from __future__ import annotations

import json

import pandas as pd

from src.engine.forecast.baseline_forecaster import BaselineForecaster
from src.engine.forecast.feature_builder import build_prediction_feature_matrix
from src.engine.forecast.gnn_forecaster import GNNForecaster
import src.engine.forecast.lstm_forecaster as lstm_module
from src.engine.forecast.lstm_forecaster import LSTMForecaster
from src.engine.forecast.neural_gnn_forecaster import NeuralGNNForecaster
from src.data.loaders import load_grid_dataset_or_default
from src.data.schemas import InstallationPoint
from src.services.prediction_service import PredictionService


def test_mock_prediction_result_contract(scenario):
    result = PredictionService().run_mock_prediction(
        load_scale=1.0,
        created_at=scenario.created_at,
        scenario=scenario,
    )

    assert result.source == "mock"
    assert result.fallback.enabled is True
    assert result.fallback.mode == "mock_data"
    assert result.scenario.scenario_id == scenario.scenario_id
    assert result.forecast_horizon_h == 24
    assert len(result.predictions) == 24 * 24
    assert result.metadata["legacy_bus_source"] is False
    assert result.metadata["prediction_node_count"] == 24
    assert all(pred.bus_id.startswith("TOWER_") for pred in result.predictions)
    assert all(risk.line_id.startswith("GLINE_") for risk in result.risk_lines)
    assert result.summary
    assert all(pred.predicted_load_mw >= 0.0 for pred in result.predictions)


def test_baseline_forecaster_contract_with_synthetic_features(load_df_2bus):
    forecast_start = load_df_2bus["timestamp"].max()
    target_features = build_prediction_feature_matrix(
        load_df=load_df_2bus,
        forecast_start=forecast_start,
        bus_ids=["NODE_A", "NODE_B"],
        horizon_h=3,
    )

    predictions = (
        BaselineForecaster()
        .fit(load_df_2bus)
        .predict(target_features=target_features)
    )

    assert len(predictions) == 6
    assert [
        (pred.timestamp, pred.bus_id)
        for pred in predictions
    ] == [
        (feature.timestamp, feature.bus_id)
        for feature in target_features
    ]
    assert all(pred.predicted_load_mw >= 0.0 for pred in predictions)
    assert all(
        pred.confidence_lower_mw <= pred.predicted_load_mw <= pred.confidence_upper_mw
        for pred in predictions
    )


def test_gnn_forecaster_contract_with_synthetic_features(load_df_2bus):
    forecast_start = load_df_2bus["timestamp"].max()
    target_features = build_prediction_feature_matrix(
        load_df=load_df_2bus,
        forecast_start=forecast_start,
        bus_ids=["NODE_A", "NODE_B"],
        horizon_h=4,
    )

    predictions = (
        GNNForecaster()
        .fit(load_df_2bus)
        .predict(
            history_df=load_df_2bus,
            forecast_start=forecast_start,
            target_features=target_features,
        )
    )

    assert len(predictions) == 8
    assert [
        (pred.timestamp, pred.bus_id)
        for pred in predictions
    ] == [
        (feature.timestamp, feature.bus_id)
        for feature in target_features
    ]
    assert all(pred.predicted_load_mw >= 0.0 for pred in predictions)
    assert all(
        pred.confidence_lower_mw <= pred.predicted_load_mw <= pred.confidence_upper_mw
        for pred in predictions
    )


def test_gnn_prediction_service_contract_uses_synthetic_weather(
    monkeypatch,
    scenario,
):
    service = PredictionService()

    result = service.run_gnn_prediction(
        raw_dir="data/raw",
        load_scale=1.0,
        scenario=scenario,
    )

    assert result.source == "gnn"
    assert result.fallback.enabled is False
    assert result.fallback.mode == "none"
    assert result.scenario_id == scenario.scenario_id
    assert len(result.predictions) == 24 * 24
    assert result.metadata["graph_edge_source"] == "GridLine"
    assert result.metadata["legacy_bus_source"] is False
    assert result.metadata["processed_node_history_used"] is True
    assert result.metadata["history_source"] == "data/processed/grid_node_load_history.csv"
    assert result.metadata["node_history_node_count"] == 24
    assert result.metadata["processed_line_history_used"] is True
    assert result.metadata["line_flow_history_line_count"] == 44
    assert result.summary


def test_baseline_prediction_service_falls_back_when_processed_history_unavailable(
    monkeypatch,
    scenario,
):
    def _raise_processed_history_error():
        raise FileNotFoundError("unit missing processed history")

    monkeypatch.setattr(
        "src.services.prediction_service.load_processed_grid_node_history",
        _raise_processed_history_error,
    )

    result = PredictionService().run_baseline_prediction(
        raw_dir="data/raw",
        load_scale=1.0,
        scenario=scenario,
    )

    assert result.source == "baseline"
    assert result.metadata["processed_node_history_used"] is False
    assert result.metadata["history_source"] == "KPX CSV redistributed to GridNode"
    assert "unit missing processed history" in result.metadata["processed_node_history_error"]
    assert result.metadata["legacy_bus_source"] is False


def test_prediction_service_uses_processed_history_with_user_tower(scenario):
    user_tower = InstallationPoint(
        installation_id="prediction-test-tower",
        label="예측 테스트 송전탑",
        kind="transmission_tower",
        latitude=36.5,
        longitude=127.4,
    )
    dataset = load_grid_dataset_or_default(
        user_installations=[user_tower],
        created_at=scenario.created_at,
    )

    result = PredictionService().run_baseline_prediction(
        raw_dir="data/raw",
        load_scale=1.0,
        scenario=scenario,
        grid_dataset=dataset,
    )

    assert result.metadata["processed_node_history_used"] is True
    assert result.metadata["history_source"] == "data/processed/grid_node_load_history.csv"
    assert result.metadata["node_history_node_count"] == 24
    assert result.metadata["prediction_node_count"] == 24
    assert all(not pred.bus_id.startswith("USER_TOWER_") for pred in result.predictions)


def test_lstm_training_metadata_reads_history_and_evaluation(monkeypatch, tmp_path):
    history_path = tmp_path / "training_history.csv"
    evaluation_path = tmp_path / "evaluation_summary.json"
    model_path = tmp_path / "model.keras"
    scaler_path = tmp_path / "scalers.pkl"

    pd.DataFrame(
        [
            {"epoch": 1, "loss": 0.20, "mae": 0.30, "val_loss": 0.25, "val_mae": 0.35},
            {"epoch": 2, "loss": 0.10, "mae": 0.20, "val_loss": 0.15, "val_mae": 0.25},
        ]
    ).to_csv(history_path, index=False)
    evaluation_path.write_text(
        json.dumps(
            {
                "model": "lstm",
                "mae_mw": 12.5,
                "rmse_mw": 18.75,
                "mape_pct": 3.2,
                "sample_count": 1152,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(lstm_module, "_HISTORY_PATH", history_path)
    monkeypatch.setattr(lstm_module, "_EVALUATION_PATH", evaluation_path)
    monkeypatch.setattr(lstm_module, "_MODEL_PATH", model_path)
    monkeypatch.setattr(lstm_module, "_SCALER_PATH", scaler_path)

    metadata = LSTMForecaster().training_metadata()

    assert metadata["model_type"] == "lstm"
    assert metadata["deep_learning"] is True
    assert metadata["epochs_trained"] == 2
    assert metadata["train_loss_final"] == 0.10
    assert metadata["val_loss_best"] == 0.15
    assert metadata["test_mae"] == 12.5
    assert metadata["test_rmse"] == 18.75
    assert metadata["test_mape"] == 3.2
    assert metadata["evaluation_summary"]["sample_count"] == 1152


def test_neural_gnn_training_metadata_reads_holdout_evaluation(tmp_path):
    model_dir = tmp_path / "gnn"
    model_dir.mkdir()
    metadata_path = model_dir / "metadata.json"
    evaluation_path = model_dir / "evaluation_summary.json"
    node_error_path = model_dir / "node_error_summary.csv"

    metadata_path.write_text(
        json.dumps(
            {
                "model_type": "neural_gnn",
                "framework": "torch",
                "deep_learning": True,
                "bus_ids": ["NODE_A", "NODE_B"],
                "node_count": 2,
                "graph_edge_count": 1,
                "epochs_trained": 2,
                "test_mae": 99.0,
            }
        ),
        encoding="utf-8",
    )
    evaluation_path.write_text(
        json.dumps(
            {
                "model": "neural_gnn",
                "mae_mw": 7.5,
                "rmse_mw": 11.25,
                "mape_pct": 2.4,
                "sample_count": 1152,
                "forecast_start_count": 24,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "node_id": "NODE_A",
                "mae_mw": 6.0,
                "rmse_mw": 9.0,
                "mape_pct": 2.0,
            }
        ]
    ).to_csv(node_error_path, index=False)

    metadata = NeuralGNNForecaster(model_dir=model_dir).training_metadata()

    assert metadata["model_type"] == "neural_gnn"
    assert metadata["deep_learning"] is True
    assert metadata["test_mae"] == 7.5
    assert metadata["test_rmse"] == 11.25
    assert metadata["test_mape"] == 2.4
    assert metadata["evaluation_summary"]["forecast_start_count"] == 24
    assert metadata["evaluation_summary_path"].endswith("evaluation_summary.json")
    assert metadata["node_error_summary_path"].endswith("node_error_summary.csv")
