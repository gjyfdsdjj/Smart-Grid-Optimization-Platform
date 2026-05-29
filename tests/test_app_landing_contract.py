from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

import app
from src.data.schemas import (
    CongestionSummary,
    GridDataset,
    GridImprovementProposal,
    GridLine,
    GridNode,
    InstallationPoint,
    LineStressSnapshot,
    LineStatus,
    MapOverlayLine,
    MapOverlayPoint,
    MapOverlayResult,
    MapOverlayRoute,
    MonitoringResult,
    NodeStressSnapshot,
    PredictionResult,
    RerouteCandidate,
    RiskLine,
    RoutePoint,
    RouteResult,
    ScenarioContext,
    StressAnalysisResult,
    SuggestedGridNode,
    TransmissionScenario,
)


class _FakeSessionState(dict):
    def __getattr__(self, key: str):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: object) -> None:
        self[key] = value


def _distance_km(point_a: MapOverlayPoint, point_b: MapOverlayPoint) -> float:
    radius_km = 6371.0
    lat_a = radians(point_a.latitude)
    lat_b = radians(point_b.latitude)
    delta_lat = radians(point_b.latitude - point_a.latitude)
    delta_lon = radians(point_b.longitude - point_a.longitude)
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * atan2(sqrt(haversine), sqrt(1 - haversine))


def _grid_node(
    node_id: str,
    name: str,
    *,
    latitude: float,
    longitude: float,
) -> GridNode:
    return GridNode(
        node_id=node_id,
        node_name=name,
        node_type="transmission_tower",
        latitude=latitude,
        longitude=longitude,
        voltage_kv=345.0,
    )


def _grid_line(
    line_id: str,
    from_node_id: str,
    to_node_id: str,
    *,
    distance_km: float = 20.0,
) -> GridLine:
    return GridLine(
        line_id=line_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        voltage_kv=345.0,
        capacity_mw=500.0,
        reactance_pu=0.04,
        distance_km=distance_km,
    )


def _app_grid_dataset() -> GridDataset:
    return GridDataset(
        nodes=[
            _grid_node("PLANT_A", "A 발전소", latitude=36.0, longitude=127.0),
            _grid_node("TOWER_B", "B 송전탑", latitude=36.2, longitude=127.2),
            _grid_node("TOWER_C", "C 송전탑", latitude=36.4, longitude=127.4),
        ],
        lines=[
            _grid_line("LINE_AB", "PLANT_A", "TOWER_B", distance_km=20.0),
            _grid_line("LINE_BC", "TOWER_B", "TOWER_C", distance_km=30.0),
        ],
    )


def test_landing_click_extracts_xy_only_install_point():
    point = app._extract_clicked_point(
        {
            "last_clicked": {
                "lat": "37.5665",
                "lng": "126.9780",
            }
        }
    )

    assert point is not None
    assert point.kind == "install_point"
    assert point.source == "manual"
    assert point.longitude == 126.9780
    assert point.latitude == 37.5665
    assert point.elevation_m is None
    assert point.elevation_source == "not_queried"
    assert point.coordinate_system == "EPSG:4326"
    assert point.metadata["capture_source"] == "folium_click"
    assert point.label == "서울 선택 지점"
    assert point.metadata["nearest_place_name"] == "서울"
    assert point.metadata["nearest_place_province"] == "서울특별시"
    assert point.metadata["nearest_place_distance_km"] < 0.1


def test_landing_click_prefers_object_click_coordinates():
    point = app._extract_clicked_point(
        {
            "last_clicked": {
                "lat": 35.0,
                "lng": 126.0,
            },
            "last_object_clicked": {
                "lat": 36.1195,
                "lng": 128.3446,
            },
            "last_object_clicked_tooltip": "구미 송전탑",
        }
    )

    assert point is not None
    assert point.latitude == 36.1195
    assert point.longitude == 128.3446
    assert point.label == "구미 선택 지점"
    assert point.metadata["capture_source"] == "folium_object_click"
    assert point.metadata["object_tooltip"] == "구미 송전탑"


def test_landing_click_uses_nearest_place_for_installation_name():
    point = app._extract_clicked_point(
        {
            "last_clicked": {
                "lat": 36.1195,
                "lng": 128.3446,
            }
        }
    )

    assert point is not None
    assert app._suggest_installation_name("power_plant", point) == "구미 발전소"
    assert app._suggest_installation_name("transmission_tower", point) == "구미 송전탑"


def test_landing_click_store_defers_widget_name_update(monkeypatch):
    fake_state = _FakeSessionState(
        sgop_landing_installations=[],
        sgop_landing_last_click=None,
    )
    monkeypatch.setattr(app.st, "session_state", fake_state)
    clicked_point = MapOverlayPoint(
        overlay_id="map-click:last",
        label="구미 선택 지점",
        kind="install_point",
        latitude=36.1195,
        longitude=128.3446,
        metadata={"nearest_place_name": "구미", "nearest_place_id": "gumi"},
    )

    assert app._store_last_clicked_point(clicked_point, "transmission_tower") is True

    assert fake_state.sgop_landing_last_click == clicked_point
    assert app._LANDING_NAME_STATE_KEY not in fake_state
    assert fake_state[app._LANDING_PENDING_NAME_STATE_KEY] == "구미 송전탑"

    app._sync_installation_name("transmission_tower", clicked_point)

    assert fake_state[app._LANDING_NAME_STATE_KEY] == "구미 송전탑"
    assert app._LANDING_PENDING_NAME_STATE_KEY not in fake_state


def test_landing_mock_points_include_product_map_assets():
    points = app._build_mock_grid_points()
    kinds = {point.kind for point in points}
    plant_labels = {point.label for point in points if point.kind == "power_plant"}
    tower_labels = {point.label for point in points if point.kind == "transmission_tower"}

    assert kinds == {"power_plant", "transmission_tower"}
    assert plant_labels == {
        "인천 발전소",
        "광주 발전소",
        "속초 발전소",
        "부산 발전소",
        "울산 발전소",
        "포항 발전소",
    }
    assert tower_labels == {
        "거창 송전탑",
        "서울 송전탑",
        "강릉 송전탑",
        "대전 송전탑",
        "춘천 송전탑",
        "제주도 송전탑",
        "구미 송전탑",
        "대구 송전탑",
        "창원 송전탑",
        "영천 송전탑",
        "상주 송전탑",
        "해남 송전탑",
    }
    assert all(point.coordinate_system == "EPSG:4326" for point in points)
    assert all(point.elevation_m is None for point in points)
    assert all(point.elevation_source == "not_queried" for point in points)
    assert all(point.source == "manual" for point in points)
    assert all(point.metadata.get("default_asset") is True for point in points)
    assert any(point.metadata.get("capacity_mw") for point in points if point.kind == "power_plant")
    assert any(point.metadata.get("voltage_kv") for point in points if point.kind == "transmission_tower")


def test_landing_default_towers_do_not_overlap_default_power_plants():
    points = app._build_mock_grid_points()
    plants = [point for point in points if point.kind == "power_plant"]
    towers = [point for point in points if point.kind == "transmission_tower"]

    assert all(
        _distance_km(plant, tower) >= 25.0
        for plant in plants
        for tower in towers
    )
    assert all(
        _distance_km(tower, other_tower) >= 30.0
        for index, tower in enumerate(towers)
        for other_tower in towers[index + 1:]
    )


def test_landing_installation_overlay_preserves_installation_contract():
    installation = InstallationPoint(
        installation_id="power_plant-20260517120000-1",
        label="신규 발전소 1",
        kind="power_plant",
        latitude=36.45,
        longitude=127.85,
        mode="new",
        capacity_mw=500.0,
        notes="현장 검토",
        created_at=datetime(2026, 5, 17, 12, 0),
    )

    point = app._installation_to_overlay_point(installation)

    assert point.overlay_id == "installation:power_plant-20260517120000-1"
    assert point.kind == "power_plant"
    assert point.status == "selected"
    assert point.source == "manual"
    assert point.longitude == installation.longitude
    assert point.latitude == installation.latitude
    assert point.elevation_m is None
    assert point.elevation_source == "not_queried"
    assert point.coordinate_system == "EPSG:4326"
    assert point.metadata["installation_id"] == installation.installation_id
    assert point.metadata["capacity_mw"] == 500.0
    assert point.metadata["notes"] == "현장 검토"


def test_landing_dedupe_keeps_last_overlay_value():
    first = MapOverlayPoint(
        overlay_id="duplicate",
        label="기존 지점",
        kind="bus",
        latitude=36.0,
        longitude=127.0,
    )
    second = MapOverlayPoint(
        overlay_id="duplicate",
        label="갱신 지점",
        kind="bus",
        latitude=37.0,
        longitude=128.0,
    )

    points = app._dedupe_points([first, second])

    assert len(points) == 1
    assert points[0].label == "갱신 지점"
    assert points[0].latitude == 37.0
    assert points[0].longitude == 128.0


def test_landing_points_use_grid_overlay_and_filter_legacy_service_points(monkeypatch):
    fake_state = _FakeSessionState(
        sgop_landing_installations=[
            InstallationPoint(
                installation_id="power_plant-20260529150000-1",
                label="구미 발전소",
                kind="power_plant",
                latitude=36.1195,
                longitude=128.3446,
                capacity_mw=500.0,
            )
        ],
    )
    monkeypatch.setattr(app.st, "session_state", fake_state)
    scenario = ScenarioContext(
        scenario_id="landing-grid-test",
        created_at=datetime(2026, 5, 29, 15, 0),
    )
    grid_user_point = MapOverlayPoint(
        overlay_id="grid-node:USER_PLANT_POWER_PLANT_20260529150000_1",
        label="구미 발전소",
        kind="power_plant",
        latitude=36.1195,
        longitude=128.3446,
        metadata={"node_id": "USER_PLANT_POWER_PLANT_20260529150000_1"},
    )
    service_candidate = MapOverlayPoint(
        overlay_id="tower_candidate:TOWER_ROUTE_EXTRA",
        label="추가 송전탑 경로",
        kind="tower_candidate",
        latitude=35.98,
        longitude=128.05,
    )
    non_candidate_service_point = MapOverlayPoint(
        overlay_id="substation:OLD_NODE",
        label="이전 서비스 지점",
        kind="substation",
        latitude=37.5665,
        longitude=126.9780,
    )
    grid_overlay = MapOverlayResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="manual",
        points=[grid_user_point],
    )
    service_overlay = MapOverlayResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="astar",
        points=[service_candidate, non_candidate_service_point],
    )

    points = app._build_landing_points(grid_overlay, service_overlay)
    overlay_ids = {point.overlay_id for point in points}

    assert overlay_ids == {
        "grid-node:USER_PLANT_POWER_PLANT_20260529150000_1",
        "tower_candidate:TOWER_ROUTE_EXTRA",
    }
    assert "installation:power_plant-20260529150000-1" not in overlay_ids
    assert "substation:OLD_NODE" not in overlay_ids


def test_landing_routes_hide_recommendations_until_explicit_simulation():
    scenario = ScenarioContext(
        scenario_id="landing-route-test",
        created_at=datetime(2026, 5, 29, 15, 0),
    )
    default_recommendation = MapOverlayRoute(
        overlay_id="simulation-route:default",
        label="1순위 기본 추천 경로",
        route_id="default",
        candidate_id="TOWER_GUMI",
        rank=1,
    )
    active_simulation = MapOverlayRoute(
        overlay_id="simulation-route:active",
        label="활성 최적 경로",
        route_id="active",
        candidate_id="TOWER_NAJU",
        rank=1,
        metadata={"landing_visible": True, "display_status": "active_simulation"},
    )
    service_overlay = MapOverlayResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="astar",
        routes=[default_recommendation, active_simulation],
    )

    routes = app._build_landing_routes(service_overlay)

    assert routes == [active_simulation]


def test_landing_global_load_scale_state_defaults_and_clamps(monkeypatch):
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)

    app._init_landing_state()

    assert fake_state[app.LANDING_INTERACTION_MODE_STATE_KEY] == "install"
    assert fake_state[app.GLOBAL_LOAD_SCALE_STATE_KEY] == 1.0
    assert fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY] == []
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "start"
    assert fake_state[app.TRANSMISSION_START_NODE_ID_STATE_KEY] == ""
    assert fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] == ""
    assert fake_state[app.TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY] == ""
    assert fake_state[app.TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY] == app.DEFAULT_TRANSFER_MW
    assert fake_state[app.TRANSMISSION_NEXT_INDEX_STATE_KEY] == 1
    assert fake_state[app.TRANSMISSION_CREATE_REQUESTED_STATE_KEY] is False
    assert fake_state[app.PREDICTION_ENABLED_STATE_KEY] is False
    assert fake_state[app.PREDICTION_MODEL_STATE_KEY] == "Baseline"
    assert fake_state[app.PREDICTION_RESULT_STATE_KEY] is None

    fake_state[app.GLOBAL_LOAD_SCALE_STATE_KEY] = 9.0

    assert app._get_global_load_scale() == 2.0
    assert fake_state[app.GLOBAL_LOAD_SCALE_STATE_KEY] == 9.0

    assert app._normalize_global_load_scale_state() == 2.0
    assert fake_state[app.GLOBAL_LOAD_SCALE_STATE_KEY] == 2.0

    fake_state[app.GLOBAL_LOAD_SCALE_STATE_KEY] = "invalid"

    assert app._get_global_load_scale() == 1.0


def test_landing_transmission_node_lookup_uses_nearest_grid_node() -> None:
    clicked = MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=36.001,
        longitude=127.001,
    )
    selectable = MapOverlayPoint(
        overlay_id="grid-node:TOWER_NEAR",
        label="가까운 송전탑",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "TOWER_NEAR"},
    )
    ignored = MapOverlayPoint(
        overlay_id="route-point:NOT_NODE",
        label="경로점",
        kind="route_point",
        latitude=36.0001,
        longitude=127.0001,
    )
    far_clicked = MapOverlayPoint(
        overlay_id="map-click:last",
        label="먼 지점",
        kind="install_point",
        latitude=37.0,
        longitude=129.0,
    )

    assert app._find_clicked_grid_node(clicked, [ignored, selectable]) == selectable
    assert app._find_clicked_grid_node(far_clicked, [selectable], max_distance_km=2.0) is None


def test_landing_transmission_node_lookup_rejects_line_tooltip() -> None:
    selectable = MapOverlayPoint(
        overlay_id="grid-node:TOWER_NEAR",
        label="가까운 송전탑",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "TOWER_NEAR"},
    )
    line_click = MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=36.0001,
        longitude=127.0001,
        metadata={"object_tooltip": "LINE_AB | A 송전탑 -> B 송전탑 | normal"},
    )
    marker_click = MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=36.0001,
        longitude=127.0001,
        metadata={"object_tooltip": "가까운 송전탑"},
    )

    assert app._find_clicked_grid_node(line_click, [selectable]) is None
    assert app._find_clicked_grid_node(marker_click, [selectable]) == selectable


def test_landing_click_extracts_grid_line_object_from_tooltip() -> None:
    from_point = MapOverlayPoint(
        overlay_id="grid-node:PLANT_A",
        label="A 발전소",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "PLANT_A"},
    )
    to_point = MapOverlayPoint(
        overlay_id="grid-node:TOWER_B",
        label="B 송전탑",
        kind="transmission_tower",
        latitude=36.1,
        longitude=127.1,
        metadata={"node_id": "TOWER_B"},
    )
    line = MapOverlayLine(
        overlay_id="grid-line:LINE_AB",
        label="A 발전소 -> B 송전탑",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
        metadata={"line_id": "LINE_AB"},
    )
    clicked = MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=36.05,
        longitude=127.05,
        metadata={"object_tooltip": "LINE_AB | A 발전소 -> B 송전탑 | warning | 이용률 72.0%"},
    )

    clicked_object = app._extract_clicked_grid_object(
        clicked,
        overlay_points=[from_point, to_point],
        overlay_lines=[line],
    )

    assert app._parse_line_click_tooltip(clicked.metadata["object_tooltip"]) == "LINE_AB"
    assert clicked_object == {
        "type": "line",
        "id": "LINE_AB",
        "label": "A 발전소 -> B 송전탑",
        "source": "map_click",
    }


def test_landing_selected_grid_object_state_and_line_id(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    app._init_landing_state()

    changed = app._store_selected_grid_object(
        {
            "type": "line",
            "id": "LINE_AB",
            "label": "A-B",
        }
    )
    unchanged = app._store_selected_grid_object(
        {
            "type": "line",
            "id": "LINE_AB",
            "label": "A-B",
        }
    )

    assert changed is True
    assert unchanged is False
    assert fake_state[app.SELECTED_GRID_OBJECT_STATE_KEY]["id"] == "LINE_AB"
    assert app._selected_grid_object_line_id() == "LINE_AB"


def test_landing_transmission_click_signature_prevents_repeated_rerun(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    app._init_landing_state()
    clicked = MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=36.0,
        longitude=127.0,
        metadata={
            "capture_source": "folium_object_click",
            "object_tooltip": "A 발전소",
        },
    )

    assert app._should_process_transmission_click(clicked) is True
    assert app._should_process_transmission_click(clicked) is False

    app._reset_transmission_selection()

    assert app._should_process_transmission_click(clicked) is True


def test_landing_transmission_selection_state_machine(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    app._init_landing_state()

    start_node = MapOverlayPoint(
        overlay_id="grid-node:PLANT_A",
        label="A 발전소",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "PLANT_A"},
    )
    end_node = MapOverlayPoint(
        overlay_id="grid-node:TOWER_B",
        label="B 송전탑",
        kind="transmission_tower",
        latitude=36.2,
        longitude=127.2,
        metadata={"node_id": "TOWER_B"},
    )

    assert app._store_transmission_node_selection(start_node) is True
    assert fake_state[app.TRANSMISSION_START_NODE_ID_STATE_KEY] == "PLANT_A"
    assert fake_state[app.TRANSMISSION_START_NODE_LABEL_STATE_KEY] == "A 발전소"
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "end"

    assert app._store_transmission_node_selection(start_node) is True
    assert fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] == ""
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "end"
    assert "달라야" in fake_state[app.TRANSMISSION_SELECTION_WARNING_STATE_KEY]

    assert app._store_transmission_node_selection(end_node) is True
    assert fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] == "TOWER_B"
    assert fake_state[app.TRANSMISSION_END_NODE_LABEL_STATE_KEY] == "B 송전탑"
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "ready"
    assert fake_state[app.TRANSMISSION_SELECTION_WARNING_STATE_KEY] == ""

    app._reset_transmission_selection()

    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "start"
    assert fake_state[app.TRANSMISSION_START_NODE_ID_STATE_KEY] == ""
    assert fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] == ""


def test_landing_points_mark_selected_transmission_nodes(monkeypatch) -> None:
    fake_state = _FakeSessionState(
        **{
            app.TRANSMISSION_START_NODE_ID_STATE_KEY: "PLANT_A",
            app.TRANSMISSION_END_NODE_ID_STATE_KEY: "TOWER_B",
        }
    )
    monkeypatch.setattr(app.st, "session_state", fake_state)
    scenario = ScenarioContext(
        scenario_id="landing-selection-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    plant = MapOverlayPoint(
        overlay_id="grid-node:PLANT_A",
        label="A 발전소",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "PLANT_A"},
    )
    tower = MapOverlayPoint(
        overlay_id="grid-node:TOWER_B",
        label="B 송전탑",
        kind="transmission_tower",
        latitude=36.2,
        longitude=127.2,
        metadata={"node_id": "TOWER_B"},
    )
    grid_overlay = MapOverlayResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="manual",
        points=[plant, tower],
    )

    points = app._build_landing_points(grid_overlay, None)
    point_by_node_id = {
        point.metadata["node_id"]: point
        for point in points
    }

    assert point_by_node_id["PLANT_A"].status == "selected"
    assert point_by_node_id["PLANT_A"].metadata["selection_role"] == "start"
    assert point_by_node_id["TOWER_B"].status == "selected"
    assert point_by_node_id["TOWER_B"].metadata["selection_role"] == "end"


def test_landing_creates_transmission_scenario_from_ready_selection(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    monkeypatch.setattr(
        app,
        "load_grid_dataset_or_default",
        lambda **kwargs: _app_grid_dataset(),
    )
    app._init_landing_state()
    fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] = "ready"
    fake_state[app.TRANSMISSION_START_NODE_ID_STATE_KEY] = "PLANT_A"
    fake_state[app.TRANSMISSION_START_NODE_LABEL_STATE_KEY] = "A 발전소"
    fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] = "TOWER_C"
    fake_state[app.TRANSMISSION_END_NODE_LABEL_STATE_KEY] = "C 송전탑"
    fake_state[app.TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY] = 320.0
    scenario = ScenarioContext(
        scenario_id="landing-create-test",
        created_at=datetime(2026, 5, 29, 17, 0),
    )

    created = app._create_transmission_scenario_from_selection(
        scenario,
        load_scale=1.0,
    )

    assert created is True
    assert fake_state[app.TRANSMISSION_NEXT_INDEX_STATE_KEY] == 2
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "start"
    scenarios = fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY]
    assert len(scenarios) == 1
    transmission = scenarios[0]
    assert isinstance(transmission, TransmissionScenario)
    assert transmission.scenario_route_id == "TX_001_PLANT_A_TOWER_C"
    assert transmission.requested_transfer_mw == 320.0
    assert transmission.path_node_ids == ["PLANT_A", "TOWER_B", "TOWER_C"]
    assert transmission.used_line_ids == ["LINE_AB", "LINE_BC"]
    assert transmission.route is not None
    assert transmission.route.source == "astar"
    assert transmission.metadata["scenario_order"] == 1
    assert transmission.metadata["scenario_color"] == app._transmission_scenario_color(1)


def test_landing_duplicate_transmission_scenario_is_not_appended(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    monkeypatch.setattr(
        app,
        "load_grid_dataset_or_default",
        lambda **kwargs: _app_grid_dataset(),
    )
    app._init_landing_state()
    scenario = ScenarioContext(
        scenario_id="landing-duplicate-test",
        created_at=datetime(2026, 5, 29, 17, 0),
    )

    for _ in range(2):
        fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] = "ready"
        fake_state[app.TRANSMISSION_START_NODE_ID_STATE_KEY] = "PLANT_A"
        fake_state[app.TRANSMISSION_START_NODE_LABEL_STATE_KEY] = "A 발전소"
        fake_state[app.TRANSMISSION_END_NODE_ID_STATE_KEY] = "TOWER_C"
        fake_state[app.TRANSMISSION_END_NODE_LABEL_STATE_KEY] = "C 송전탑"
        fake_state[app.TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY] = 320.0
        app._create_transmission_scenario_from_selection(scenario, load_scale=1.0)

    assert len(fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY]) == 1
    assert "이미 있습니다" in fake_state[app.TRANSMISSION_SELECTION_WARNING_STATE_KEY]


def test_landing_builds_visible_transmission_scenario_route() -> None:
    service = app.TransmissionScenarioService()
    dataset = _app_grid_dataset()
    route = service.build_route_between_nodes(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        route_id="tx-route-001",
    )
    transmission = service.create_transmission_scenario(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        requested_transfer_mw=320.0,
        scenario_index=1,
        route=route,
        source="astar",
    )

    routes = app._build_transmission_scenario_routes([transmission])

    assert len(routes) == 1
    visible_route = routes[0]
    assert visible_route.metadata["landing_visible"] is True
    assert visible_route.metadata["display_status"] == "active_simulation"
    assert visible_route.metadata["scenario_order"] == 1
    assert visible_route.metadata["scenario_color"] == app._transmission_scenario_color(1)
    assert visible_route.metadata["used_line_ids"] == ["LINE_AB", "LINE_BC"]
    assert [point.metadata["node_id"] for point in visible_route.points] == [
        "PLANT_A",
        "TOWER_B",
        "TOWER_C",
    ]
    assert all(
        point.metadata["scenario_color"] == app._transmission_scenario_color(1)
        for point in visible_route.points
    )


def test_landing_transmission_scenario_colors_are_distinct_and_cycle() -> None:
    first_color = app._transmission_scenario_color(1)
    second_color = app._transmission_scenario_color(2)
    cycled_color = app._transmission_scenario_color(
        len(app._TRANSMISSION_SCENARIO_COLORS) + 1
    )

    assert first_color != second_color
    assert cycled_color == first_color


def test_landing_builds_only_active_transmission_routes_with_colors() -> None:
    service = app.TransmissionScenarioService()
    dataset = _app_grid_dataset()
    first_route = service.build_route_between_nodes(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        route_id="tx-route-001",
    )
    second_route = service.build_route_between_nodes(
        start_node_id="TOWER_B",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        route_id="tx-route-002",
    )
    disabled = service.create_transmission_scenario(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        requested_transfer_mw=320.0,
        scenario_index=1,
        route=first_route,
        source="astar",
    )
    active = service.create_transmission_scenario(
        start_node_id="TOWER_B",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        requested_transfer_mw=160.0,
        scenario_index=2,
        route=second_route,
        source="astar",
    )
    disabled = replace(
        disabled,
        status="disabled",
        metadata={
            **disabled.metadata,
            "scenario_order": 1,
            "scenario_color": app._transmission_scenario_color(1),
        },
    )
    active = replace(
        active,
        metadata={
            **active.metadata,
            "scenario_order": 2,
            "scenario_color": app._transmission_scenario_color(2),
        },
    )

    routes = app._build_transmission_scenario_routes([disabled, active])

    assert len(routes) == 1
    assert routes[0].candidate_id == active.scenario_route_id
    assert routes[0].metadata["scenario_order"] == 2
    assert routes[0].metadata["scenario_color"] == app._transmission_scenario_color(2)


def test_landing_transmission_scenario_status_and_clear_helpers(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    app._init_landing_state()
    service = app.TransmissionScenarioService()
    dataset = _app_grid_dataset()
    route = service.build_route_between_nodes(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        route_id="tx-route-001",
    )
    transmission = service.create_transmission_scenario(
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        grid_dataset=dataset,
        requested_transfer_mw=320.0,
        scenario_index=1,
        route=route,
        source="astar",
    )
    fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY] = [transmission]
    fake_state[app.TRANSMISSION_NEXT_INDEX_STATE_KEY] = 7
    fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] = "ready"

    assert app._set_transmission_scenario_status(
        transmission.scenario_route_id,
        "disabled",
    ) is True
    assert fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY][0].status == "disabled"
    assert app._set_transmission_scenario_status(
        transmission.scenario_route_id,
        "active",
    ) is True
    assert fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY][0].status == "active"

    app._clear_transmission_scenarios()

    assert fake_state[app.TRANSMISSION_SCENARIOS_STATE_KEY] == []
    assert fake_state[app.TRANSMISSION_NEXT_INDEX_STATE_KEY] == 1
    assert fake_state[app.TRANSMISSION_SELECTION_STEP_STATE_KEY] == "start"


def test_landing_stress_metadata_attaches_without_changing_line_status():
    scenario = ScenarioContext(
        scenario_id="landing-stress-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    from_point = MapOverlayPoint(
        overlay_id="node:A",
        label="A",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
    )
    to_point = MapOverlayPoint(
        overlay_id="node:B",
        label="B",
        kind="transmission_tower",
        latitude=36.1,
        longitude=127.1,
    )
    line = MapOverlayLine(
        overlay_id="grid-line:LINE_AB",
        label="A-B",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
        metadata={"line_id": "LINE_AB"},
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.2,
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_AB",
                from_node_id="A",
                to_node_id="B",
                capacity_mw=500.0,
                base_flow_mw=210.0,
                scenario_flow_mw=180.0,
                total_flow_mw=390.0,
                utilization=0.78,
                risk_level="medium",
                contributing_scenario_ids=["TX_001"],
                shared_route_count=1,
                status="warning",
            )
        ],
    )

    enriched = app._attach_stress_metadata([line], stress_analysis)

    assert enriched[0].status == "normal"
    assert enriched[0].metadata["stress_status"] == "warning"
    assert enriched[0].metadata["stress_utilization"] == 0.78
    assert enriched[0].metadata["stress_capacity_mw"] == 500.0
    assert enriched[0].metadata["stress_base_flow_mw"] == 210.0
    assert enriched[0].metadata["stress_total_flow_mw"] == 390.0
    assert enriched[0].metadata["stress_scenario_flow_mw"] == 180.0
    assert enriched[0].metadata["stress_capacity_margin_mw"] == 110.0
    assert enriched[0].metadata["is_bottleneck"] is False
    assert enriched[0].metadata["contributing_scenario_ids"] == ["TX_001"]
    assert enriched[0].metadata["xai_reason_summary"]
    assert enriched[0].metadata["xai_before_metrics"]["utilization"] == 0.78
    assert any(
        "송전 시나리오" in cause
        for cause in enriched[0].metadata["xai_bottleneck_causes"]
    )


def test_landing_improvement_metadata_attaches_to_target_line():
    from_point = MapOverlayPoint(
        overlay_id="node:A",
        label="A",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
    )
    to_point = MapOverlayPoint(
        overlay_id="node:B",
        label="B",
        kind="transmission_tower",
        latitude=36.1,
        longitude=127.1,
    )
    line = MapOverlayLine(
        overlay_id="grid-line:LINE_AB",
        label="A-B",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        metadata={"line_id": "LINE_AB"},
    )
    candidate = RerouteCandidate(
        candidate_id="REROUTE_TX_001",
        target_line_id="LINE_AB",
        scenario_route_id="TX_001",
        scenario_label="A -> B 송전",
        before_target_utilization=0.94,
        after_target_utilization=0.61,
        added_distance_km=12.5,
        score=42.0,
        rationale="목표 선로 이용률이 낮아집니다.",
    )
    suggested_node = SuggestedGridNode(
        suggested_node_id="SUGGESTED_TOWER_LINE_AB",
        label="A-B 우회 송전탑 후보",
        latitude=36.05,
        longitude=127.08,
        voltage_kv=345.0,
        capacity_mw=650.0,
        install_cost_billion=9.2,
        target_line_id="LINE_AB",
        reason="우회점을 추가합니다.",
    )
    proposal = GridImprovementProposal(
        proposal_id="IMPROVE_LINE_AB",
        target_line_id="LINE_AB",
        summary="LINE_AB 개선안입니다.",
        reroute_candidates=[candidate],
        suggested_nodes=[suggested_node],
    )

    enriched = app._attach_improvement_metadata([line], proposal)

    assert enriched[0].metadata["improvement_proposal_id"] == "IMPROVE_LINE_AB"
    assert enriched[0].metadata["improvement_best_candidate_id"] == "REROUTE_TX_001"
    assert enriched[0].metadata["improvement_best_after_utilization"] == 0.61
    assert enriched[0].metadata["improvement_suggested_node_label"] == "A-B 우회 송전탑 후보"


def test_landing_suggested_node_becomes_session_installation_point():
    suggested_node = SuggestedGridNode(
        suggested_node_id="SUGGESTED_TOWER_LINE_AB",
        label="A-B 우회 송전탑 후보",
        latitude=36.05,
        longitude=127.08,
        voltage_kv=345.0,
        capacity_mw=650.0,
        install_cost_billion=9.2,
        target_line_id="LINE_AB",
        relief_line_ids=["LINE_AB"],
        expected_utilization_delta=-0.22,
        reason="우회점을 추가합니다.",
        metadata={"expected_after_utilization": 0.72},
    )

    installation = app._suggested_node_to_installation_point(suggested_node)

    assert installation.kind == "transmission_tower"
    assert installation.mode == "review"
    assert installation.label == "A-B 우회 송전탑 후보"
    assert installation.voltage_kv == 345.0
    assert installation.metadata["suggested_node_id"] == "SUGGESTED_TOWER_LINE_AB"
    assert installation.metadata["recommended_capacity_mw"] == 650.0
    assert installation.metadata["relief_line_ids"] == ["LINE_AB"]


def test_landing_builds_improvement_routes_and_suggested_points():
    route = RouteResult(
        route_id="reroute-tx-001",
        start_bus_id="A",
        end_bus_id="C",
        path_node_ids=["A", "B", "C"],
        waypoints=[
            RoutePoint("A", "A", 36.0, 127.0),
            RoutePoint("B", "B", 36.1, 127.1),
            RoutePoint("C", "C", 36.2, 127.2),
        ],
        total_distance_km=30.0,
        estimated_cost=12.0,
        source="astar",
    )
    candidate = RerouteCandidate(
        candidate_id="REROUTE_TX_001",
        target_line_id="LINE_AB",
        scenario_route_id="TX_001",
        route=route,
        after_target_utilization=0.62,
        score=32.0,
    )
    suggested_node = SuggestedGridNode(
        suggested_node_id="SUGGESTED_TOWER_LINE_AB",
        label="A-B 우회 송전탑 후보",
        latitude=36.05,
        longitude=127.08,
        voltage_kv=345.0,
        capacity_mw=650.0,
        install_cost_billion=9.2,
        target_line_id="LINE_AB",
        reason="우회점을 추가합니다.",
    )
    proposal = GridImprovementProposal(
        proposal_id="IMPROVE_LINE_AB",
        target_line_id="LINE_AB",
        reroute_candidates=[candidate],
        suggested_nodes=[suggested_node],
    )

    routes = app._build_improvement_reroute_routes(proposal)
    points = app._build_improvement_suggested_points(proposal)

    assert len(routes) == 1
    assert routes[0].metadata["display_status"] == "improvement_candidate"
    assert routes[0].points[1].metadata["selection_role"] == "improvement_reroute"
    assert len(points) == 1
    assert points[0].kind == "tower_candidate"
    assert points[0].metadata["suggested_node_id"] == "SUGGESTED_TOWER_LINE_AB"


def test_landing_node_stress_metadata_attaches_to_grid_nodes():
    scenario = ScenarioContext(
        scenario_id="landing-node-stress-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    tower = MapOverlayPoint(
        overlay_id="grid-node:TOWER_A",
        label="A 송전탑",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "TOWER_A"},
    )
    route_point = MapOverlayPoint(
        overlay_id="route-point:TOWER_A",
        label="경로점",
        kind="route_point",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "TOWER_A"},
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        node_stresses=[
            NodeStressSnapshot(
                node_id="TOWER_A",
                node_name="A 송전탑",
                node_type="transmission_tower",
                generation_mw=0.0,
                load_mw=90.0,
                net_injection_mw=-90.0,
                connected_line_ids=["LINE_AB", "LINE_AC"],
                connected_scenario_ids=["TX_001", "TX_002"],
                risk_level="high",
                metadata={
                    "connected_line_count": 2,
                    "connected_scenario_count": 2,
                    "max_connected_utilization": 0.94,
                    "max_connected_line_id": "LINE_AB",
                },
            )
        ],
    )

    enriched = app._attach_node_stress_metadata([tower, route_point], stress_analysis)

    assert enriched[0].metadata["stress_node_risk_level"] == "high"
    assert enriched[0].metadata["stress_node_max_connected_utilization"] == 0.94
    assert enriched[0].metadata["stress_node_max_connected_line_id"] == "LINE_AB"
    assert enriched[0].metadata["stress_node_connected_line_count"] == 2
    assert enriched[0].metadata["stress_node_connected_scenario_count"] == 2
    assert "stress_node_risk_level" not in enriched[1].metadata


def test_landing_line_detail_merges_monitoring_and_stress() -> None:
    scenario = ScenarioContext(
        scenario_id="landing-line-detail-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    from_point = MapOverlayPoint(
        overlay_id="grid-node:A",
        label="A",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "A"},
    )
    to_point = MapOverlayPoint(
        overlay_id="grid-node:B",
        label="B",
        kind="transmission_tower",
        latitude=36.1,
        longitude=127.1,
        metadata={"node_id": "B"},
    )
    line = MapOverlayLine(
        overlay_id="grid-line:LINE_AB",
        label="A -> B",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        metadata={"line_id": "LINE_AB", "voltage_kv": 345.0, "capacity_mw": 500.0},
    )
    monitoring_result = MonitoringResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="dc_power_flow",
        load_scale=1.0,
        line_statuses=[
            LineStatus(
                line_id="LINE_AB",
                from_bus="A",
                to_bus="B",
                from_bus_name="A",
                to_bus_name="B",
                flow_mw=220.0,
                capacity_mw=500.0,
                utilization=0.44,
                status="normal",
                risk_level="low",
                loss_mw=1.7,
            )
        ],
        congestion_summary=CongestionSummary(
            total_lines=1,
            normal_count=1,
            warning_count=0,
            critical_count=0,
            overload_count=0,
            avg_utilization=0.44,
            total_loss_mw=1.7,
            max_utilization=0.44,
            max_utilization_line_id="LINE_AB",
        ),
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_AB",
                from_node_id="A",
                to_node_id="B",
                capacity_mw=500.0,
                base_flow_mw=220.0,
                scenario_flow_mw=180.0,
                total_flow_mw=400.0,
                utilization=0.8,
                risk_level="medium",
                contributing_scenario_ids=["TX_001", "TX_002"],
                shared_route_count=2,
                status="warning",
                metadata={"capacity_margin_mw": 100.0},
            )
        ],
    )

    rows = app._line_detail_rows(
        "LINE_AB",
        overlay_lines=[line],
        stress_analysis=stress_analysis,
        monitoring_result=monitoring_result,
    )
    row_by_label = {row["항목"]: row["값"] for row in rows}

    assert row_by_label["DC 현재 흐름"] == "220.00 MW"
    assert row_by_label["시나리오 추가 흐름"] == "180.00 MW"
    assert row_by_label["누적 이용률"] == "80.0%"
    assert row_by_label["기여 시나리오"] == "TX_001, TX_002"
    assert row_by_label["데이터 소스"] == "dc_power_flow"


def test_landing_stress_analysis_receives_monitoring_result(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    monkeypatch.setattr(
        app,
        "load_grid_dataset_or_default",
        lambda **kwargs: _app_grid_dataset(),
    )
    scenario = ScenarioContext(
        scenario_id="landing-monitoring-stress-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    monitoring_result = MonitoringResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="dc_power_flow",
        load_scale=1.0,
        line_statuses=[],
        congestion_summary=CongestionSummary(
            total_lines=0,
            normal_count=0,
            warning_count=0,
            critical_count=0,
            overload_count=0,
            avg_utilization=0.0,
            total_loss_mw=0.0,
            max_utilization=0.0,
            max_utilization_line_id="",
        ),
    )
    captured: dict[str, object] = {}

    def fake_analyze_route_stress(**kwargs):
        captured["monitoring_result"] = kwargs["monitoring_result"]
        return StressAnalysisResult(
            scenario=scenario,
            created_at=scenario.created_at,
            load_scale=1.0,
        )

    monkeypatch.setattr(app, "analyze_route_stress", fake_analyze_route_stress)

    result, warning = app._get_landing_stress_analysis(
        scenario,
        load_scale=1.0,
        monitoring_result=monitoring_result,
    )

    assert result is not None
    assert warning == ""
    assert captured["monitoring_result"] is monitoring_result


def test_landing_prediction_flow_uses_predicted_utilization_delta() -> None:
    scenario = ScenarioContext(
        scenario_id="landing-prediction-flow-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    prediction_result = PredictionResult(
        scenario_id=scenario.scenario_id,
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        forecast_horizon_h=24,
        predictions=[],
        risk_lines=[
            RiskLine(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                peak_risk_hour=14,
                predicted_utilization=0.8,
                risk_level="high",
                explanation="테스트",
            ),
            RiskLine(
                line_id="LINE_UNKNOWN",
                from_bus="X",
                to_bus="Y",
                from_bus_name="X",
                to_bus_name="Y",
                peak_risk_hour=14,
                predicted_utilization=1.2,
                risk_level="critical",
                explanation="테스트",
            ),
        ],
        summary="테스트",
        source="baseline",
    )
    monitoring_result = MonitoringResult(
        scenario=scenario,
        created_at=scenario.created_at,
        source="dc_power_flow",
        load_scale=1.0,
        line_statuses=[
            LineStatus(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                flow_mw=260.0,
                capacity_mw=500.0,
                utilization=0.52,
                status="normal",
                risk_level="low",
                loss_mw=0.3,
            )
        ],
        congestion_summary=CongestionSummary(
            total_lines=1,
            normal_count=1,
            warning_count=0,
            critical_count=0,
            overload_count=0,
            avg_utilization=0.52,
            total_loss_mw=0.3,
            max_utilization=0.52,
            max_utilization_line_id="LINE_AB",
        ),
    )

    predicted_flow = app._prediction_flow_by_line(
        prediction_result,
        grid_dataset=_app_grid_dataset(),
        monitoring_result=monitoring_result,
        load_scale=1.0,
    )

    assert predicted_flow == {"LINE_AB": 140.0}


def test_landing_stress_analysis_receives_prediction_flow(monkeypatch) -> None:
    fake_state = _FakeSessionState()
    monkeypatch.setattr(app.st, "session_state", fake_state)
    monkeypatch.setattr(
        app,
        "load_grid_dataset_or_default",
        lambda **kwargs: _app_grid_dataset(),
    )
    scenario = ScenarioContext(
        scenario_id="landing-prediction-stress-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    prediction_result = PredictionResult(
        scenario_id=scenario.scenario_id,
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        forecast_horizon_h=24,
        predictions=[],
        risk_lines=[
            RiskLine(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                peak_risk_hour=14,
                predicted_utilization=0.8,
                risk_level="high",
                explanation="테스트",
            )
        ],
        summary="테스트",
        source="baseline",
        metadata={"landing_model_source": "Baseline"},
    )
    captured: dict[str, object] = {}

    def fake_analyze_route_stress(**kwargs):
        captured["predicted_flow_by_line"] = kwargs["predicted_flow_by_line"]
        return StressAnalysisResult(
            scenario=scenario,
            created_at=scenario.created_at,
            load_scale=1.0,
        )

    monkeypatch.setattr(app, "analyze_route_stress", fake_analyze_route_stress)

    result, warning = app._get_landing_stress_analysis(
        scenario,
        load_scale=1.0,
        prediction_result=prediction_result,
    )

    assert result is not None
    assert warning == ""
    assert captured["predicted_flow_by_line"] == {"LINE_AB": 225.0}
    assert result.metadata["prediction_source"] == "baseline"
    assert result.metadata["prediction_model_source"] == "Baseline"


def test_prediction_briefing_comparison_summarizes_model_delta() -> None:
    scenario = ScenarioContext(
        scenario_id="landing-prediction-briefing-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    baseline_result = PredictionResult(
        scenario_id=scenario.scenario_id,
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=2.0,
        forecast_horizon_h=24,
        predictions=[],
        risk_lines=[
            RiskLine(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                peak_risk_hour=14,
                predicted_utilization=0.9,
                risk_level="critical",
                explanation="테스트",
            ),
            RiskLine(
                line_id="LINE_BC",
                from_bus="TOWER_B",
                to_bus="TOWER_C",
                from_bus_name="B 송전탑",
                to_bus_name="C 송전탑",
                peak_risk_hour=14,
                predicted_utilization=0.7,
                risk_level="medium",
                explanation="테스트",
            ),
        ],
        summary="baseline",
        source="baseline",
        metadata={"landing_model_source": "Baseline"},
    )
    selected_result = PredictionResult(
        scenario_id=scenario.scenario_id,
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=2.0,
        forecast_horizon_h=24,
        predictions=[],
        risk_lines=[
            RiskLine(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                peak_risk_hour=14,
                predicted_utilization=0.8,
                risk_level="high",
                explanation="테스트",
            )
        ],
        summary="hybrid",
        source="hybrid_neural_gnn",
        metadata={"landing_model_source": "LSTM+Neural GNN(beta)"},
    )
    baseline_stress = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=2.0,
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_AB",
                from_node_id="PLANT_A",
                to_node_id="TOWER_B",
                from_node_name="A 발전소",
                to_node_name="B 송전탑",
                capacity_mw=500.0,
                base_flow_mw=300.0,
                predicted_flow_mw=150.0,
                total_flow_mw=450.0,
                utilization=0.9,
                status="critical",
                risk_level="critical",
            ),
            LineStressSnapshot(
                line_id="LINE_BC",
                from_node_id="TOWER_B",
                to_node_id="TOWER_C",
                from_node_name="B 송전탑",
                to_node_name="C 송전탑",
                capacity_mw=500.0,
                base_flow_mw=300.0,
                predicted_flow_mw=50.0,
                total_flow_mw=350.0,
                utilization=0.7,
                status="warning",
                risk_level="medium",
            ),
        ],
        bottleneck_line_ids=["LINE_AB"],
        critical_line_ids=["LINE_AB"],
    )
    selected_stress = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=2.0,
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_AB",
                from_node_id="PLANT_A",
                to_node_id="TOWER_B",
                from_node_name="A 발전소",
                to_node_name="B 송전탑",
                capacity_mw=500.0,
                base_flow_mw=300.0,
                predicted_flow_mw=100.0,
                total_flow_mw=400.0,
                utilization=0.8,
                status="warning",
                risk_level="high",
            ),
            LineStressSnapshot(
                line_id="LINE_BC",
                from_node_id="TOWER_B",
                to_node_id="TOWER_C",
                from_node_name="B 송전탑",
                to_node_name="C 송전탑",
                capacity_mw=500.0,
                base_flow_mw=300.0,
                predicted_flow_mw=0.0,
                total_flow_mw=300.0,
                utilization=0.6,
                status="normal",
                risk_level="low",
            ),
        ],
    )

    comparison = app._build_prediction_briefing_comparison(
        baseline_result=baseline_result,
        selected_result=selected_result,
        baseline_stress=baseline_stress,
        selected_stress=selected_stress,
        selected_model_label="LSTM+Neural GNN(beta)",
    )

    risk_summary = next(row for row in comparison.summary_rows if row["항목"] == "미래 위험 선로")
    max_summary = next(row for row in comparison.summary_rows if row["항목"] == "최대 이용률")
    line_ab = next(row for row in comparison.line_delta_rows if row["선로 ID"] == "LINE_AB")

    assert risk_summary["변화"] == "-1개"
    assert max_summary["변화"] == "-10.0 pp"
    assert line_ab["구간"] == "A 발전소->B 송전탑"
    assert line_ab["변화 pp"] == -10.0
    assert line_ab["예측 MW 변화"] == "-50.0 MW"


def test_landing_node_detail_uses_node_stress() -> None:
    point = MapOverlayPoint(
        overlay_id="grid-node:TOWER_A",
        label="A 송전탑",
        kind="transmission_tower",
        latitude=36.0,
        longitude=127.0,
        metadata={"node_id": "TOWER_A", "voltage_kv": 345.0},
    )
    scenario = ScenarioContext(
        scenario_id="landing-node-detail-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        node_stresses=[
            NodeStressSnapshot(
                node_id="TOWER_A",
                node_name="A 송전탑",
                node_type="transmission_tower",
                generation_mw=0.0,
                load_mw=85.0,
                net_injection_mw=-85.0,
                connected_line_ids=["LINE_AB"],
                connected_scenario_ids=["TX_001"],
                risk_level="medium",
                metadata={
                    "connected_line_count": 1,
                    "max_connected_utilization": 0.74,
                    "max_connected_line_id": "LINE_AB",
                },
            )
        ],
    )

    rows = app._node_detail_rows(
        "TOWER_A",
        overlay_points=[point],
        stress_analysis=stress_analysis,
    )
    row_by_label = {row["항목"]: row["값"] for row in rows}

    assert row_by_label["발전량"] == "0.00 MW"
    assert row_by_label["부하량"] == "85.00 MW"
    assert row_by_label["연결 선로"] == "LINE_AB"
    assert row_by_label["최대 연결 이용률"] == "74.0%"
    assert row_by_label["위험도"] == "medium"


def test_landing_stress_table_rows_sort_and_filter() -> None:
    scenario = ScenarioContext(
        scenario_id="landing-stress-table-test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        bottleneck_line_ids=["LINE_HIGH", "LINE_SHARED"],
        warning_line_ids=["LINE_WARN"],
        critical_line_ids=["LINE_HIGH"],
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_NORMAL",
                from_node_id="A",
                to_node_id="B",
                capacity_mw=500.0,
                base_flow_mw=100.0,
                total_flow_mw=100.0,
                utilization=0.2,
                status="normal",
            ),
            LineStressSnapshot(
                line_id="LINE_WARN",
                from_node_id="B",
                to_node_id="C",
                capacity_mw=500.0,
                base_flow_mw=200.0,
                scenario_flow_mw=170.0,
                total_flow_mw=370.0,
                utilization=0.74,
                risk_level="medium",
                contributing_scenario_ids=["TX_001"],
                shared_route_count=1,
                status="warning",
            ),
            LineStressSnapshot(
                line_id="LINE_HIGH",
                from_node_id="C",
                to_node_id="D",
                capacity_mw=500.0,
                base_flow_mw=200.0,
                scenario_flow_mw=280.0,
                total_flow_mw=480.0,
                utilization=0.96,
                risk_level="high",
                contributing_scenario_ids=["TX_002"],
                shared_route_count=1,
                status="critical",
            ),
            LineStressSnapshot(
                line_id="LINE_SHARED",
                from_node_id="D",
                to_node_id="E",
                capacity_mw=500.0,
                base_flow_mw=100.0,
                scenario_flow_mw=40.0,
                total_flow_mw=140.0,
                utilization=0.28,
                contributing_scenario_ids=["TX_001", "TX_002"],
                shared_route_count=2,
                status="normal",
            ),
        ],
    )

    rows = app._line_utilization_table_rows(stress_analysis)
    warning_rows = app._line_utilization_table_rows(
        stress_analysis,
        status_filter="경고",
    )
    bottleneck_rows = app._line_utilization_table_rows(
        stress_analysis,
        status_filter="병목만",
    )
    risk_rows = app._risk_line_table_rows(stress_analysis)
    warning_chart_rows = app._line_utilization_chart_rows(warning_rows)
    bottleneck_chart_rows = app._line_utilization_chart_rows(bottleneck_rows)
    metrics = app._stress_summary_metrics(stress_analysis)

    assert [row["선로 ID"] for row in rows] == [
        "LINE_HIGH",
        "LINE_WARN",
        "LINE_SHARED",
        "LINE_NORMAL",
    ]
    assert [row["선로 ID"] for row in warning_rows] == ["LINE_WARN"]
    assert {row["선로 ID"] for row in bottleneck_rows} == {
        "LINE_HIGH",
        "LINE_SHARED",
    }
    assert {row["선로 ID"] for row in risk_rows} == {
        "LINE_HIGH",
        "LINE_WARN",
        "LINE_SHARED",
    }
    assert [row["선로 ID"] for row in warning_chart_rows] == ["LINE_WARN"]
    assert warning_chart_rows[0]["표시명"] == "B->C"
    assert warning_chart_rows[0]["이용률 % 값"] == 74.0
    assert warning_chart_rows[0]["막대 색상"] == app._STRESS_STATUS_BAR_COLORS["warning"]
    assert {row["선로 ID"] for row in bottleneck_chart_rows} == {
        "LINE_HIGH",
        "LINE_SHARED",
    }
    assert metrics["병목 선로"] == 2
    assert metrics["위험/과부하"] == 1
    assert metrics["최대 이용률 선로"] == "LINE_HIGH"
    assert metrics["최대 이용률"] == "96.0%"


def test_line_utilization_display_label_prefers_korean_endpoint_names() -> None:
    row = {
        "선로 ID": "GLINE_TOWER_DANGJIN_TOWER_PYEONGTAEK",
        "From": "당진 송전탑",
        "To": "평택 송전탑",
    }

    assert app._line_utilization_display_label(row) == "당진 송전탑->평택 송전탑"


def test_operation_console_status_items_expose_demo_flow(monkeypatch):
    fake_state = _FakeSessionState(
        {
            app.SELECTED_GRID_OBJECT_STATE_KEY: {
                "type": "line",
                "id": "LINE_HIGH",
                "label": "High line",
            }
        }
    )
    monkeypatch.setattr(app.st, "session_state", fake_state)
    scenario = ScenarioContext(
        scenario_id="status-bar-test",
        created_at=datetime(2026, 5, 29, 18, 0),
    )
    stress_analysis = StressAnalysisResult(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
        line_stresses=[
            LineStressSnapshot(
                line_id="LINE_HIGH",
                from_node_id="A",
                to_node_id="B",
                capacity_mw=500.0,
                total_flow_mw=480.0,
                utilization=0.96,
                status="critical",
            )
        ],
        bottleneck_line_ids=["LINE_HIGH"],
        critical_line_ids=["LINE_HIGH"],
    )
    proposal = GridImprovementProposal(
        proposal_id="IMPROVE_LINE_HIGH",
        target_line_id="LINE_HIGH",
        reroute_candidates=[
            RerouteCandidate(
                candidate_id="REROUTE_TX_001",
                target_line_id="LINE_HIGH",
                scenario_route_id="TX_001",
            )
        ],
    )

    items = dict(
        app._operation_status_items(
            interaction_mode="transmission",
            stress_analysis=stress_analysis,
            prediction_result=None,
            improvement_proposal=proposal,
        )
    )

    assert items["작업 모드"] == "송전 시나리오"
    assert items["병목 선로"] == "1"
    assert items["위험/과부하"] == "1"
    assert items["선택 선로"] == "LINE_HIGH"
    assert items["Prediction"] == "미반영"
    assert items["개선안"] == "1개 우회"


def test_map_layer_legend_documents_operation_layers():
    labels = [label for label, _, _ in app._map_layer_legend_items()]

    assert labels == [
        "선로 <50%",
        "선로 50-70%",
        "선로 70-85%",
        "선로 85-100%",
        "선로 100-125%",
        "선로 125%+",
        "활성 송전 시나리오",
        "선택 선로",
        "우회 경로 후보",
        "신규 송전탑 후보",
    ]


def test_transmission_scenario_table_rows_are_console_ready():
    route = RouteResult(
        route_id="tx-route-001",
        start_bus_id="A",
        end_bus_id="B",
        path_node_ids=["A", "B"],
        source="astar",
    )
    scenario = TransmissionScenario(
        scenario_route_id="TX_001",
        label="A -> B 300MW 송전",
        start_node_id="A",
        end_node_id="B",
        start_node_name="A 발전소",
        end_node_name="B 송전탑",
        requested_transfer_mw=300.0,
        route=route,
        path_node_ids=["A", "B"],
        used_line_ids=["LINE_AB"],
        status="active",
        source="astar",
        created_at=datetime(2026, 5, 29, 18, 0),
        metadata={"scenario_order": 3},
    )

    rows = app._transmission_scenario_table_rows([scenario])

    assert rows == [
        {
            "순번": 3,
            "상태": "active",
            "시나리오": "A -> B 300MW 송전",
            "시작": "A 발전소",
            "종료": "B 송전탑",
            "송전량 MW": 300.0,
            "경로 노드 수": 2,
            "사용 선로 수": 1,
            "경로 source": "astar",
            "생성 시각": "2026-05-29T18:00:00",
        }
    ]


def test_landing_page_uses_common_map_overlay_renderer():
    source = Path(app.__file__).read_text(encoding="utf-8")

    assert "from src.ui.map_overlay_renderer import render_map_overlay" in source
    assert "analyze_route_stress" in source
    assert "PredictionService" in source
    assert "from src.data.loaders import load_grid_dataset_or_default" in source
    assert "load_grid_dataset_or_default(" in source
    assert "GLOBAL_LOAD_SCALE_STATE_KEY" in source
    assert "PREDICTION_RESULT_STATE_KEY" in source
    assert "LANDING_INTERACTION_MODE_STATE_KEY" in source
    assert "TRANSMISSION_SELECTION_STEP_STATE_KEY" in source
    assert "STRESS_ANALYSIS_STATE_KEY" in source
    assert "MapOverlayService().build_grid_overlay(" in source
    assert "render_map_overlay(" in source
    assert "return_map_data=True" in source
    assert "MapOverlayService().build_landing_overlay(" in source
    assert "_build_landing_points(grid_overlay, service_overlay)" in source
    assert "_build_landing_routes(service_overlay)" in source
    assert "_build_transmission_scenario_routes(_landing_transmission_scenarios())" in source
    assert "_render_selected_grid_object_dialog(" not in source
    assert "@st.dialog(" not in source
    assert "_render_selected_grid_object_detail(" not in source
    assert "_render_selected_point(" not in source
    assert "최근 선택 지점" not in source
    assert "landing_overlay.summary" not in source
    assert "지도 fallback 및 좌표 메타데이터" not in source


def test_legacy_multipage_sidebar_navigation_is_hidden():
    config_path = Path(app.__file__).resolve().parent / ".streamlit" / "config.toml"
    config_source = config_path.read_text(encoding="utf-8")

    assert "[client]" in config_source
    assert "showSidebarNavigation = false" in config_source


def test_landing_page_does_not_keep_local_folium_renderer_helpers():
    source = Path(app.__file__).read_text(encoding="utf-8")
    forbidden_fragments = [
        "def _render_operational_map",
        "def _load_map_libraries",
        "def _render_overlay_table",
        "def _point_style",
        "def _point_popup_html",
        "streamlit_folium",
        "folium.",
    ]

    assert all(fragment not in source for fragment in forbidden_fragments)
