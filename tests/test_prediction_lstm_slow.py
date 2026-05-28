from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.services.prediction_service import PredictionService


pytestmark = [pytest.mark.integration, pytest.mark.slow]

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
MODEL_PATH = ROOT / "models" / "lstm" / "model.keras"
SCALER_PATH = ROOT / "models" / "lstm" / "scalers.pkl"


def test_lstm_prediction_load_or_retrain_contract():
    if os.environ.get("SGOP_RUN_SLOW_LSTM") != "1":
        pytest.skip("Set SGOP_RUN_SLOW_LSTM=1 to run the real LSTM load/retrain smoke test.")
    if not RAW_DIR.exists():
        pytest.skip("Repository raw data is not available.")
    if not MODEL_PATH.exists() or not SCALER_PATH.exists():
        pytest.skip("Saved LSTM model artifacts are not available.")

    result = PredictionService().run_lstm_prediction(
        raw_dir=str(RAW_DIR),
        load_scale=1.0,
        retrain=False,
        epochs=1,
    )

    assert result.source in {"lstm", "baseline"}
    assert result.fallback.mode in {"none", "baseline_model"}
    assert result.predictions
    assert len(result.predictions) == 24 * 24
    assert result.metadata["legacy_bus_source"] is False
    assert all(pred.predicted_load_mw >= 0.0 for pred in result.predictions)
