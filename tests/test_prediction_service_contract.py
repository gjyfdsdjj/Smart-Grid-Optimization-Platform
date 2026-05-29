from __future__ import annotations

from src.engine.forecast.baseline_forecaster import BaselineForecaster
from src.engine.forecast.feature_builder import build_prediction_feature_matrix
from src.engine.forecast.gnn_forecaster import GNNForecaster
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
    assert result.summary
