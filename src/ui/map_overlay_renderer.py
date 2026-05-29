# MapOverlayResult를 Streamlit/Folium 지도 또는 표 fallback으로 렌더링한다.
from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from src.data.adapters.vworld_adapter import MapCapability
from src.data.schemas import (
    MapOverlayLine,
    MapOverlayPoint,
    MapOverlayResult,
    MapOverlayRoute,
)


_KOREA_CENTER = [36.45, 127.85]
_LINE_COLOR: dict[str, str] = {
    "normal": "#22c55e",
    "warning": "#f59e0b",
    "critical": "#dc2626",
    "overload": "#7f1d1d",
    "unknown": "#94a3b8",
    "selected": "#7c3aed",
}
_UTILIZATION_LINE_STYLES: tuple[tuple[float, str, int, float], ...] = (
    (1.25, "#7f1d1d", 8, 0.98),
    (1.0, "#dc2626", 7, 0.94),
    (0.85, "#f97316", 6, 0.88),
    (0.70, "#f59e0b", 5, 0.78),
    (0.50, "#22c55e", 4, 0.62),
    (0.0, "#64748b", 3, 0.45),
)


def render_map_overlay(
    overlay: MapOverlayResult,
    *,
    map_capability: MapCapability,
    selected_line_id: str | None = None,
    height: int = 620,
    width: int | None = 1200,
    show_point_table: bool = False,
    return_map_data: bool = False,
) -> dict[str, Any] | None:
    """Render an overlay map without exposing provider secrets in UI messages."""

    folium, st_folium, import_error = _load_map_libraries()
    if import_error is not None:
        st.warning(f"지도 라이브러리 fallback: {import_error}")
        render_overlay_fallback_map(overlay)
        render_overlay_fallback_tables(overlay, show_points=show_point_table)
        return None

    folium_map = folium.Map(
        location=_map_center(overlay),
        zoom_start=7,
        tiles=None,
        control_scale=True,
    )
    _add_tile_layer(folium, folium_map, map_capability)

    base_lines, highlighted_lines = split_overlay_lines_by_highlight(overlay.lines)
    for line in base_lines:
        _add_overlay_line(
            folium,
            folium_map,
            line,
            selected=line_id_from_overlay_line(line) == selected_line_id,
        )
    for route in overlay.routes:
        _add_overlay_route(folium, folium_map, route)
    for line in highlighted_lines:
        _add_overlay_line(
            folium,
            folium_map,
            line,
            selected=line_id_from_overlay_line(line) == selected_line_id,
        )
    for point in overlay.points:
        _add_overlay_point(folium, folium_map, point)

    folium.LayerControl(collapsed=True).add_to(folium_map)
    returned_objects = [
        "last_clicked",
        "last_object_clicked",
        "last_object_clicked_tooltip",
    ] if return_map_data else []
    map_data = st_folium(
        folium_map,
        width=width,
        height=height,
        use_container_width=width is None,
        returned_objects=returned_objects,
    )
    if return_map_data:
        return map_data
    return None


def render_overlay_fallback_tables(
    overlay: MapOverlayResult,
    *,
    show_points: bool = False,
) -> None:
    """Render a compact tabular fallback when Folium is unavailable."""

    line_rows = [
        {
            "선로 ID": line_id_from_overlay_line(line),
            "구간": line.label,
            "상태": line.status,
            "이용률 (%)": round(line_utilization_from_overlay_line(line) * 100, 1),
            "소스": line.source,
        }
        for line in overlay.lines
    ]
    route_rows = [
        {
            "순위": route.rank,
            "후보지": route.metadata.get("candidate_label", route.candidate_id),
            "경로 길이 (km)": round(route.total_distance_km, 1),
            "예상 비용": round(route.estimated_cost, 1),
            "소스": route.source,
        }
        for route in overlay.routes
    ]
    point_rows = [
        {
            "구분": point.kind,
            "이름": point.label,
            "x": round(point.longitude, 6),
            "y": round(point.latitude, 6),
            "상태": point.status,
            "소스": point.source,
        }
        for point in overlay.points
    ]

    if line_rows:
        st.dataframe(pd.DataFrame(line_rows), width="stretch", hide_index=True)
    if route_rows:
        st.dataframe(pd.DataFrame(route_rows), width="stretch", hide_index=True)
    if point_rows and (show_points or (not line_rows and not route_rows)):
        st.dataframe(pd.DataFrame(point_rows), width="stretch", hide_index=True)


def render_overlay_fallback_map(overlay: MapOverlayResult) -> None:
    """Render a native Streamlit map when Folium is unavailable."""

    rows: list[dict[str, float | str]] = []
    for point in overlay.points:
        rows.append(
            {
                "latitude": point.latitude,
                "longitude": point.longitude,
                "label": point.label,
            }
        )
    for line in overlay.lines:
        rows.extend(
            [
                {
                    "latitude": line.from_point.latitude,
                    "longitude": line.from_point.longitude,
                    "label": line.from_point.label,
                },
                {
                    "latitude": line.to_point.latitude,
                    "longitude": line.to_point.longitude,
                    "label": line.to_point.label,
                },
            ]
        )
    for route in overlay.routes:
        for point in route.points:
            rows.append(
                {
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "label": point.label,
                }
            )

    if not rows:
        return

    st.map(pd.DataFrame(rows), latitude="latitude", longitude="longitude", use_container_width=True)


def line_id_from_overlay_line(line: MapOverlayLine) -> str:
    return str(line.metadata.get("line_id", line.overlay_id))


def line_utilization_from_overlay_line(line: MapOverlayLine) -> float:
    raw_value = line.metadata.get(
        "utilization",
        line.metadata.get("predicted_utilization", 0.0),
    )
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return 0.0


def overlay_warnings_for_display(
    source_warnings: list[str],
    overlay_warnings: list[str],
) -> list[str]:
    """Return overlay-only warnings without repeating service warnings."""
    source_warning_set = set(source_warnings)
    return [
        warning
        for warning in overlay_warnings
        if warning not in source_warning_set
    ]


def line_style_for_status(status: str, *, selected: bool = False) -> dict[str, Any]:
    return {
        "color": "#7c3aed" if selected else _LINE_COLOR.get(status, "#94a3b8"),
        "weight": 7 if selected else 4,
        "opacity": 0.95 if selected else 0.52,
    }


def line_style_for_utilization(
    utilization: float,
    *,
    selected: bool = False,
) -> dict[str, Any]:
    if selected:
        return line_style_for_status("selected", selected=True)

    utilization = max(0.0, float(utilization))
    for threshold, color, weight, opacity in _UTILIZATION_LINE_STYLES:
        if utilization >= threshold:
            return {
                "color": color,
                "weight": weight,
                "opacity": opacity,
            }
    return {
        "color": "#64748b",
        "weight": 3,
        "opacity": 0.45,
    }


def line_style_for_overlay_line(
    line: MapOverlayLine,
    *,
    selected: bool = False,
) -> dict[str, Any]:
    if selected:
        return line_style_for_status(line.status, selected=True)

    stress_status = line.metadata.get("stress_status")
    status = stress_status if isinstance(stress_status, str) and stress_status else line.status
    utilization = _float_metadata(line.metadata.get("stress_utilization"))
    if utilization is None:
        utilization = _float_metadata(line.metadata.get("predicted_utilization"))
    style = line_style_for_utilization(utilization) if utilization is not None else line_style_for_status(status)
    if utilization is None:
        if status == "warning":
            style.update({"weight": 5, "opacity": 0.78})
        elif status == "critical":
            style.update({"weight": 6, "opacity": 0.88})
        elif status == "overload":
            style.update({"weight": 7, "opacity": 0.95})
    if line.metadata.get("is_bottleneck") is True:
        if status == "normal" and (utilization is None or utilization < 0.70):
            style["color"] = "#f97316"
        style["weight"] = max(int(style["weight"]), 6)
        style["opacity"] = max(float(style["opacity"]), 0.86)
    return style


def line_is_stress_highlighted(line: MapOverlayLine) -> bool:
    stress_status = line.metadata.get("stress_status")
    stress_utilization = _float_metadata(line.metadata.get("stress_utilization"))
    predicted_flow_mw = _float_metadata(line.metadata.get("stress_predicted_flow_mw"))
    return (
        stress_status in {"warning", "critical", "overload"}
        or line.metadata.get("is_bottleneck") is True
        or (stress_utilization is not None and stress_utilization >= 0.50)
        or (predicted_flow_mw is not None and predicted_flow_mw > 0.0)
    )


def _float_metadata(value: object) -> float | None:
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def split_overlay_lines_by_highlight(
    lines: list[MapOverlayLine],
) -> tuple[list[MapOverlayLine], list[MapOverlayLine]]:
    base_lines: list[MapOverlayLine] = []
    highlighted_lines: list[MapOverlayLine] = []
    for line in lines:
        if line_is_stress_highlighted(line):
            highlighted_lines.append(line)
        else:
            base_lines.append(line)
    return base_lines, highlighted_lines


def route_style_for_overlay_route(route: MapOverlayRoute) -> dict[str, Any]:
    """Style active app simulation routes distinctly from ranked recommendations."""
    display_status = str(route.metadata.get("display_status", ""))
    scenario_color = route.metadata.get("scenario_color")
    if isinstance(scenario_color, str) and scenario_color.strip():
        return {
            "color": scenario_color.strip(),
            "weight": 6,
            "opacity": 0.95,
            "dash_array": None,
        }
    if display_status == "improvement_candidate":
        return {
            "color": "#2563eb",
            "weight": 5,
            "opacity": 0.88,
            "dash_array": "8",
        }
    if route.metadata.get("landing_visible") is True or display_status in {
        "active_simulation",
        "optimal_route",
        "selected",
    }:
        return {"color": "#dc2626", "weight": 6, "opacity": 0.95, "dash_array": None}

    return {
        "color": "#2563eb" if route.rank == 1 else "#64748b",
        "weight": 5 if route.rank == 1 else 3,
        "opacity": 0.9 if route.rank == 1 else 0.45,
        "dash_array": "10" if route.rank == 1 else None,
    }


def _load_map_libraries() -> tuple[Any | None, Any | None, str | None]:
    try:
        import folium
        from streamlit_folium import st_folium

        return folium, st_folium, None
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)


def _map_center(overlay: MapOverlayResult) -> list[float]:
    points = list(overlay.points)
    if not points:
        return list(_KOREA_CENTER)

    return [
        sum(point.latitude for point in points) / len(points),
        sum(point.longitude for point in points) / len(points),
    ]


def _add_tile_layer(folium: Any, folium_map: Any, map_capability: MapCapability) -> None:
    if map_capability.wmts_tile_url:
        folium.TileLayer(
            tiles=map_capability.wmts_tile_url,
            attr="공간정보 오픈플랫폼(브이월드)",
            name="VWorld 2.5D",
            overlay=False,
            control=True,
        ).add_to(folium_map)
        return

    folium.TileLayer(
        tiles="CartoDB positron",
        name="Fallback 2D",
        overlay=False,
        control=True,
    ).add_to(folium_map)


def _line_tooltip(line: MapOverlayLine, line_id: str) -> str:
    status = line.metadata.get("stress_status", line.status)
    utilization = line.metadata.get("stress_utilization")
    if isinstance(utilization, (float, int)):
        return f"{line_id} | {line.label} | {status} | 이용률 {utilization:.1%}"
    return f"{line_id} | {line.label} | {status}"


def _add_overlay_line(
    folium: Any,
    folium_map: Any,
    line: MapOverlayLine,
    *,
    selected: bool,
) -> None:
    style = line_style_for_overlay_line(line, selected=selected)
    line_id = line_id_from_overlay_line(line)
    folium.PolyLine(
        locations=[
            [line.from_point.latitude, line.from_point.longitude],
            [line.to_point.latitude, line.to_point.longitude],
        ],
        color=style["color"],
        weight=style["weight"],
        opacity=style["opacity"],
        popup=folium.Popup(line_popup_html_for_overlay_line(line), max_width=460),
        tooltip=_line_tooltip(line, line_id),
    ).add_to(folium_map)


def _add_overlay_route(folium: Any, folium_map: Any, route: MapOverlayRoute) -> None:
    route_coords = [[point.latitude, point.longitude] for point in route.points]
    if len(route_coords) < 2:
        return
    style = route_style_for_overlay_route(route)

    folium.PolyLine(
        locations=route_coords,
        color=style["color"],
        weight=style["weight"],
        dash_array=style["dash_array"],
        tooltip=route.label,
        opacity=style["opacity"],
    ).add_to(folium_map)


def _add_overlay_point(folium: Any, folium_map: Any, point: MapOverlayPoint) -> None:
    style = point_style_for_overlay_point(point)
    folium.CircleMarker(
        location=[point.latitude, point.longitude],
        radius=style["radius"],
        popup=folium.Popup(point_popup_html_for_overlay_point(point), max_width=460),
        tooltip=point.label,
        color=style["color"],
        fill=True,
        fill_color=style["fill_color"],
        fill_opacity=style["fill_opacity"],
        weight=style["weight"],
    ).add_to(folium_map)


def point_style_for_overlay_point(point: MapOverlayPoint) -> dict[str, Any]:
    if point.status == "selected":
        return {"color": "#7c3aed", "fill_color": "#a78bfa", "fill_opacity": 0.95, "radius": 9, "weight": 3}
    stress_style = _point_stress_style(point)
    if stress_style is not None:
        return stress_style
    if point.kind == "tower_candidate":
        return {"color": "#047857", "fill_color": "#34d399", "fill_opacity": 0.9, "radius": 7, "weight": 2}
    if point.kind == "route_point":
        return {"color": "#2563eb", "fill_color": "#ffffff", "fill_opacity": 1.0, "radius": 5, "weight": 2}
    if point.kind == "power_plant":
        return {"color": "#b91c1c", "fill_color": "#ef4444", "fill_opacity": 0.9, "radius": 8, "weight": 2}
    if point.kind == "transmission_tower":
        return {"color": "#1d4ed8", "fill_color": "#60a5fa", "fill_opacity": 0.9, "radius": 7, "weight": 2}
    return {"color": "#334155", "fill_color": "#cbd5e1", "fill_opacity": 0.85, "radius": 5, "weight": 2}


def _point_stress_style(point: MapOverlayPoint) -> dict[str, Any] | None:
    if point.kind not in {"power_plant", "transmission_tower"}:
        return None

    risk_level = point.metadata.get("stress_node_risk_level")
    if risk_level == "critical":
        return {"color": "#7f1d1d", "fill_color": "#dc2626", "fill_opacity": 0.96, "radius": 10, "weight": 4}
    if risk_level == "high":
        return {"color": "#b91c1c", "fill_color": "#ef4444", "fill_opacity": 0.94, "radius": 9, "weight": 3}
    if risk_level == "medium":
        return {"color": "#d97706", "fill_color": "#f59e0b", "fill_opacity": 0.92, "radius": 8, "weight": 3}
    return None


def point_popup_html_for_overlay_point(point: MapOverlayPoint) -> str:
    metadata = point.metadata
    rows = [
        ("객체", "노드" if point.kind in {"power_plant", "transmission_tower"} else _kind_label(point.kind)),
        ("노드 ID", _metadata_text(metadata, "node_id", point.overlay_id)),
        ("이름", point.label),
        ("유형", _metadata_text(metadata, "node_type", point.kind)),
        ("전압", _format_kv(metadata.get("voltage_kv"))),
        ("권장 용량", _format_mw(metadata.get("capacity_mw")) if point.kind == "tower_candidate" else ""),
        ("예상 비용", _format_cost_billion(metadata.get("install_cost_billion"))),
        ("완화 선로", _format_list(metadata.get("relief_line_ids"))),
        ("제안 이유", _metadata_text(metadata, "reason")),
        ("발전량", _format_mw(_first_present(metadata, "stress_node_generation_mw", "generation_mw"))),
        ("부하량", _format_mw(_first_present(metadata, "stress_node_load_mw", "load_mw", "base_load_mw"))),
        ("순주입량", _format_mw(_first_present(metadata, "stress_node_net_injection_mw", "net_injection_mw"))),
        ("연결 선로 수", _metadata_text(metadata, "stress_node_connected_line_count")),
        ("연결 선로", _format_list(metadata.get("stress_node_connected_line_ids"))),
        ("연결 시나리오", _format_list(metadata.get("stress_node_connected_scenario_ids"))),
        ("최대 연결 이용률", _format_percent(metadata.get("stress_node_max_connected_utilization"))),
        ("최대 이용률 선로", _metadata_text(metadata, "stress_node_max_connected_line_id")),
        ("위험도", _metadata_text(metadata, "stress_node_risk_level", point.risk_level or "")),
        ("데이터 소스", "DC Power Flow + route stress" if "stress_node_risk_level" in metadata else str(point.source)),
    ]
    return _popup_table_html(point.label, rows)


def line_popup_html_for_overlay_line(line: MapOverlayLine) -> str:
    metadata = line.metadata
    rows = [
        ("객체", "선로"),
        ("선로 ID", line_id_from_overlay_line(line)),
        ("구간", line.label),
        ("전압", _format_kv(metadata.get("voltage_kv"))),
        ("용량", _format_mw(_first_present(metadata, "stress_capacity_mw", "capacity_mw"))),
        ("기본 흐름", _format_mw(metadata.get("stress_base_flow_mw"))),
        ("시나리오 추가 흐름", _format_mw(metadata.get("stress_scenario_flow_mw"))),
        ("예측 추가 흐름", _format_mw(metadata.get("stress_predicted_flow_mw"))),
        ("누적 총 흐름", _format_mw(metadata.get("stress_total_flow_mw"))),
        ("누적 이용률", _format_percent(metadata.get("stress_utilization"))),
        ("상태", _metadata_text(metadata, "stress_status", line.status)),
        ("위험도", _metadata_text(metadata, "stress_risk_level", line.risk_level or "")),
        ("공유 시나리오 수", _metadata_text(metadata, "stress_shared_route_count")),
        ("기여 시나리오", _format_list(metadata.get("contributing_scenario_ids"))),
        ("용량 여유", _format_mw(metadata.get("stress_capacity_margin_mw"))),
    ]
    return _popup_table_html(
        line.label,
        rows,
        extra_html=(
            _xai_popup_section_html(metadata)
            + _improvement_popup_section_html(metadata)
        ),
    )


def _popup_table_html(
    title: str,
    rows: list[tuple[str, object]],
    *,
    extra_html: str = "",
) -> str:
    visible_rows = [
        (label, _stringify_popup_value(value))
        for label, value in rows
        if _stringify_popup_value(value)
    ]
    row_html = "".join(
        "<tr>"
        '<th style="border-top:1px solid #e5e7eb;color:#475569;'
        'font-weight:600;min-width:104px;padding:5px 10px 5px 0;'
        'text-align:left;vertical-align:top;white-space:nowrap;word-break:keep-all;">'
        f"{escape(label)}</th>"
        '<td style="border-top:1px solid #e5e7eb;color:#111827;'
        'padding:5px 0;text-align:left;vertical-align:top;'
        'white-space:normal;word-break:normal;overflow-wrap:anywhere;">'
        f"{escape(value)}</td>"
        "</tr>"
        for label, value in visible_rows
    )
    return (
        '<div style="min-width:380px;max-width:520px;max-height:360px;overflow:auto;'
        'font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;'
        'font-size:13px;line-height:1.35;">'
        f'<div style="font-weight:700;font-size:15px;margin:0 0 8px;white-space:nowrap;">{escape(title)}</div>'
        '<table style="border-collapse:collapse;table-layout:auto;width:100%;">'
        f"{row_html}"
        "</table>"
        f"{extra_html}"
        "</div>"
    )


def _xai_popup_section_html(metadata: dict[str, object]) -> str:
    reason_summary = _metadata_text(metadata, "xai_reason_summary")
    causes = _format_list_items(metadata.get("xai_bottleneck_causes"))
    actions = _format_list_items(metadata.get("xai_recommended_actions"))
    if not reason_summary and not causes and not actions:
        return ""

    after_metrics = metadata.get("xai_after_metrics")
    before_metrics = metadata.get("xai_before_metrics")
    current_utilization = ""
    estimated_utilization = ""
    estimated_rerouted_mw = ""
    if isinstance(before_metrics, dict):
        current_utilization = _format_percent(before_metrics.get("utilization"))
    if isinstance(after_metrics, dict):
        estimated_utilization = _format_percent(after_metrics.get("estimated_utilization"))
        estimated_rerouted_mw = _format_mw(after_metrics.get("estimated_rerouted_mw"))

    metric_rows = [
        ("현재 이용률", current_utilization),
        ("개선 후 추정 이용률", estimated_utilization),
        ("예상 분산량", estimated_rerouted_mw),
    ]
    metrics_html = "".join(
        "<tr>"
        '<th style="color:#475569;font-weight:600;padding:3px 8px 3px 0;'
        'text-align:left;white-space:nowrap;">'
        f"{escape(label)}</th>"
        '<td style="color:#111827;padding:3px 0;overflow-wrap:anywhere;">'
        f"{escape(value)}</td>"
        "</tr>"
        for label, value in metric_rows
        if value
    )

    return (
        '<div style="border-top:1px solid #cbd5e1;margin-top:10px;padding-top:9px;">'
        '<div style="font-weight:700;color:#0f172a;margin-bottom:5px;">xAI 설명</div>'
        f'<div style="color:#111827;margin-bottom:7px;">{escape(reason_summary)}</div>'
        f"{_list_section_html('주요 원인', causes)}"
        f"{_list_section_html('권장 조치', actions)}"
        '<table style="border-collapse:collapse;width:100%;margin-top:5px;">'
        f"{metrics_html}"
        "</table>"
        "</div>"
    )


def _improvement_popup_section_html(metadata: dict[str, object]) -> str:
    summary = _metadata_text(metadata, "improvement_summary")
    if not summary:
        return ""

    before_utilization = _format_percent(metadata.get("improvement_best_before_utilization"))
    after_utilization = _format_percent(metadata.get("improvement_best_after_utilization"))
    added_distance = _format_km(metadata.get("improvement_best_added_distance_km"))
    score = _metadata_text(metadata, "improvement_best_score")
    suggested_node = _metadata_text(metadata, "improvement_suggested_node_label")
    suggested_capacity = _format_mw(metadata.get("improvement_suggested_node_capacity_mw"))
    suggested_cost = _format_cost_billion(metadata.get("improvement_suggested_node_cost_billion"))
    rationale = _metadata_text(metadata, "improvement_best_rationale")
    node_reason = _metadata_text(metadata, "improvement_suggested_node_reason")

    metric_rows = [
        ("적용 전 이용률", before_utilization),
        ("적용 후 이용률", after_utilization),
        ("추가 거리", added_distance),
        ("개선 점수", score),
        ("신규 후보", suggested_node),
        ("권장 용량", suggested_capacity),
        ("예상 비용", suggested_cost),
    ]
    metrics_html = "".join(
        "<tr>"
        '<th style="color:#475569;font-weight:600;padding:3px 8px 3px 0;'
        'text-align:left;white-space:nowrap;">'
        f"{escape(label)}</th>"
        '<td style="color:#111827;padding:3px 0;overflow-wrap:anywhere;">'
        f"{escape(value)}</td>"
        "</tr>"
        for label, value in metric_rows
        if value
    )
    rationale_html = (
        f'<div style="color:#111827;margin-top:6px;">{escape(rationale)}</div>'
        if rationale
        else ""
    )
    node_reason_html = (
        f'<div style="color:#111827;margin-top:6px;">{escape(node_reason)}</div>'
        if node_reason
        else ""
    )

    return (
        '<div style="border-top:1px solid #cbd5e1;margin-top:10px;padding-top:9px;">'
        '<div style="font-weight:700;color:#0f172a;margin-bottom:5px;">개선안 제안</div>'
        f'<div style="color:#111827;margin-bottom:7px;">{escape(summary)}</div>'
        f"{rationale_html}"
        f"{node_reason_html}"
        '<table style="border-collapse:collapse;width:100%;margin-top:5px;">'
        f"{metrics_html}"
        "</table>"
        "</div>"
    )


def _list_section_html(
    title: str,
    values: list[str],
) -> str:
    if not values:
        return ""
    item_html = "".join(f"<li>{escape(value)}</li>" for value in values)
    return (
        f'<div style="font-weight:600;color:#334155;margin:6px 0 2px;">{escape(title)}</div>'
        '<ul style="margin:0 0 4px 1rem;padding:0;color:#111827;">'
        f"{item_html}"
        "</ul>"
    )


def _stringify_popup_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple, set)):
        return _format_list(value)
    return str(value)


def _metadata_text(
    metadata: dict[str, object],
    key: str,
    fallback: object = "",
) -> str:
    value = metadata.get(key, fallback)
    return _stringify_popup_value(value)


def _first_present(
    metadata: dict[str, object],
    *keys: str,
) -> object:
    for key in keys:
        value = metadata.get(key)
        if value is not None and value != "":
            return value
    return None


def _format_mw(value: object) -> str:
    number = _coerce_float(value)
    return f"{number:.2f} MW" if number is not None else ""


def _format_kv(value: object) -> str:
    number = _coerce_float(value)
    return f"{number:.1f} kV" if number is not None else ""


def _format_km(value: object) -> str:
    number = _coerce_float(value)
    return f"{number:.2f} km" if number is not None else ""


def _format_percent(value: object) -> str:
    number = _coerce_float(value)
    return f"{number:.1%}" if number is not None else ""


def _format_cost_billion(value: object) -> str:
    number = _coerce_float(value)
    return f"{number:.2f}십억" if number is not None else ""


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _format_list(value: object) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if str(item))
    if isinstance(value, str):
        return value
    return ""


def _format_list_items(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _kind_label(kind: str) -> str:
    labels = {
        "power_plant": "발전소",
        "transmission_tower": "송전탑",
        "tower_candidate": "후보지",
        "route_point": "경로점",
        "install_point": "설치 지점",
        "start_point": "시작점",
        "end_point": "종료점",
        "bus": "버스",
        "line": "선로",
        "risk_line": "위험 선로",
        "route": "경로",
    }
    return labels.get(kind, kind)
