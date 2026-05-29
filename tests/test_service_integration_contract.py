from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.data.schemas import (
    MonitoringResult,
    PredictionResult,
    ScenarioContext,
    SimulationResult,
)
from src.engine.forecast.feature_builder import build_prediction_feature_matrix
from src.services.monitoring_service import MonitoringService
from src.services.prediction_service import PredictionService
from src.services.result_metadata import build_fallback_warning, build_source_warning
from src.services.simulation_service import SimulationService


ALLOWED_SOURCES = {
    "mock",
    "baseline",
    "lstm",
    "gnn",
    "neural_gnn",
    "hybrid",
    "hybrid_neural_gnn",
    "dc_power_flow",
    "heuristic",
    "astar",
    "manual",
}

ALLOWED_FALLBACK_MODES = {
    "none",
    "mock_data",
    "baseline_model",
    "graph_model",
    "cached_result",
    "manual_override",
    "map_2_5d",
}


def _shared_scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="service-integration-001",
        title="Service Integration Contract",
        description="Monitoring, Simulation, Prediction 공통 계약 검증",
        region="South Korea",
        created_at=datetime(2026, 5, 11, 9, 0),
        created_by="pytest",
    )


def _assert_common_metadata(
    result: MonitoringResult | SimulationResult | PredictionResult,
    *,
    scenario: ScenarioContext,
) -> None:
    assert result.scenario is not None
    assert result.scenario.scenario_id == scenario.scenario_id
    assert result.source in ALLOWED_SOURCES
    assert result.fallback.mode in ALLOWED_FALLBACK_MODES

    if result.fallback.mode == "none":
        assert result.fallback.enabled is False
    else:
        assert result.fallback.enabled is True
        assert result.fallback.reason
        assert result.fallback.primary_path
        assert result.fallback.active_path
        assert any("fallback" in warning for warning in result.warnings)


def test_actual_service_flow_preserves_shared_scenario_and_metadata():
    scenario = _shared_scenario()
    load_scale = 1.0
    created_at = scenario.created_at

    monitoring = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        load_scale=load_scale,
        created_at=created_at,
    )
    simulation_service = SimulationService()
    simulation = simulation_service.run_simulation(
        simulation_service.build_default_input(
            scenario=scenario,
            created_at=created_at,
            load_scale=load_scale,
        ),
        created_at=created_at,
    )
    prediction = PredictionService().run_baseline_prediction(
        raw_dir=str(Path("data/raw").resolve()),
        load_scale=load_scale,
        forecast_start=created_at,
        scenario=scenario,
    )

    for result in (monitoring, simulation, prediction):
        _assert_common_metadata(result, scenario=scenario)

    assert monitoring.load_scale == load_scale
    assert simulation.simulation_input.load_scale == load_scale
    assert prediction.load_scale == load_scale

    assert monitoring.source == "dc_power_flow"
    assert monitoring.fallback.mode == "none"
    assert monitoring.line_statuses
    assert monitoring.congestion_summary.total_lines == len(monitoring.line_statuses)
    assert monitoring.warnings[0] == build_source_warning("MonitoringService", "dc_power_flow")

    assert simulation.source == "astar"
    assert simulation.fallback.mode == "none"
    assert simulation.selected_route is not None
    assert simulation.selected_route.source == "astar"
    assert [recommendation.rank for recommendation in simulation.recommendations] == list(
        range(1, len(simulation.recommendations) + 1)
    )
    assert all(recommendation.candidate_id.startswith("TOWER_") for recommendation in simulation.recommendations)
    assert [recommendation.candidate_id for recommendation in simulation.recommendations]
    assert simulation.deltas
    assert any(
        warning == build_source_warning("SimulationService", "astar")
        for warning in simulation.warnings
    )

    assert prediction.source == "baseline"
    assert prediction.fallback.mode == "none"
    assert prediction.predictions
    assert prediction.risk_lines
    assert prediction.warnings[0] == build_source_warning("PredictionService", "baseline")
    assert prediction.metadata["legacy_bus_source"] is False
    assert prediction.metadata["prediction_node_count"] == 24
    assert all(pred.bus_id.startswith("TOWER_") for pred in prediction.predictions)
    assert all(risk.line_id.startswith("GLINE_") for risk in prediction.risk_lines)


def test_prediction_mock_path_preserves_shared_scenario_contract():
    scenario = _shared_scenario()
    result = PredictionService().run_mock_prediction(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    _assert_common_metadata(result, scenario=scenario)
    assert result.source == "mock"
    assert result.fallback.mode == "mock_data"
    assert result.warnings[0] == build_fallback_warning("PredictionService", "mock_data")
    assert len(result.predictions) == 24 * 24
    assert result.metadata["legacy_bus_source"] is False


def test_monitoring_actual_failure_falls_back_without_losing_scenario(monkeypatch):
    scenario = _shared_scenario()

    def fail_solve(*args, **kwargs):
        raise RuntimeError("forced dc failure")

    monkeypatch.setattr("src.services.monitoring_service._dcpf.solve", fail_solve)

    result = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    _assert_common_metadata(result, scenario=scenario)
    assert result.source == "mock"
    assert result.fallback.mode == "mock_data"
    assert result.warnings[0] == build_fallback_warning("MonitoringService", "mock_data")
    assert any("DC Power Flow 실패" in warning for warning in result.warnings)


def test_simulation_actual_failure_falls_back_without_losing_scenario(monkeypatch):
    scenario = _shared_scenario()

    def fail_route(*args, **kwargs):
        raise RuntimeError("forced astar failure")

    monkeypatch.setattr("src.services.simulation_service.build_astar_route", fail_route)

    service = SimulationService()
    result = service.run_simulation(
        service.build_default_input(
            scenario=scenario,
            created_at=scenario.created_at,
            load_scale=1.0,
        ),
        created_at=scenario.created_at,
    )

    _assert_common_metadata(result, scenario=scenario)
    assert result.source == "mock"
    assert result.fallback.mode == "mock_data"
    assert result.warnings[0] == build_fallback_warning("SimulationService", "mock_data")
    assert any("A* route/score 실패" in warning for warning in result.warnings)
    assert result.recommendations


def test_prediction_hybrid_failure_uses_baseline_fallback_contract(
    monkeypatch,
    load_df_13bus,
    prediction_factory,
):
    scenario = _shared_scenario()
    forecast_start = load_df_13bus["timestamp"].max()
    service = PredictionService()

    def fail_lstm(**kwargs):
        raise RuntimeError("forced lstm failure")

    def fake_gnn(**kwargs):
        return [
            prediction_factory(
                timestamp=feature.timestamp,
                bus_id=feature.bus_id,
                value=120.0,
            )
            for feature in kwargs["target_features"]
        ]

    def fake_baseline(**kwargs):
        target_features = build_prediction_feature_matrix(
            load_df=load_df_13bus,
            forecast_start=kwargs["forecast_start"],
        )
        predictions = [
            prediction_factory(
                timestamp=feature.timestamp,
                bus_id=feature.bus_id,
                value=100.0,
            )
            for feature in target_features
        ]
        return service._build_prediction_result(
            scenario=kwargs["scenario"],
            created_at=kwargs["forecast_start"],
            load_scale=kwargs["load_scale"],
            predictions=predictions,
            source="baseline",
            warnings=[],
        )

    monkeypatch.setattr(service, "_load_grid_history", lambda raw_dir, dataset: load_df_13bus)
    monkeypatch.setattr(service, "_predict_lstm", fail_lstm)
    monkeypatch.setattr(service, "_predict_gnn", fake_gnn)
    monkeypatch.setattr(service, "run_baseline_prediction", fake_baseline)

    result = service.run_hybrid_prediction(
        raw_dir="unused",
        load_scale=1.0,
        forecast_start=forecast_start,
        scenario=scenario,
        retrain=False,
        epochs=1,
    )

    _assert_common_metadata(result, scenario=scenario)
    assert result.source == "baseline"
    assert result.fallback.mode == "baseline_model"
    assert result.warnings[0] == build_fallback_warning("PredictionService", "baseline_model")
    assert any("LSTM 실패" in warning for warning in result.warnings)
    assert any(
        warning == build_source_warning("PredictionService", "baseline")
        for warning in result.warnings
    )
