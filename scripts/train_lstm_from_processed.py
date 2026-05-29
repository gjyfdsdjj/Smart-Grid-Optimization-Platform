#!/usr/bin/env python
"""Train the LSTM forecaster from processed SGOP GridNode load history."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.loaders import (  # noqa: E402
    DEFAULT_GRID_NODE_LOAD_HISTORY_PATH,
    load_processed_grid_node_history,
)
from src.engine.forecast.evaluation import regression_metrics  # noqa: E402
from src.engine.forecast.lstm_forecaster import HORIZON_H, LOOKBACK_H, LSTMForecaster  # noqa: E402

MODEL_DIR = ROOT / "models" / "lstm"
EVALUATION_PATH = MODEL_DIR / "evaluation_summary.json"
MODEL_EVALUATION_SUMMARY_PATH = ROOT / "data" / "processed" / "model_evaluation_summary.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train LSTM from data/processed/grid_node_load_history.csv",
    )
    parser.add_argument(
        "--history-path",
        default=str(DEFAULT_GRID_NODE_LOAD_HISTORY_PATH),
        help="Processed GridNode load history CSV path.",
    )
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--validation-split", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--eval-step-h", type=int, default=24)
    args = parser.parse_args()

    history = _load_lstm_history(args.history_path)
    train_df, test_df = _time_ordered_train_test_split(
        history,
        test_ratio=args.test_ratio,
    )
    forecaster = LSTMForecaster().fit(
        train_df,
        epochs=args.epochs,
        batch_size=args.batch_size,
        validation_split=args.validation_split,
    )
    evaluation = _evaluate_lstm(
        forecaster,
        full_history_df=history,
        test_df=test_df,
        eval_step_h=args.eval_step_h,
    )
    training_metadata = forecaster.training_metadata()
    summary = {
        "model": "lstm",
        "data_source": _portable_path(Path(args.history_path)),
        "node_count": int(history["bus_id"].nunique()),
        "history_rows": int(len(history)),
        "history_start": history["timestamp"].min().isoformat(),
        "history_end": history["timestamp"].max().isoformat(),
        "train_start": train_df["timestamp"].min().isoformat(),
        "train_end": train_df["timestamp"].max().isoformat(),
        "test_start": test_df["timestamp"].min().isoformat(),
        "test_end": test_df["timestamp"].max().isoformat(),
        "lookback_h": LOOKBACK_H,
        "horizon_h": HORIZON_H,
        "epochs_requested": int(args.epochs),
        "epochs_trained": int(training_metadata.get("epochs_trained", 0)),
        "batch_size": int(args.batch_size),
        "validation_split": float(args.validation_split),
        "test_ratio": float(args.test_ratio),
        "eval_step_h": int(args.eval_step_h),
        "sample_count": int(evaluation["sample_count"]),
        "forecast_start_count": int(evaluation["forecast_start_count"]),
        "mae_mw": float(evaluation["mae"]),
        "rmse_mw": float(evaluation["rmse"]),
        "mape_pct": float(evaluation["mape"]),
        "created_at": datetime.now().replace(microsecond=0).isoformat(),
        "model_path": training_metadata.get("model_path", "models/lstm/model.keras"),
        "scaler_path": training_metadata.get("scaler_path", "models/lstm/scalers.pkl"),
        "training_history_path": training_metadata.get(
            "training_history_path",
            "models/lstm/training_history.csv",
        ),
        "evaluation_summary_path": _portable_path(EVALUATION_PATH),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    EVALUATION_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_model_evaluation_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _load_lstm_history(path: str | Path) -> pd.DataFrame:
    processed = load_processed_grid_node_history(path)
    df = processed[
        (processed["node_type"] == "transmission_tower")
        & (pd.to_numeric(processed["load_mw"], errors="coerce") > 0.0)
    ].copy()
    if df.empty:
        raise ValueError("LSTM 학습 대상 송전탑 부하 이력이 없습니다.")
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
        raise ValueError("LSTM train/test split을 만들 시간이 부족합니다.")
    resolved_ratio = min(max(float(test_ratio), 0.05), 0.40)
    split_index = max(LOOKBACK_H + HORIZON_H, int(len(timestamps) * (1.0 - resolved_ratio)))
    split_index = min(split_index, len(timestamps) - HORIZON_H - 1)
    test_start = timestamps[split_index]
    train_df = history[history["timestamp"] < test_start].copy()
    test_df = history[history["timestamp"] >= test_start].copy()
    if train_df.empty or test_df.empty:
        raise ValueError("LSTM train/test split 결과가 비어 있습니다.")
    return train_df, test_df


def _evaluate_lstm(
    forecaster: LSTMForecaster,
    *,
    full_history_df: pd.DataFrame,
    test_df: pd.DataFrame,
    eval_step_h: int,
) -> dict[str, float | int]:
    actual_by_key = {
        (row.timestamp.to_pydatetime(), row.bus_id): float(row.load_mw)
        for row in test_df.itertuples(index=False)
    }
    test_timestamps = sorted(pd.to_datetime(test_df["timestamp"]).unique().tolist())
    first_start = pd.Timestamp(test_timestamps[0]).to_pydatetime()
    last_start = pd.Timestamp(test_timestamps[-1]).to_pydatetime()
    step = max(1, int(eval_step_h))

    y_true: list[float] = []
    y_pred: list[float] = []
    forecast_start_count = 0
    current_start = first_start
    while current_start <= last_start:
        predictions = forecaster.predict(
            full_history_df,
            forecast_start=current_start,
            horizon_h=HORIZON_H,
        )
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
        current_start = current_start + pd.Timedelta(hours=step).to_pytimedelta()

    if not y_true:
        raise ValueError("LSTM 평가에 사용할 실제/예측 쌍이 없습니다.")
    metrics = regression_metrics(np.asarray(y_true), np.asarray(y_pred))
    return {
        **metrics,
        "sample_count": len(y_true),
        "forecast_start_count": forecast_start_count,
    }


def _write_model_evaluation_summary(summary: dict[str, object]) -> None:
    MODEL_EVALUATION_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        key: value
        for key, value in summary.items()
        if not isinstance(value, (dict, list))
    }
    existing = (
        pd.read_csv(MODEL_EVALUATION_SUMMARY_PATH)
        if MODEL_EVALUATION_SUMMARY_PATH.exists()
        else pd.DataFrame()
    )
    if not existing.empty and "model" in existing.columns:
        existing = existing[existing["model"] != "lstm"]
    next_df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    next_df.to_csv(MODEL_EVALUATION_SUMMARY_PATH, index=False)


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
