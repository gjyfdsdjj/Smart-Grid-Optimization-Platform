from __future__ import annotations

import inspect

from src.data.schemas import MapOverlayPoint
from src.ui.map_overlay_renderer import (
    overlay_warnings_for_display,
    point_style_for_overlay_point,
    render_map_overlay,
)


def test_renderer_supports_optional_click_return_contract():
    signature = inspect.signature(render_map_overlay)

    assert "return_map_data" in signature.parameters
    assert signature.parameters["return_map_data"].default is False
    assert signature.return_annotation == "dict[str, Any] | None"


def test_overlay_warnings_for_display_removes_service_duplicates():
    warnings = overlay_warnings_for_display(
        ["service fallback", "same warning"],
        ["same warning", "map warning", "elevation warning"],
    )

    assert warnings == ["map warning", "elevation warning"]


def test_common_point_style_covers_landing_assets():
    selected = point_style_for_overlay_point(
        MapOverlayPoint(
            overlay_id="selected",
            label="선택 지점",
            kind="install_point",
            latitude=36.45,
            longitude=127.85,
            status="selected",
        )
    )
    plant = point_style_for_overlay_point(
        MapOverlayPoint(
            overlay_id="plant",
            label="발전소",
            kind="power_plant",
            latitude=36.45,
            longitude=127.85,
        )
    )
    tower = point_style_for_overlay_point(
        MapOverlayPoint(
            overlay_id="tower",
            label="송전탑",
            kind="transmission_tower",
            latitude=36.45,
            longitude=127.85,
        )
    )

    assert selected["radius"] > plant["radius"]
    assert plant["color"] != tower["color"]
    assert tower["fill_color"] != selected["fill_color"]
