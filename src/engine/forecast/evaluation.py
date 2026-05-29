# 예측 모델 평가 지표를 공통 계산한다.
from __future__ import annotations

import numpy as np


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error."""

    true = np.asarray(y_true, dtype=np.float32)
    pred = np.asarray(y_pred, dtype=np.float32)
    return float(np.mean(np.abs(true - pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""

    true = np.asarray(y_true, dtype=np.float32)
    pred = np.asarray(y_pred, dtype=np.float32)
    return float(np.sqrt(np.mean((true - pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, epsilon: float = 1e-6) -> float:
    """Mean Absolute Percentage Error, percent scale."""

    true = np.asarray(y_true, dtype=np.float32)
    pred = np.asarray(y_pred, dtype=np.float32)
    mask = np.abs(true) > epsilon
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((true[mask] - pred[mask]) / true[mask])) * 100.0)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """Forecast comparison metrics in one shape-stable mapping."""

    return {
        "mae": mae(y_true, y_pred),
        "rmse": rmse(y_true, y_pred),
        "mape": mape(y_true, y_pred),
    }
