from __future__ import annotations

from datetime import datetime
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

import app
from src.data.schemas import InstallationPoint, MapOverlayPoint


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


def test_landing_page_uses_common_map_overlay_renderer():
    source = Path(app.__file__).read_text(encoding="utf-8")

    assert "from src.ui.map_overlay_renderer import overlay_warnings_for_display, render_map_overlay" in source
    assert "render_map_overlay(" in source
    assert "return_map_data=True" in source
    assert "MapOverlayService().build_landing_overlay(" in source
    assert "_render_selected_point(" not in source
    assert "최근 선택 지점" not in source


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
