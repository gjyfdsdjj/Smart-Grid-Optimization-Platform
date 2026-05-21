from __future__ import annotations

from datetime import datetime
from pathlib import Path

import app
from src.data.schemas import InstallationPoint, MapOverlayPoint


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
        "인천 송전탑",
        "서울 송전탑",
        "강릉 송전탑",
        "대전 송전탑",
        "나주 송전탑",
        "충북 송전탑",
        "구미 송전탑",
        "대구 송전탑",
        "부산 송전탑",
        "울산 송전탑",
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
