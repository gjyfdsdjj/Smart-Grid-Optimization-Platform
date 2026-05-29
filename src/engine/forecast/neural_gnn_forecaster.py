# PyTorch 기반 최소 Neural GNN 부하 예측기.
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.schemas import ForecastFeatureVector, HourlyLoadPrediction
from src.engine.forecast.evaluation import regression_metrics

LOOKBACK_H = 24
HORIZON_H = 24
FEATURE_DIM = 4  # load_norm, hour_sin, hour_cos, is_weekend
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "gnn"


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _group_target_features(
    target_features: list[ForecastFeatureVector],
) -> dict[str, list[ForecastFeatureVector]]:
    grouped: dict[str, list[ForecastFeatureVector]] = {}
    for feature in target_features:
        grouped.setdefault(feature.bus_id, []).append(feature)
    for features in grouped.values():
        features.sort(key=lambda item: item.timestamp)
    return grouped


def _time_features(timestamps: list[datetime] | pd.Series | pd.DatetimeIndex) -> np.ndarray:
    ts = pd.to_datetime(pd.Series(timestamps))
    hour = ts.dt.hour.to_numpy()
    dow = ts.dt.dayofweek.to_numpy()
    return np.stack(
        [
            np.sin(2 * np.pi * hour / 24.0),
            np.cos(2 * np.pi * hour / 24.0),
            (dow >= 5).astype(float),
        ],
        axis=1,
    ).astype(np.float32)


def _prepare_matrix(history_df: pd.DataFrame, bus_ids: list[str] | None = None) -> tuple[np.ndarray, list[str], list[datetime]]:
    df = history_df.copy()
    if df.empty:
        raise ValueError("Neural GNN 학습 이력이 비어 있습니다.")
    required = {"timestamp", "bus_id", "load_mw"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Neural GNN 입력 컬럼이 부족합니다: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    resolved_bus_ids = bus_ids or sorted(df["bus_id"].dropna().unique().tolist())
    if not resolved_bus_ids:
        raise ValueError("Neural GNN 학습 대상 bus_id가 없습니다.")

    pivot = (
        df.pivot_table(
            index="timestamp",
            columns="bus_id",
            values="load_mw",
            aggfunc="mean",
        )
        .sort_index()
        .reindex(columns=resolved_bus_ids)
    )
    if pivot.empty:
        raise ValueError("Neural GNN 학습용 load matrix를 만들 수 없습니다.")

    pivot = pivot.ffill().bfill()
    for bus_id in resolved_bus_ids:
        if pivot[bus_id].isna().any():
            fallback = float(df[df["bus_id"] == bus_id]["load_mw"].mean())
            if not np.isfinite(fallback):
                fallback = float(df["load_mw"].mean())
            pivot[bus_id] = pivot[bus_id].fillna(fallback)

    return (
        pivot.to_numpy(dtype=np.float32),
        resolved_bus_ids,
        [pd.Timestamp(ts).to_pydatetime() for ts in pivot.index.tolist()],
    )


def _normalize_adjacency(bus_ids: list[str], graph_edges: list[tuple[str, str]] | None) -> np.ndarray:
    node_count = len(bus_ids)
    index = {bus_id: i for i, bus_id in enumerate(bus_ids)}
    adjacency = np.eye(node_count, dtype=np.float32)
    for from_bus, to_bus in graph_edges or []:
        if from_bus not in index or to_bus not in index:
            continue
        i = index[from_bus]
        j = index[to_bus]
        adjacency[i, j] = 1.0
        adjacency[j, i] = 1.0

    degree = adjacency.sum(axis=1)
    degree[degree == 0.0] = 1.0
    inv_sqrt = np.diag(1.0 / np.sqrt(degree))
    return (inv_sqrt @ adjacency @ inv_sqrt).astype(np.float32)


def _build_windows(
    matrix_norm: np.ndarray,
    timestamps: list[datetime],
    lookback_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    X: list[np.ndarray] = []
    y: list[np.ndarray] = []
    sample_count = len(timestamps) - lookback_h
    if sample_count <= 0:
        raise ValueError(
            f"Neural GNN 학습 이력이 부족합니다. 최소 {lookback_h + 1}시간이 필요합니다."
        )

    node_count = matrix_norm.shape[1]
    for start in range(sample_count):
        end = start + lookback_h
        load_window = matrix_norm[start:end].reshape(lookback_h, node_count, 1)
        time_window = _time_features(timestamps[start:end])
        time_window = np.repeat(time_window[:, np.newaxis, :], node_count, axis=1)
        X.append(np.concatenate([load_window, time_window], axis=2))
        y.append(matrix_norm[end])

    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32)


class _GraphTemporalNet:
    def __init__(self, node_count: int, lookback_h: int, feature_dim: int, hidden_dim: int) -> None:
        import torch
        from torch import nn

        class Model(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.temporal = nn.Sequential(
                    nn.Linear(lookback_h * feature_dim, hidden_dim),
                    nn.ReLU(),
                    nn.Dropout(0.1),
                )
                self.graph_linear = nn.Linear(hidden_dim, hidden_dim)
                self.output = nn.Linear(hidden_dim, 1)

            def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
                batch_size = x.shape[0]
                x = x.permute(0, 2, 1, 3).reshape(batch_size, node_count, lookback_h * feature_dim)
                h = self.temporal(x)
                h = torch.einsum("ij,bjh->bih", adj, h)
                h = torch.relu(self.graph_linear(h))
                return self.output(h).squeeze(-1)

        self.model = Model()


class NeuralGNNForecaster:
    """GridLine adjacency를 사용하는 학습형 최소 GNN 예측기."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        *,
        lookback_h: int = LOOKBACK_H,
        horizon_h: int = HORIZON_H,
        hidden_dim: int = 32,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else DEFAULT_MODEL_DIR
        self.model_path = self.model_dir / "model.pt"
        self.history_path = self.model_dir / "training_history.csv"
        self.metadata_path = self.model_dir / "metadata.json"
        self.evaluation_path = self.model_dir / "evaluation_summary.json"
        self.node_error_path = self.model_dir / "node_error_summary.csv"
        self.lookback_h = lookback_h
        self.horizon_h = horizon_h
        self.hidden_dim = hidden_dim
        self.feature_dim = FEATURE_DIM

    def fit_or_load(
        self,
        history_df: pd.DataFrame,
        *,
        graph_edges: list[tuple[str, str]] | None = None,
        retrain: bool = False,
        epochs: int = 20,
        batch_size: int = 64,
        learning_rate: float = 0.003,
        patience: int = 5,
    ) -> "NeuralGNNForecaster":
        matrix, bus_ids, _ = _prepare_matrix(history_df)
        if not retrain and self._load_if_compatible(bus_ids):
            return self
        return self.fit(
            history_df,
            graph_edges=graph_edges,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            patience=patience,
        )

    def fit(
        self,
        history_df: pd.DataFrame,
        *,
        graph_edges: list[tuple[str, str]] | None = None,
        epochs: int = 20,
        batch_size: int = 64,
        learning_rate: float = 0.003,
        patience: int = 5,
    ) -> "NeuralGNNForecaster":
        import torch
        from torch import nn

        torch.manual_seed(42)
        np.random.seed(42)

        matrix, bus_ids, timestamps = _prepare_matrix(history_df)
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds < 1e-6] = 1.0
        matrix_norm = (matrix - means) / stds
        X, y = _build_windows(matrix_norm, timestamps, self.lookback_h)

        sample_count = X.shape[0]
        if sample_count < 4:
            train_end = max(1, sample_count - 1)
            val_end = sample_count
        else:
            train_end = max(1, int(sample_count * 0.70))
            val_end = max(train_end + 1, int(sample_count * 0.85))
            val_end = min(sample_count, val_end)

        X_train, y_train = X[:train_end], y[:train_end]
        X_val, y_val = X[train_end:val_end], y[train_end:val_end]
        X_test, y_test = X[val_end:], y[val_end:]
        if len(X_val) == 0:
            X_val, y_val = X_train[-1:], y_train[-1:]
        if len(X_test) == 0:
            X_test, y_test = X_val, y_val

        adj_np = _normalize_adjacency(bus_ids, graph_edges)
        net = _GraphTemporalNet(
            node_count=len(bus_ids),
            lookback_h=self.lookback_h,
            feature_dim=self.feature_dim,
            hidden_dim=self.hidden_dim,
        ).model
        optimizer = torch.optim.Adam(net.parameters(), lr=learning_rate)
        loss_fn = nn.MSELoss()
        adj = torch.tensor(adj_np, dtype=torch.float32)
        X_train_t = torch.tensor(X_train, dtype=torch.float32)
        y_train_t = torch.tensor(y_train, dtype=torch.float32)
        X_val_t = torch.tensor(X_val, dtype=torch.float32)
        y_val_t = torch.tensor(y_val, dtype=torch.float32)

        best_state: dict[str, Any] | None = None
        best_val = float("inf")
        stale_epochs = 0
        history_rows: list[dict[str, float | int]] = []
        epochs = max(1, int(epochs))
        batch_size = max(1, int(batch_size))

        for epoch in range(1, epochs + 1):
            net.train()
            permutation = torch.randperm(len(X_train_t))
            train_losses: list[float] = []
            for start in range(0, len(X_train_t), batch_size):
                batch_idx = permutation[start:start + batch_size]
                pred = net(X_train_t[batch_idx], adj)
                loss = loss_fn(pred, y_train_t[batch_idx])
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                train_losses.append(float(loss.detach().cpu().item()))

            net.eval()
            with torch.no_grad():
                val_pred = net(X_val_t, adj)
                val_loss = float(loss_fn(val_pred, y_val_t).detach().cpu().item())
            train_loss = float(np.mean(train_losses)) if train_losses else val_loss
            history_rows.append(
                {
                    "epoch": epoch,
                    "train_loss": train_loss,
                    "val_loss": val_loss,
                }
            )

            if val_loss < best_val:
                best_val = val_loss
                best_state = {
                    key: value.detach().cpu().clone()
                    for key, value in net.state_dict().items()
                }
                stale_epochs = 0
            else:
                stale_epochs += 1
            if stale_epochs >= max(1, patience):
                break

        if best_state is not None:
            net.load_state_dict(best_state)

        X_test_t = torch.tensor(X_test, dtype=torch.float32)
        with torch.no_grad():
            test_pred_norm = net(X_test_t, adj).detach().cpu().numpy()
        y_test_mw = (y_test * stds) + means
        y_pred_mw = (test_pred_norm * stds) + means
        metrics = regression_metrics(y_test_mw, y_pred_mw)
        node_mae_mw = np.mean(np.abs(y_test_mw - y_pred_mw), axis=0)

        self.model_dir.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": net.state_dict(),
                "bus_ids": bus_ids,
                "means": means.astype(np.float32),
                "stds": stds.astype(np.float32),
                "node_mae_mw": node_mae_mw.astype(np.float32),
                "lookback_h": self.lookback_h,
                "horizon_h": self.horizon_h,
                "feature_dim": self.feature_dim,
                "hidden_dim": self.hidden_dim,
            },
            self.model_path,
        )
        pd.DataFrame(history_rows).to_csv(self.history_path, index=False)
        metadata = {
            "model_type": "neural_gnn",
            "framework": "torch",
            "deep_learning": True,
            "bus_ids": bus_ids,
            "node_count": len(bus_ids),
            "graph_edge_count": len(graph_edges or []),
            "lookback_h": self.lookback_h,
            "horizon_h": self.horizon_h,
            "epochs_requested": epochs,
            "epochs_trained": len(history_rows),
            "train_loss_final": history_rows[-1]["train_loss"],
            "val_loss_best": best_val,
            "test_mae": metrics["mae"],
            "test_rmse": metrics["rmse"],
            "test_mape": metrics["mape"],
            "model_path": _portable_path(self.model_path),
            "training_history_path": _portable_path(self.history_path),
            "evaluation_summary_path": _portable_path(self.evaluation_path),
            "node_error_summary_path": _portable_path(self.node_error_path),
        }
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._model = net
        self._bus_ids = bus_ids
        self._means = means.astype(np.float32)
        self._stds = stds.astype(np.float32)
        self._node_mae_mw = node_mae_mw.astype(np.float32)
        self._metadata = metadata
        self._training_history = history_rows
        return self

    def predict(
        self,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        *,
        graph_edges: list[tuple[str, str]] | None = None,
        horizon_h: int | None = None,
        target_features: list[ForecastFeatureVector] | None = None,
    ) -> list[HourlyLoadPrediction]:
        import torch

        self._load_if_needed()
        targets_by_bus: dict[str, list[ForecastFeatureVector]] = {}
        if target_features is not None:
            targets_by_bus = _group_target_features(target_features)
            unknown = sorted(set(targets_by_bus) - set(self._bus_ids))
            if unknown:
                raise ValueError(f"Neural GNN target_features에 학습되지 않은 bus_id가 포함되어 있습니다: {unknown}")
            horizon_h = len(sorted({feature.timestamp for feature in target_features}))
        resolved_horizon = int(horizon_h or self.horizon_h)

        matrix, _, timestamps = _prepare_matrix(history_df, bus_ids=self._bus_ids)
        matrix_norm = (matrix - self._means) / self._stds
        history_pairs = [
            (ts, matrix_norm[index])
            for index, ts in enumerate(timestamps)
            if ts <= forecast_start - timedelta(hours=1)
        ]
        if not history_pairs:
            history_pairs = list(zip(timestamps, matrix_norm))
        recent_values = [value for _, value in history_pairs[-self.lookback_h:]]
        recent_timestamps = [ts for ts, _ in history_pairs[-self.lookback_h:]]
        if len(recent_values) < self.lookback_h:
            pad_count = self.lookback_h - len(recent_values)
            pad_value = np.zeros(len(self._bus_ids), dtype=np.float32)
            first_ts = recent_timestamps[0] if recent_timestamps else forecast_start - timedelta(hours=self.lookback_h)
            pad_timestamps = [
                first_ts - timedelta(hours=pad_count - idx)
                for idx in range(pad_count)
            ]
            recent_values = [pad_value.copy() for _ in range(pad_count)] + recent_values
            recent_timestamps = pad_timestamps + recent_timestamps

        adj = torch.tensor(
            _normalize_adjacency(self._bus_ids, graph_edges),
            dtype=torch.float32,
        )
        prediction_map: dict[tuple[datetime, str], HourlyLoadPrediction] = {}
        self._model.eval()
        for step in range(1, resolved_horizon + 1):
            window_load = np.stack(recent_values[-self.lookback_h:], axis=0).reshape(
                self.lookback_h,
                len(self._bus_ids),
                1,
            )
            window_time = _time_features(recent_timestamps[-self.lookback_h:])
            window_time = np.repeat(window_time[:, np.newaxis, :], len(self._bus_ids), axis=1)
            X = np.concatenate([window_load, window_time], axis=2)[np.newaxis].astype(np.float32)
            with torch.no_grad():
                pred_norm = self._model(torch.tensor(X, dtype=torch.float32), adj).detach().cpu().numpy()[0]
            pred_mw = np.maximum(0.0, (pred_norm * self._stds) + self._means)
            target_ts = forecast_start + timedelta(hours=step)
            for node_index, bus_id in enumerate(self._bus_ids):
                value = float(pred_mw[node_index])
                ci = max(float(self._node_mae_mw[node_index]) * 1.25, value * 0.05)
                prediction_map[(target_ts, bus_id)] = HourlyLoadPrediction(
                    timestamp=target_ts,
                    bus_id=bus_id,
                    predicted_load_mw=round(value, 1),
                    confidence_lower_mw=round(max(0.0, value - ci), 1),
                    confidence_upper_mw=round(value + ci, 1),
                )
            recent_values.append(pred_norm.astype(np.float32))
            recent_timestamps.append(target_ts)

        if target_features is None:
            return sorted(prediction_map.values(), key=lambda item: (item.timestamp, item.bus_id))
        return [
            prediction_map[(feature.timestamp, feature.bus_id)]
            for feature in target_features
            if (feature.timestamp, feature.bus_id) in prediction_map
        ]

    def is_trained(self) -> bool:
        return self.model_path.exists() and self.metadata_path.exists()

    def training_metadata(self) -> dict[str, object]:
        if hasattr(self, "_metadata"):
            return self._with_evaluation_metadata(dict(self._metadata))
        if self.metadata_path.exists():
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return self._with_evaluation_metadata(metadata)
        return self._with_evaluation_metadata({})

    def training_history(self) -> list[dict[str, float | int]]:
        if hasattr(self, "_training_history"):
            return list(self._training_history)
        if self.history_path.exists():
            return pd.read_csv(self.history_path).to_dict("records")
        return []

    def _load_if_compatible(self, bus_ids: list[str]) -> bool:
        if not self.is_trained():
            return False
        metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if metadata.get("bus_ids") != bus_ids:
            return False
        self._load_if_needed()
        return True

    def _load_if_needed(self) -> None:
        if hasattr(self, "_model"):
            return
        if not self.is_trained():
            raise RuntimeError("학습된 Neural GNN 모델이 없습니다. fit() 을 먼저 실행하세요.")

        import torch

        checkpoint = torch.load(self.model_path, map_location="cpu", weights_only=False)
        self.lookback_h = int(checkpoint["lookback_h"])
        self.horizon_h = int(checkpoint["horizon_h"])
        self.feature_dim = int(checkpoint["feature_dim"])
        self.hidden_dim = int(checkpoint["hidden_dim"])
        self._bus_ids = list(checkpoint["bus_ids"])
        self._means = np.asarray(checkpoint["means"], dtype=np.float32)
        self._stds = np.asarray(checkpoint["stds"], dtype=np.float32)
        self._node_mae_mw = np.asarray(checkpoint["node_mae_mw"], dtype=np.float32)
        net = _GraphTemporalNet(
            node_count=len(self._bus_ids),
            lookback_h=self.lookback_h,
            feature_dim=self.feature_dim,
            hidden_dim=self.hidden_dim,
        ).model
        net.load_state_dict(checkpoint["state_dict"])
        self._model = net
        self._metadata = self.training_metadata()
        self._training_history = self.training_history()

    def _with_evaluation_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        if not self.evaluation_path.exists():
            return metadata

        evaluation = json.loads(self.evaluation_path.read_text(encoding="utf-8"))
        metadata.update(
            {
                "evaluation_summary_path": _portable_path(self.evaluation_path),
                "test_mae": evaluation.get("mae_mw"),
                "test_rmse": evaluation.get("rmse_mw"),
                "test_mape": evaluation.get("mape_pct"),
                "evaluation_summary": evaluation,
            }
        )
        if self.node_error_path.exists():
            metadata["node_error_summary_path"] = _portable_path(self.node_error_path)
        return metadata
