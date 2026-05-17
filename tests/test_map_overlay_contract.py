from __future__ import annotations

from datetime import datetime

from src.data.adapters.vworld_adapter import get_map_capability
from src.data.schemas import InstallationPoint, MapOverlayPoint, ScenarioContext
from src.services.map_overlay_service import MapOverlayService
from src.services.monitoring_service import MonitoringService
from src.services.prediction_service import PredictionService
from src.services.simulation_service import SimulationService


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="overlay-contract-001",
        title="Overlay Contract",
        region="South Korea",
        created_at=datetime(2026, 5, 11, 10, 0),
        created_by="pytest",
    )


def _map_2_5d_capability():
    return get_map_capability(api_key="", use_settings=False)


def test_installation_point_contract_preserves_xy_and_2_5d_defaults():
    installation = InstallationPoint(
        installation_id="install-001",
        label="신규 발전소",
        kind="power_plant",
        latitude=37.123456,
        longitude=127.654321,
        capacity_mw=500.0,
    )
    overlay_point = MapOverlayPoint(
        overlay_id=f"installation:{installation.installation_id}",
        label=installation.label,
        kind=installation.kind,
        latitude=installation.latitude,
        longitude=installation.longitude,
        elevation_m=installation.elevation_m,
        coordinate_system=installation.coordinate_system,
        elevation_source=installation.elevation_source,
        status="selected",
        source="manual",
    )

    assert installation.mode == "new"
    assert installation.elevation_m is None
    assert installation.elevation_source == "not_queried"
    assert installation.coordinate_system == "EPSG:4326"
    assert overlay_point.kind == "power_plant"
    assert overlay_point.source == "manual"
    assert overlay_point.longitude == 127.654321
    assert overlay_point.latitude == 37.123456


def test_installation_target_kinds_are_supported_by_overlay_point_contract():
    supported_kinds = [
        "power_plant",
        "transmission_tower",
        "start_point",
        "end_point",
        "install_point",
    ]

    for kind in supported_kinds:
        point = MapOverlayPoint(
            overlay_id=f"{kind}:sample",
            label=kind,
            kind=kind,
            latitude=36.45,
            longitude=127.85,
            elevation_m=None,
            coordinate_system="EPSG:4326",
            elevation_source="not_queried",
            source="manual",
        )

        assert point.kind == kind
        assert point.elevation_m is None
        assert point.elevation_source == "not_queried"


def test_monitoring_overlay_preserves_line_ids_and_scenario():
    scenario = _scenario()
    monitoring = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    overlay = MapOverlayService().build_monitoring_overlay(
        monitoring,
        map_capability=_map_2_5d_capability(),
    )

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay.source == "dc_power_flow"
    assert overlay.fallback.mode == "map_2_5d"
    assert overlay.warnings[0] == "MapOverlayService는 현재 `map_2_5d` fallback 결과를 반환합니다."
    assert overlay.lines
    assert overlay.points
    assert len(overlay.lines) == len(monitoring.line_statuses)
    assert {line.metadata["line_id"] for line in overlay.lines} == {
        line.line_id for line in monitoring.line_statuses
    }
    assert all(line.from_point.elevation_m is None for line in overlay.lines)
    assert any("고도" in warning for warning in overlay.warnings)


def test_simulation_overlay_exposes_candidate_points_and_ranked_routes():
    scenario = _scenario()
    service = SimulationService()
    simulation = service.run_simulation(
        service.build_default_input(
            scenario=scenario,
            created_at=scenario.created_at,
            load_scale=1.0,
        ),
        created_at=scenario.created_at,
    )
    monitoring = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    overlay = MapOverlayService().build_simulation_overlay(
        simulation,
        baseline_monitoring=monitoring,
        map_capability=_map_2_5d_capability(),
    )

    candidate_points = [point for point in overlay.points if point.kind == "tower_candidate"]

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay.source == "astar"
    assert len(candidate_points) == 3
    assert len(overlay.lines) == len(monitoring.line_statuses)
    assert len(overlay.routes) == 3
    assert {line.metadata["line_id"] for line in overlay.lines} == {
        line.line_id for line in monitoring.line_statuses
    }
    assert [route.rank for route in overlay.routes] == [1, 2, 3]
    assert overlay.routes[0].candidate_id == simulation.recommendations[0].candidate_id
    assert overlay.routes[0].metadata["score_total"] == simulation.recommendations[0].score.total_score
    assert all(route.points for route in overlay.routes)
    assert any(point.metadata["candidate_id"] == "SITE_SOUTH" for point in candidate_points)


def test_prediction_overlay_uses_risk_line_ids_for_table_map_sync():
    scenario = _scenario()
    prediction = PredictionService().run_mock_prediction(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.5,
    )

    overlay = MapOverlayService().build_prediction_overlay(
        prediction,
        map_capability=_map_2_5d_capability(),
    )

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay.source == "mock"
    assert overlay.lines
    assert {line.metadata["line_id"] for line in overlay.lines} == {
        risk.line_id for risk in prediction.risk_lines
    }
    assert all(line.kind == "risk_line" for line in overlay.lines)
    assert all("predicted_utilization" in line.metadata for line in overlay.lines)
    assert all("peak_risk_hour" in line.metadata for line in overlay.lines)


def test_overlay_fallback_messages_do_not_expose_vworld_key():
    secret_key = "secret-vworld-key"
    scenario = _scenario()
    monitoring = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )
    capability = get_map_capability(
        api_key=secret_key,
        prefer_webgl=False,
        use_settings=False,
    )

    overlay = MapOverlayService().build_monitoring_overlay(
        monitoring,
        map_capability=capability,
    )
    messages = [overlay.fallback.reason, *overlay.warnings]

    assert overlay.fallback.mode == "map_2_5d"
    assert overlay.metadata["vworld_available"] is True
    assert all(secret_key not in message for message in messages)
