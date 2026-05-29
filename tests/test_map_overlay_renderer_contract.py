from __future__ import annotations

import inspect

from src.data.schemas import MapOverlayLine, MapOverlayPoint, MapOverlayRoute
from src.ui.map_overlay_renderer import (
    line_style_for_overlay_line,
    overlay_warnings_for_display,
    point_style_for_overlay_point,
    render_map_overlay,
    route_style_for_overlay_route,
    split_overlay_lines_by_highlight,
)


def test_renderer_supports_optional_click_return_contract():
    signature = inspect.signature(render_map_overlay)
    source = inspect.getsource(render_map_overlay)

    assert "return_map_data" in signature.parameters
    assert signature.parameters["return_map_data"].default is False
    assert signature.return_annotation == "dict[str, Any] | None"
    assert "last_object_clicked_tooltip" in source


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


def test_point_style_uses_node_stress_risk_metadata():
    stressed_tower = MapOverlayPoint(
        overlay_id="tower",
        label="송전탑",
        kind="transmission_tower",
        latitude=36.45,
        longitude=127.85,
        metadata={
            "stress_node_risk_level": "high",
            "stress_node_max_connected_utilization": 0.94,
        },
    )
    normal_tower = MapOverlayPoint(
        overlay_id="tower-normal",
        label="송전탑",
        kind="transmission_tower",
        latitude=36.45,
        longitude=127.85,
    )
    selected_stressed_tower = MapOverlayPoint(
        overlay_id="tower-selected",
        label="선택 송전탑",
        kind="transmission_tower",
        latitude=36.45,
        longitude=127.85,
        status="selected",
        metadata={"stress_node_risk_level": "critical"},
    )

    stressed = point_style_for_overlay_point(stressed_tower)
    normal = point_style_for_overlay_point(normal_tower)
    selected = point_style_for_overlay_point(selected_stressed_tower)

    assert stressed["color"] == "#b91c1c"
    assert stressed["radius"] > normal["radius"]
    assert selected["color"] == "#7c3aed"


def test_active_landing_route_style_is_red():
    route = MapOverlayRoute(
        overlay_id="simulation-route:active",
        label="활성 최적 경로",
        route_id="active",
        rank=1,
        metadata={"landing_visible": True, "display_status": "active_simulation"},
    )
    default_ranked_route = MapOverlayRoute(
        overlay_id="simulation-route:ranked",
        label="1순위 추천 경로",
        route_id="ranked",
        rank=1,
    )

    active_style = route_style_for_overlay_route(route)
    ranked_style = route_style_for_overlay_route(default_ranked_route)

    assert active_style["color"] == "#dc2626"
    assert active_style["weight"] > ranked_style["weight"]
    assert ranked_style["color"] == "#2563eb"


def test_active_landing_route_uses_transmission_scenario_color():
    route = MapOverlayRoute(
        overlay_id="transmission-route:active",
        label="활성 송전 시나리오",
        route_id="active",
        metadata={
            "landing_visible": True,
            "display_status": "active_simulation",
            "scenario_color": "#059669",
        },
    )

    style = route_style_for_overlay_route(route)

    assert style["color"] == "#059669"
    assert style["weight"] == 6


def test_line_style_prefers_stress_status_metadata():
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
        metadata={
            "stress_status": "overload",
            "stress_utilization": 1.08,
            "is_bottleneck": True,
        },
    )
    normal_line = MapOverlayLine(
        overlay_id="grid-line:LINE_BC",
        label="B-C",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
    )

    stress_style = line_style_for_overlay_line(line)
    normal_style = line_style_for_overlay_line(normal_line)
    selected_style = line_style_for_overlay_line(line, selected=True)

    assert stress_style["color"] == "#991b1b"
    assert stress_style["weight"] > normal_style["weight"]
    assert stress_style["opacity"] > normal_style["opacity"]
    assert selected_style["color"] == "#7c3aed"


def test_line_style_highlights_shared_route_bottleneck():
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
        overlay_id="grid-line:LINE_SHARED",
        label="A-B",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
        metadata={
            "stress_status": "normal",
            "is_bottleneck": True,
        },
    )

    style = line_style_for_overlay_line(line)

    assert style["color"] == "#f97316"
    assert style["weight"] >= 6


def test_highlighted_lines_are_split_for_route_overlay_order():
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
    normal_line = MapOverlayLine(
        overlay_id="grid-line:NORMAL",
        label="normal",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
    )
    bottleneck_line = MapOverlayLine(
        overlay_id="grid-line:BOTTLENECK",
        label="bottleneck",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
        metadata={"stress_status": "normal", "is_bottleneck": True},
    )
    warning_line = MapOverlayLine(
        overlay_id="grid-line:WARNING",
        label="warning",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status="normal",
        metadata={"stress_status": "warning"},
    )

    base_lines, highlighted_lines = split_overlay_lines_by_highlight(
        [normal_line, bottleneck_line, warning_line]
    )

    assert base_lines == [normal_line]
    assert highlighted_lines == [bottleneck_line, warning_line]
