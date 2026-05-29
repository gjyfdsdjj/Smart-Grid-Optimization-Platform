from __future__ import annotations

from datetime import datetime

from src.data.adapters.vworld_adapter import get_map_capability
from src.data.grid_builder import build_default_grid_dataset
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


def test_landing_overlay_wraps_points_and_routes_with_common_metadata():
    scenario = _scenario()
    point = MapOverlayPoint(
        overlay_id="plant:test",
        label="테스트 발전소",
        kind="power_plant",
        latitude=36.45,
        longitude=127.85,
        elevation_m=None,
        coordinate_system="EPSG:4326",
        elevation_source="not_queried",
        source="manual",
    )

    overlay = MapOverlayService().build_landing_overlay(
        scenario=scenario,
        created_at=scenario.created_at,
        points=[point],
        routes=[],
        warnings=["landing local warning"],
        map_capability=_map_2_5d_capability(),
    )

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay.source == "manual"
    assert overlay.points == [point]
    assert overlay.routes == []
    assert overlay.metadata["coordinate_system"] == "EPSG:4326"
    assert overlay.metadata["elevation_source"] == "not_queried"
    assert overlay.metadata["point_count"] == 1
    assert overlay.metadata["line_count"] == 0
    assert overlay.metadata["route_count"] == 0
    assert "landing local warning" in overlay.warnings


def test_grid_overlay_exposes_grid_nodes_lines_and_power_profile_metadata():
    scenario = _scenario()
    dataset = build_default_grid_dataset(created_at=scenario.created_at)

    overlay = MapOverlayService().build_grid_overlay(
        dataset,
        scenario=scenario,
        created_at=scenario.created_at,
        map_capability=_map_2_5d_capability(),
    )
    point_ids = {point.overlay_id for point in overlay.points}

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay.source == "manual"
    assert len(overlay.points) == len(dataset.nodes)
    assert len(overlay.lines) == len(dataset.lines)
    assert overlay.metadata["grid_stage"] == "7-8"
    assert overlay.metadata["line_generation_status"] == "generated"
    assert overlay.metadata["slack_node_ids"] == ["PLANT_ULSAN"]
    assert not any(point.metadata["node_id"].startswith(("BUS_", "B0", "SITE_")) for point in overlay.points)
    assert not any(line.metadata["line_id"].startswith(("BUS_", "B0", "SITE_")) for line in overlay.lines)
    assert all(line.from_point.overlay_id in point_ids for line in overlay.lines)
    assert all(line.to_point.overlay_id in point_ids for line in overlay.lines)

    slack_point = next(point for point in overlay.points if point.metadata["node_id"] == "PLANT_ULSAN")
    assert slack_point.kind == "power_plant"
    assert slack_point.metadata["is_slack_candidate"] is True
    assert slack_point.metadata["generation_mw"] > 0.0
    assert any(line.metadata["is_bidirectional"] is True for line in overlay.lines)


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
    assert len(candidate_points) == len(simulation.recommendations)
    assert len(overlay.lines) == len(monitoring.line_statuses)
    assert len(overlay.routes) == len(simulation.recommendations)
    assert {line.metadata["line_id"] for line in overlay.lines} == {
        line.line_id for line in monitoring.line_statuses
    }
    assert [route.rank for route in overlay.routes] == list(range(1, len(overlay.routes) + 1))
    assert overlay.routes[0].candidate_id == simulation.recommendations[0].candidate_id
    assert overlay.routes[0].metadata["score_total"] == simulation.recommendations[0].score.total_score
    assert all(route.points for route in overlay.routes)
    assert all(str(point.metadata["candidate_id"]).startswith("TOWER_") for point in candidate_points)
    assert not any(str(point.metadata["candidate_id"]).startswith("SITE_") for point in candidate_points)


def test_simulation_overlay_exposes_landing_installation_candidate_metadata():
    scenario = _scenario()
    service = SimulationService()
    installation = InstallationPoint(
        installation_id="tower-manual-001",
        label="수동 송전탑 후보",
        kind="transmission_tower",
        latitude=36.42,
        longitude=127.72,
        voltage_kv=345.0,
        created_at=scenario.created_at,
    )
    simulation = service.run_simulation(
        service.build_default_input(
            scenario=scenario,
            created_at=scenario.created_at,
            candidate_site_ids=[],
            user_candidate_points=[installation],
            load_scale=1.0,
        ),
        created_at=scenario.created_at,
    )

    overlay = MapOverlayService().build_simulation_overlay(
        simulation,
        map_capability=_map_2_5d_capability(),
    )

    candidate_point = next(point for point in overlay.points if point.kind == "tower_candidate")
    route = overlay.routes[0]

    assert candidate_point.source == "manual"
    assert candidate_point.metadata["candidate_id"] == "USER_TOWER_TOWER_MANUAL_001"
    assert candidate_point.metadata["installation_id"] == "USER_TOWER_TOWER_MANUAL_001"
    assert candidate_point.metadata["candidate_source"] == "landing_installation"
    assert candidate_point.latitude == installation.latitude
    assert candidate_point.longitude == installation.longitude
    assert route.candidate_id == "USER_TOWER_TOWER_MANUAL_001"
    assert route.metadata["candidate_source"] == "landing_installation"
    assert route.metadata["installation_id"] == "USER_TOWER_TOWER_MANUAL_001"


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
    assert all(point.metadata["coordinate_precision"] == "grid_node" for point in overlay.points)
    assert not any(point.metadata["node_id"].startswith("BUS_") for point in overlay.points)


def test_prediction_overlay_includes_selected_chart_nodes():
    scenario = _scenario()
    selected_node_ids = ["TOWER_CHEONGJU", "TOWER_GUMI"]
    prediction = PredictionService().run_mock_prediction(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    overlay = MapOverlayService().build_prediction_overlay(
        prediction,
        selected_node_ids=selected_node_ids,
        map_capability=_map_2_5d_capability(),
    )

    selected_points = [
        point
        for point in overlay.points
        if point.metadata.get("selected_for") == "prediction_chart"
    ]
    selected_point_ids = {
        point.metadata["node_id"]
        for point in selected_points
    }

    assert selected_point_ids == set(selected_node_ids)
    assert all(point.status == "selected" for point in selected_points)
    assert all(point.metadata["coordinate_precision"] == "grid_node" for point in selected_points)
    assert "선택 노드 2개" in overlay.summary


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
    metadata_values = [str(value) for value in overlay.metadata.values()]

    assert overlay.fallback.mode == "map_2_5d"
    assert overlay.metadata["vworld_available"] is True
    assert all(secret_key not in message for message in messages)
    assert "wmts_tile_url" not in overlay.metadata
    assert all(secret_key not in value for value in metadata_values)
    assert capability.wmts_tile_url is not None
    assert all(capability.wmts_tile_url not in value for value in metadata_values)
