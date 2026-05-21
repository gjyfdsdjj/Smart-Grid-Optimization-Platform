# MapOverlayResult를 Streamlit/Folium 지도 또는 표 fallback으로 렌더링한다.
from __future__ import annotations

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
    "warning": "#eab308",
    "critical": "#ef4444",
    "overload": "#8b5cf6",
    "unknown": "#94a3b8",
    "selected": "#7c3aed",
}


def render_map_overlay(
    overlay: MapOverlayResult,
    *,
    map_capability: MapCapability,
    selected_line_id: str | None = None,
    height: int = 620,
    width: int = 1200,
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

    for line in overlay.lines:
        _add_overlay_line(
            folium,
            folium_map,
            line,
            selected=line_id_from_overlay_line(line) == selected_line_id,
        )
    for route in overlay.routes:
        _add_overlay_route(folium, folium_map, route)
    for point in overlay.points:
        _add_overlay_point(folium, folium_map, point)

    folium.LayerControl(collapsed=True).add_to(folium_map)
    returned_objects = ["last_clicked"] if return_map_data else []
    map_data = st_folium(
        folium_map,
        width=width,
        height=height,
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


def _add_overlay_line(
    folium: Any,
    folium_map: Any,
    line: MapOverlayLine,
    *,
    selected: bool,
) -> None:
    style = line_style_for_status(line.status, selected=selected)
    line_id = line_id_from_overlay_line(line)
    folium.PolyLine(
        locations=[
            [line.from_point.latitude, line.from_point.longitude],
            [line.to_point.latitude, line.to_point.longitude],
        ],
        color=style["color"],
        weight=style["weight"],
        opacity=style["opacity"],
        tooltip=f"{line_id} | {line.label} | {line.status}",
    ).add_to(folium_map)


def _add_overlay_route(folium: Any, folium_map: Any, route: MapOverlayRoute) -> None:
    route_coords = [[point.latitude, point.longitude] for point in route.points]
    if len(route_coords) < 2:
        return

    folium.PolyLine(
        locations=route_coords,
        color="#2563eb" if route.rank == 1 else "#64748b",
        weight=5 if route.rank == 1 else 3,
        dash_array="10" if route.rank == 1 else None,
        tooltip=route.label,
        opacity=0.9 if route.rank == 1 else 0.45,
    ).add_to(folium_map)


def _add_overlay_point(folium: Any, folium_map: Any, point: MapOverlayPoint) -> None:
    style = point_style_for_overlay_point(point)
    folium.CircleMarker(
        location=[point.latitude, point.longitude],
        radius=style["radius"],
        popup=_point_popup_html(point),
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
    if point.kind == "tower_candidate":
        return {"color": "#047857", "fill_color": "#34d399", "fill_opacity": 0.9, "radius": 7, "weight": 2}
    if point.kind == "route_point":
        return {"color": "#2563eb", "fill_color": "#ffffff", "fill_opacity": 1.0, "radius": 5, "weight": 2}
    if point.kind == "power_plant":
        return {"color": "#b91c1c", "fill_color": "#ef4444", "fill_opacity": 0.9, "radius": 8, "weight": 2}
    if point.kind == "transmission_tower":
        return {"color": "#1d4ed8", "fill_color": "#60a5fa", "fill_opacity": 0.9, "radius": 7, "weight": 2}
    return {"color": "#334155", "fill_color": "#cbd5e1", "fill_opacity": 0.85, "radius": 5, "weight": 2}


def _point_popup_html(point: MapOverlayPoint) -> str:
    return (
        f"<strong>{point.label}</strong><br>"
        f"x: {point.longitude:.6f}<br>"
        f"y: {point.latitude:.6f}<br>"
        f"kind: {point.kind}"
    )
