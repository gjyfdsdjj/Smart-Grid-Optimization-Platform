#!/usr/bin/env python
"""Evaluate SGOP prediction models on processed GridNode holdout history."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.loaders import (  # noqa: E402
    DEFAULT_GRID_CSV_DIR,
    DEFAULT_GRID_NODE_LOAD_HISTORY_PATH,
    DEFAULT_GRID_LINE_FLOW_HISTORY_PATH,
    DEFAULT_MODEL_EVALUATION_SUMMARY_PATH,
    load_grid_dataset_or_default,
    load_processed_grid_line_flow_history,
    load_processed_grid_node_history,
)
from src.data.schemas import ForecastFeatureVector, GridDataset, HourlyLoadPrediction  # noqa: E402
from src.engine.forecast.baseline_forecaster import BaselineForecaster  # noqa: E402
from src.engine.forecast.evaluation import regression_metrics  # noqa: E402
from src.engine.forecast.lstm_forecaster import HORIZON_H, LOOKBACK_H, LSTMForecaster  # noqa: E402
from src.engine.forecast.neural_gnn_forecaster import NeuralGNNForecaster  # noqa: E402

DEFAULT_MODELS = ("baseline", "lstm", "neural_gnn", "hybrid_neural_gnn")
MODEL_ORDER = (
    "baseline",
    "lstm",
    "neural_gnn",
    "hybrid_neural_gnn",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate saved prediction models using processed SGOP GridNode history.",
    )
    parser.add_argument(
        "--history-path",
        default=str(DEFAULT_GRID_NODE_LOAD_HISTORY_PATH),
        help="Processed GridNode load history CSV path.",
    )
    parser.add_argument(
        "--line-history-path",
        default=str(DEFAULT_GRID_LINE_FLOW_HISTORY_PATH),
        help="Processed GridLine DC Power Flow label CSV path.",
    )
    parser.add_argument(
        "--grid-dir",
        default=str(DEFAULT_GRID_CSV_DIR),
        help="Grid enhanced CSV directory used for GridLine graph edges.",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_MODEL_EVALUATION_SUMMARY_PATH),
        help="Model evaluation summary CSV path.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        choices=list(MODEL_ORDER),
        help="Models to evaluate.",
    )
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--eval-step-h", type=int, default=24)
    parser.add_argument(
        "--skip-line-eval",
        action="store_true",
        help="Skip DC Power Flow line-utilization evaluation.",
    )
    args = parser.parse_args()

    history = _load_prediction_history(args.history_path)
    train_df, test_df = _time_ordered_train_test_split(
        history,
        test_ratio=args.test_ratio,
    )
    bus_ids = sorted(history["bus_id"].astype(str).unique().tolist())
    dataset = load_grid_dataset_or_default(grid_dir=args.grid_dir)
    graph_edges = _load_graph_edges(dataset)
    actual_line_history = (
        load_processed_grid_line_flow_history(args.line_history_path)
        if not args.skip_line_eval
        else pd.DataFrame()
    )
    actual_line_by_key = (
        _actual_line_utilization_by_key(actual_line_history)
        if not actual_line_history.empty
        else {}
    )
    existing_rows = _existing_summary_rows(args.summary_path)

    evaluators = _build_model_evaluators(
        train_df=train_df,
        full_history_df=history,
        graph_edges=graph_edges,
    )
    summaries: list[dict[str, object]] = []
    for model_name in args.models:
        print(f"[evaluate] {model_name}", flush=True)
        evaluation = _evaluate_model(
            predict_fn=evaluators[model_name],
            full_history_df=history,
            test_df=test_df,
            bus_ids=bus_ids,
            dataset=dataset,
            actual_line_by_key=actual_line_by_key,
            eval_step_h=args.eval_step_h,
            line_eval_enabled=not args.skip_line_eval,
        )
        summary = _summary_row(
            model_name=model_name,
            evaluation=evaluation,
            existing=existing_rows.get(model_name, {}),
            history=history,
            train_df=train_df,
            test_df=test_df,
            history_path=Path(args.history_path),
            grid_dir=Path(args.grid_dir),
            line_history_path=Path(args.line_history_path),
            test_ratio=args.test_ratio,
            eval_step_h=args.eval_step_h,
        )
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)

    _write_model_evaluation_summary(
        summaries,
        existing_rows=existing_rows,
        summary_path=Path(args.summary_path),
    )


def _load_prediction_history(path: str | Path) -> pd.DataFrame:
    processed = load_processed_grid_node_history(path)
    df = processed[
        (processed["node_type"] == "transmission_tower")
        & (pd.to_numeric(processed["load_mw"], errors="coerce") > 0.0)
    ].copy()
    if df.empty:
        raise ValueError("예측 평가 대상 송전탑 부하 이력이 없습니다.")
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(df["timestamp"]),
            "bus_id": df["node_id"].astype(str),
            "bus_name": df["node_name"].astype(str),
            "load_mw": pd.to_numeric(df["load_mw"], errors="coerce"),
            "generation_mw": pd.to_numeric(df["generation_mw"], errors="coerce"),
            "net_injection_mw": pd.to_numeric(df["net_injection_mw"], errors="coerce"),
            "load_weight": pd.to_numeric(df["load_weight"], errors="coerce"),
            "generation_weight": pd.to_numeric(df["generation_weight"], errors="coerce"),
        }
    ).sort_values(["timestamp", "bus_id"]).reset_index(drop=True)


def _time_ordered_train_test_split(
    history: pd.DataFrame,
    *,
    test_ratio: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = sorted(pd.to_datetime(history["timestamp"]).unique().tolist())
    if len(timestamps) < (LOOKBACK_H + HORIZON_H + 2):
        raise ValueError("Prediction 평가 train/test split을 만들 시간이 부족합니다.")
    resolved_ratio = min(max(float(test_ratio), 0.05), 0.40)
    split_index = max(LOOKBACK_H + HORIZON_H, int(len(timestamps) * (1.0 - resolved_ratio)))
    split_index = min(split_index, len(timestamps) - HORIZON_H - 1)
    test_start = timestamps[split_index]
    train_df = history[history["timestamp"] < test_start].copy()
    test_df = history[history["timestamp"] >= test_start].copy()
    if train_df.empty or test_df.empty:
        raise ValueError("Prediction 평가 train/test split 결과가 비어 있습니다.")
    return train_df, test_df


def _load_graph_edges(dataset: GridDataset) -> list[tuple[str, str]]:
    return [
        (line.from_node_id, line.to_node_id)
        for line in dataset.lines
        if line.status != "out_of_service"
    ]


def _build_model_evaluators(
    *,
    train_df: pd.DataFrame,
    full_history_df: pd.DataFrame,
    graph_edges: list[tuple[str, str]],
) -> dict[str, Callable[[datetime, list], list[HourlyLoadPrediction]]]:
    baseline = BaselineForecaster().fit(train_df)
    lstm = LSTMForecaster()
    neural_gnn = NeuralGNNForecaster()

    def baseline_predict(
        forecast_start: datetime,
        target_features: list,
    ) -> list[HourlyLoadPrediction]:
        del forecast_start
        return baseline.predict(target_features=target_features)

    def lstm_predict(
        forecast_start: datetime,
        target_features: list,
    ) -> list[HourlyLoadPrediction]:
        return lstm.predict(
            full_history_df,
            forecast_start=forecast_start,
            target_features=target_features,
        )

    def neural_gnn_predict(
        forecast_start: datetime,
        target_features: list,
    ) -> list[HourlyLoadPrediction]:
        return neural_gnn.predict(
            full_history_df,
            forecast_start=forecast_start,
            graph_edges=graph_edges,
            target_features=target_features,
        )

    def hybrid_neural_gnn_predict(
        forecast_start: datetime,
        target_features: list,
    ) -> list[HourlyLoadPrediction]:
        return _combine_predictions(
            primary=lstm_predict(forecast_start, target_features),
            secondary=neural_gnn_predict(forecast_start, target_features),
            primary_weight=0.65,
            secondary_weight=0.35,
        )

    return {
        "baseline": baseline_predict,
        "lstm": lstm_predict,
        "neural_gnn": neural_gnn_predict,
        "hybrid_neural_gnn": hybrid_neural_gnn_predict,
    }


def _evaluate_model(
    *,
    predict_fn: Callable[[datetime, list], list[HourlyLoadPrediction]],
    full_history_df: pd.DataFrame,
    test_df: pd.DataFrame,
    bus_ids: list[str],
    dataset: GridDataset,
    actual_line_by_key: dict[tuple[datetime, str], float],
    eval_step_h: int,
    line_eval_enabled: bool,
) -> dict[str, object]:
    actual_by_key = {
        (pd.Timestamp(row.timestamp).to_pydatetime(), row.bus_id): float(row.load_mw)
        for row in test_df.itertuples(index=False)
    }
    test_timestamps = sorted(pd.to_datetime(test_df["timestamp"]).unique().tolist())
    first_start = pd.Timestamp(test_timestamps[0]).to_pydatetime()
    last_start = pd.Timestamp(test_timestamps[-1]).to_pydatetime()
    step = max(1, int(eval_step_h))

    y_true: list[float] = []
    y_pred: list[float] = []
    line_true: list[float] = []
    line_pred: list[float] = []
    risk_counts: list[int] = []
    critical_counts: list[int] = []
    max_utils: list[float] = []
    forecast_start_count = 0
    line_forecast_start_count = 0

    current_start = first_start
    while current_start <= last_start:
        target_features = _build_eval_target_features(
            forecast_start=current_start,
            bus_ids=bus_ids,
            horizon_h=HORIZON_H,
        )
        predictions = predict_fn(current_start, target_features)
        matched = 0
        for prediction in predictions:
            actual = actual_by_key.get((prediction.timestamp, prediction.bus_id))
            if actual is None:
                continue
            y_true.append(actual)
            y_pred.append(float(prediction.predicted_load_mw))
            matched += 1
        if matched:
            forecast_start_count += 1

        if line_eval_enabled and actual_line_by_key:
            line_metrics = _line_metrics_for_predictions(
                predictions=predictions,
                dataset=dataset,
                actual_line_by_key=actual_line_by_key,
            )
            if line_metrics["sample_count"] > 0:
                line_true.extend(line_metrics["actual_utilizations"])
                line_pred.extend(line_metrics["predicted_utilizations"])
                risk_counts.append(int(line_metrics["future_risk_line_count"]))
                critical_counts.append(int(line_metrics["future_critical_or_overload_line_count"]))
                max_utils.append(float(line_metrics["max_predicted_utilization"]))
                line_forecast_start_count += 1

        current_start = current_start + pd.Timedelta(hours=step).to_pytimedelta()

    if not y_true:
        raise ValueError("Prediction 평가에 사용할 실제/예측 쌍이 없습니다.")
    node_metrics = regression_metrics(np.asarray(y_true), np.asarray(y_pred))
    result: dict[str, object] = {
        **node_metrics,
        "sample_count": len(y_true),
        "forecast_start_count": forecast_start_count,
    }
    if line_true and line_pred:
        line_metrics = regression_metrics(np.asarray(line_true), np.asarray(line_pred))
        result.update(
            {
                "line_sample_count": len(line_true),
                "line_forecast_start_count": line_forecast_start_count,
                "line_utilization_mae_pp": line_metrics["mae"] * 100.0,
                "line_utilization_rmse_pp": line_metrics["rmse"] * 100.0,
                "line_utilization_mape_pct": line_metrics["mape"],
                "mean_future_risk_line_count": float(np.mean(risk_counts)) if risk_counts else 0.0,
                "mean_future_critical_or_overload_line_count": (
                    float(np.mean(critical_counts)) if critical_counts else 0.0
                ),
                "mean_max_line_utilization": float(np.mean(max_utils)) if max_utils else 0.0,
                "max_predicted_line_utilization": float(np.max(max_utils)) if max_utils else 0.0,
            }
        )
    return result


def _build_eval_target_features(
    *,
    forecast_start: datetime,
    bus_ids: list[str],
    horizon_h: int,
) -> list[ForecastFeatureVector]:
    features: list[ForecastFeatureVector] = []
    for hour_offset in range(1, horizon_h + 1):
        timestamp = forecast_start + pd.Timedelta(hours=hour_offset).to_pytimedelta()
        for bus_id in bus_ids:
            features.append(
                ForecastFeatureVector(
                    timestamp=timestamp,
                    bus_id=bus_id,
                    load_lag_1h=0.0,
                    load_lag_6h=0.0,
                    load_lag_12h=0.0,
                    load_lag_24h=0.0,
                    load_lag_48h=0.0,
                    load_lag_72h=0.0,
                    hour=timestamp.hour,
                    day_of_week=timestamp.weekday(),
                    is_weekend=timestamp.weekday() >= 5,
                    is_holiday=False,
                    month=timestamp.month,
                    total_generation_mw=0.0,
                    regional_demand_ratio=0.0,
                )
            )
    return features


def _line_metrics_for_predictions(
    *,
    predictions: list[HourlyLoadPrediction],
    dataset: GridDataset,
    actual_line_by_key: dict[tuple[datetime, str], float],
) -> dict[str, object]:
    if not predictions:
        return {
            "sample_count": 0,
            "actual_utilizations": [],
            "predicted_utilizations": [],
            "future_risk_line_count": 0,
            "future_critical_or_overload_line_count": 0,
            "max_predicted_utilization": 0.0,
        }

    prediction_by_key = {
        (prediction.timestamp, prediction.bus_id): float(prediction.predicted_load_mw)
        for prediction in predictions
    }
    timestamps = sorted({prediction.timestamp for prediction in predictions})
    actual_values: list[float] = []
    predicted_values: list[float] = []
    peak_by_line: dict[str, float] = {}
    for timestamp in timestamps:
        for line in dataset.lines:
            if line.status == "out_of_service":
                continue
            from_load = prediction_by_key.get((timestamp, line.from_node_id), 0.0)
            to_load = prediction_by_key.get((timestamp, line.to_node_id), 0.0)
            endpoint_pressure = max(0.0, from_load, to_load)
            imbalance = abs(from_load - to_load)
            terrain_factor = 1.0 + (float(line.terrain_risk) * 0.04)
            flow_mw = ((endpoint_pressure * 0.95) + (imbalance * 0.20)) * terrain_factor
            utilization = flow_mw / line.capacity_mw if line.capacity_mw > 0.0 else 0.0
            actual = actual_line_by_key.get((timestamp, line.line_id))
            if actual is not None:
                actual_values.append(float(actual))
                predicted_values.append(float(utilization))
            peak_by_line[line.line_id] = max(
                peak_by_line.get(line.line_id, 0.0),
                float(utilization),
            )

    peak_values = list(peak_by_line.values())
    risk_count = sum(1 for value in peak_values if value >= 0.55)
    critical_count = sum(1 for value in peak_values if value >= 0.90)
    return {
        "sample_count": len(actual_values),
        "actual_utilizations": actual_values,
        "predicted_utilizations": predicted_values,
        "future_risk_line_count": risk_count,
        "future_critical_or_overload_line_count": critical_count,
        "max_predicted_utilization": max(peak_values) if peak_values else 0.0,
    }
def _actual_line_utilization_by_key(
    actual_line_history: pd.DataFrame,
) -> dict[tuple[datetime, str], float]:
    history = actual_line_history.copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"])
    return {
        (pd.Timestamp(row.timestamp).to_pydatetime(), str(row.line_id)): float(row.utilization)
        for row in history.itertuples(index=False)
    }


def _combine_predictions(
    *,
    primary: list[HourlyLoadPrediction],
    secondary: list[HourlyLoadPrediction],
    primary_weight: float,
    secondary_weight: float,
) -> list[HourlyLoadPrediction]:
    secondary_by_key = {
        (prediction.timestamp, prediction.bus_id): prediction
        for prediction in secondary
    }
    total_weight = primary_weight + secondary_weight
    combined: list[HourlyLoadPrediction] = []
    for prediction in primary:
        key = (prediction.timestamp, prediction.bus_id)
        secondary_prediction = secondary_by_key.get(key)
        if secondary_prediction is None:
            raise ValueError(f"Hybrid 평가 예측 키가 맞지 않습니다: {key}")
        predicted_load = (
            prediction.predicted_load_mw * primary_weight
            + secondary_prediction.predicted_load_mw * secondary_weight
        ) / total_weight
        lower_bound = (
            prediction.confidence_lower_mw * primary_weight
            + secondary_prediction.confidence_lower_mw * secondary_weight
        ) / total_weight
        upper_bound = (
            prediction.confidence_upper_mw * primary_weight
            + secondary_prediction.confidence_upper_mw * secondary_weight
        ) / total_weight
        combined.append(
            HourlyLoadPrediction(
                timestamp=prediction.timestamp,
                bus_id=prediction.bus_id,
                predicted_load_mw=round(max(0.0, predicted_load), 1),
                confidence_lower_mw=round(max(0.0, lower_bound), 1),
                confidence_upper_mw=round(max(predicted_load, upper_bound), 1),
            )
        )
    return combined


def _summary_row(
    *,
    model_name: str,
    evaluation: dict[str, object],
    existing: dict[str, object],
    history: pd.DataFrame,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    history_path: Path,
    grid_dir: Path,
    line_history_path: Path,
    test_ratio: float,
    eval_step_h: int,
) -> dict[str, object]:
    row = dict(existing)
    row.update(
        {
            "model": model_name,
            "data_source": _portable_path(history_path),
            "graph_source": _portable_path(grid_dir / "lines.csv"),
            "line_label_source": _portable_path(line_history_path),
            "evaluation_kind": "holdout_rolling_24h",
            "line_evaluation_method": "predicted_endpoint_pressure_proxy_vs_dc_power_flow_label",
            "node_count": int(history["bus_id"].nunique()),
            "history_rows": int(len(history)),
            "history_start": pd.Timestamp(history["timestamp"].min()).isoformat(),
            "history_end": pd.Timestamp(history["timestamp"].max()).isoformat(),
            "train_start": pd.Timestamp(train_df["timestamp"].min()).isoformat(),
            "train_end": pd.Timestamp(train_df["timestamp"].max()).isoformat(),
            "test_start": pd.Timestamp(test_df["timestamp"].min()).isoformat(),
            "test_end": pd.Timestamp(test_df["timestamp"].max()).isoformat(),
            "lookback_h": LOOKBACK_H,
            "horizon_h": HORIZON_H,
            "test_ratio": float(test_ratio),
            "eval_step_h": int(eval_step_h),
            "sample_count": int(evaluation["sample_count"]),
            "forecast_start_count": int(evaluation["forecast_start_count"]),
            "mae_mw": float(evaluation["mae"]),
            "rmse_mw": float(evaluation["rmse"]),
            "mape_pct": float(evaluation["mape"]),
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
        }
    )
    optional_float_fields = (
        "line_sample_count",
        "line_forecast_start_count",
        "line_utilization_mae_pp",
        "line_utilization_rmse_pp",
        "line_utilization_mape_pct",
        "mean_future_risk_line_count",
        "mean_future_critical_or_overload_line_count",
        "mean_max_line_utilization",
        "max_predicted_line_utilization",
    )
    for field in optional_float_fields:
        if field in evaluation:
            row[field] = evaluation[field]

    if model_name == "baseline":
        row.setdefault("model_path", "")
        row.setdefault("training_history_path", "")
        row.setdefault("evaluation_summary_path", "")
    elif model_name == "hybrid_neural_gnn":
        row.update(
            {
                "model_path": "models/lstm/model.keras + models/gnn/model.pt",
                "training_history_path": "models/lstm/training_history.csv + models/gnn/training_history.csv",
                "evaluation_summary_path": "data/processed/model_evaluation_summary.csv",
                "hybrid_primary": "lstm",
                "hybrid_secondary": "neural_gnn",
                "hybrid_primary_weight": 0.65,
                "hybrid_secondary_weight": 0.35,
            }
        )
    return row


def _existing_summary_rows(path: str | Path) -> dict[str, dict[str, object]]:
    resolved = Path(path)
    if not resolved.exists():
        return {}
    existing = pd.read_csv(resolved)
    if existing.empty or "model" not in existing.columns:
        return {}
    rows: dict[str, dict[str, object]] = {}
    for row in existing.to_dict("records"):
        model = str(row.get("model", "")).strip()
        if model:
            rows[model] = {
                key: _clean_cell(value)
                for key, value in row.items()
            }
    return rows


def _write_model_evaluation_summary(
    summaries: list[dict[str, object]],
    *,
    existing_rows: dict[str, dict[str, object]],
    summary_path: Path,
) -> None:
    merged = dict(existing_rows)
    for summary in summaries:
        merged[str(summary["model"])] = summary

    ordered_rows = [
        merged[model]
        for model in MODEL_ORDER
        if model in merged
    ]
    ordered_rows.extend(
        row
        for model, row in sorted(merged.items())
        if model not in MODEL_ORDER
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(ordered_rows).to_csv(summary_path, index=False)


def _clean_cell(value: object) -> object:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        return value
    return value


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
