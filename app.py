# Streamlit 기반 SGOP 애플리케이션의 진입점이다.
from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from src.config.settings import settings
from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.schemas import (
    InstallationMode,
    InstallationPoint,
    InstallationTargetKind,
    MapOverlayPoint,
    MapOverlayResult,
    ScenarioContext,
)
from src.services.map_overlay_service import MapOverlayService
from src.ui.map_overlay_renderer import overlay_warnings_for_display, render_map_overlay
from src.ui.scenario_controls import render_scenario_sidebar


_TARGET_KIND_BY_LABEL: dict[str, InstallationTargetKind] = {
    "발전소": "power_plant",
    "송전탑": "transmission_tower",
}

_TARGET_DEFAULT_NAME: dict[InstallationTargetKind, str] = {
    "power_plant": "신규 발전소",
    "transmission_tower": "신규 송전탑",
    "start_point": "시작점",
    "end_point": "종료점",
}

_INSTALLATION_MODE_BY_LABEL: dict[str, InstallationMode] = {
    "신규": "new",
    "교체": "replace",
    "검토": "review",
}

_INSTALLATION_MODE_LABEL: dict[InstallationMode, str] = {
    "new": "신규",
    "replace": "교체",
    "review": "검토",
}

def main() -> None:
    st.set_page_config(
        page_title="SGOP",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_landing_state()

    scenario = render_scenario_sidebar()
    map_capability = get_map_capability(prefer_webgl=False)
    st.session_state.sgop_landing_has_vworld_tiles = bool(map_capability.wmts_tile_url)
    service_overlay, overlay_warning = _get_service_overlay(scenario, map_capability)

    selected_kind, mode, name, capacity_mw, voltage_kv, notes = _render_left_panel()
    selected_point = st.session_state.get("sgop_landing_last_click")

    if st.session_state.get("sgop_landing_add_requested"):
        st.session_state.sgop_landing_add_requested = False
        if isinstance(selected_point, MapOverlayPoint):
            installation = _build_installation_point(
                selected_point=selected_point,
                kind=selected_kind,
                label=name,
                mode=mode,
                capacity_mw=capacity_mw,
                voltage_kv=voltage_kv,
                notes=notes,
            )
            st.session_state.sgop_landing_installations.append(installation)
            st.session_state.sgop_landing_last_click = None
        else:
            st.sidebar.warning("지도에서 설치 지점을 먼저 선택하세요.")

    st.title("SGOP 운영 지도")
    st.caption(
        f"시나리오: {scenario.scenario_id}  |  "
        f"지도 모드: {map_capability.rendering_mode}  |  "
        f"실행 환경: {settings.sgop_env}"
    )

    if map_capability.fallback.enabled:
        st.caption(f"Fallback: `{map_capability.fallback.mode}`")

    summary_cols = st.columns(4)
    summary_cols[0].metric("설치 지점", f"{len(st.session_state.sgop_landing_installations)}개")
    summary_cols[1].metric("발전소", f"{_count_installations('power_plant')}개")
    summary_cols[2].metric("송전탑", f"{_count_installations('transmission_tower')}개")
    summary_cols[3].metric("좌표계", "EPSG:4326")

    overlay_points = _build_landing_points(service_overlay)
    overlay_routes = service_overlay.routes if service_overlay is not None else []
    landing_overlay = MapOverlayService().build_landing_overlay(
        scenario=scenario,
        created_at=scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0),
        points=overlay_points,
        routes=overlay_routes,
        warnings=[overlay_warning] if overlay_warning else [],
        map_capability=map_capability,
    )

    map_data = render_map_overlay(
        landing_overlay,
        map_capability=map_capability,
        height=650,
        show_point_table=True,
        return_map_data=True,
    )
    clicked_point = _extract_clicked_point(map_data)
    if clicked_point is not None:
        st.session_state.sgop_landing_last_click = clicked_point

    st.caption(landing_overlay.summary)
    st.caption(
        f"지도 모드: {landing_overlay.metadata.get('rendering_mode')}  |  "
        f"좌표계: {landing_overlay.metadata.get('coordinate_system')}  |  "
        f"고도: {landing_overlay.metadata.get('elevation_source')}"
    )
    overlay_extra_warnings = overlay_warnings_for_display([], landing_overlay.warnings)
    if overlay_extra_warnings:
        with st.expander("지도 fallback 및 좌표 메타데이터", expanded=False):
            if landing_overlay.fallback.enabled:
                st.caption(
                    f"Fallback: `{landing_overlay.fallback.mode}`  |  "
                    f"{landing_overlay.fallback.reason}"
                )
            for warning in overlay_extra_warnings:
                st.caption(f"- {warning}")

    _render_selected_point()
    _render_installation_table()


def _init_landing_state() -> None:
    if "sgop_landing_installations" not in st.session_state:
        st.session_state.sgop_landing_installations = []
    if "sgop_landing_last_click" not in st.session_state:
        st.session_state.sgop_landing_last_click = None
    if "sgop_landing_add_requested" not in st.session_state:
        st.session_state.sgop_landing_add_requested = False


def _render_left_panel() -> tuple[
    InstallationTargetKind,
    InstallationMode,
    str,
    float | None,
    float | None,
    str,
]:
    with st.sidebar:
        st.header("설치 패널")
        selected_label = st.radio(
            "설치 대상",
            options=list(_TARGET_KIND_BY_LABEL.keys()),
            horizontal=True,
        )
        selected_kind = _TARGET_KIND_BY_LABEL[selected_label]

        selected_mode_label = st.radio(
            "설치 모드",
            options=list(_INSTALLATION_MODE_BY_LABEL.keys()),
            horizontal=True,
        )
        mode = _INSTALLATION_MODE_BY_LABEL[selected_mode_label]
        default_name = _TARGET_DEFAULT_NAME[selected_kind]
        name = st.text_input("이름", value=f"{default_name} {len(st.session_state.sgop_landing_installations) + 1}")

        capacity_mw: float | None = None
        voltage_kv: float | None = None
        if selected_kind == "power_plant":
            capacity_mw = st.number_input(
                "용량 (MW)",
                min_value=0.0,
                max_value=10000.0,
                value=500.0,
                step=50.0,
            )
        else:
            voltage_kv = st.number_input(
                "전압 (kV)",
                min_value=0.0,
                max_value=765.0,
                value=345.0,
                step=5.0,
            )

        notes = st.text_area("메모", value="", height=90)

        selected_point = st.session_state.get("sgop_landing_last_click")
        if isinstance(selected_point, MapOverlayPoint):
            st.divider()
            st.metric("x", f"{selected_point.longitude:.6f}")
            st.metric("y", f"{selected_point.latitude:.6f}")

        if st.button("설치 지점 추가", type="primary", use_container_width=True):
            st.session_state.sgop_landing_add_requested = True

        if st.button("설치 목록 초기화", use_container_width=True):
            st.session_state.sgop_landing_installations = []
            st.session_state.sgop_landing_last_click = None
            st.rerun()

        with st.expander("연결 상태", expanded=False):
            st.write(
                {
                    "VWORLD_API_KEY": bool(settings.vworld_api_key),
                    "PUBLIC_DATA_API_KEY": bool(settings.public_data_api_key),
                    "OPENAI_API_KEY": bool(settings.openai_api_key),
                    "map_mode": "2.5D",
                    "vworld_tiles": bool(getattr(st.session_state, "sgop_landing_has_vworld_tiles", False)),
                    "install_mode": _INSTALLATION_MODE_LABEL[mode],
                }
            )

        return selected_kind, mode, name.strip() or default_name, capacity_mw, voltage_kv, notes.strip()


def _get_service_overlay(
    scenario: ScenarioContext,
    map_capability: MapCapability,
) -> tuple[MapOverlayResult | None, str]:
    cache_key = (
        scenario.scenario_id,
        scenario.created_at.isoformat() if scenario.created_at is not None else "",
        map_capability.rendering_mode,
        map_capability.vworld_available,
    )
    cached = st.session_state.get("sgop_landing_service_overlay")
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        return cached[1], cached[2]

    try:
        from src.services.map_overlay_service import MapOverlayService
        from src.services.simulation_service import SimulationService

        service = SimulationService()
        created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
        simulation_input = service.build_default_input(
            scenario=scenario,
            created_at=created_at,
        )
        simulation_result = service.run_simulation(
            simulation_input,
            created_at=created_at,
        )
        overlay = MapOverlayService().build_simulation_overlay(
            simulation_result,
            map_capability=map_capability,
        )
        st.session_state.sgop_landing_service_overlay = (cache_key, overlay, "")
        return overlay, ""
    except Exception as exc:  # noqa: BLE001
        warning = f"Simulation overlay를 만들지 못해 기본 지도 지점만 표시합니다. 원인: {exc}"
        st.session_state.sgop_landing_service_overlay = (cache_key, None, warning)
        return None, warning


def _build_landing_points(service_overlay: MapOverlayResult | None) -> list[MapOverlayPoint]:
    points = _build_mock_grid_points()
    if service_overlay is not None:
        points.extend(service_overlay.points)
    points.extend(
        _installation_to_overlay_point(installation)
        for installation in st.session_state.sgop_landing_installations
    )
    return _dedupe_points(points)


def _build_mock_grid_points() -> list[MapOverlayPoint]:
    return [
        MapOverlayPoint(
            overlay_id="plant:ulsan",
            label="울산 발전소",
            kind="power_plant",
            latitude=35.5384,
            longitude=129.3114,
            elevation_m=None,
            elevation_source="not_queried",
            status="normal",
            source="manual",
            metadata={"asset_type": "power_plant", "capacity_mw": 2400.0},
        ),
        MapOverlayPoint(
            overlay_id="plant:incheon",
            label="인천 발전소",
            kind="power_plant",
            latitude=37.4563,
            longitude=126.7052,
            elevation_m=None,
            elevation_source="not_queried",
            status="normal",
            source="manual",
            metadata={"asset_type": "power_plant", "capacity_mw": 1800.0},
        ),
        MapOverlayPoint(
            overlay_id="tower:gapyeong",
            label="신가평 송전탑",
            kind="transmission_tower",
            latitude=37.8350,
            longitude=127.5110,
            elevation_m=None,
            elevation_source="not_queried",
            status="normal",
            source="manual",
            metadata={"asset_type": "transmission_tower", "voltage_kv": 345.0},
        ),
        MapOverlayPoint(
            overlay_id="tower:daejeon",
            label="대전 송전탑",
            kind="transmission_tower",
            latitude=36.3504,
            longitude=127.3845,
            elevation_m=None,
            elevation_source="not_queried",
            status="warning",
            source="manual",
            metadata={"asset_type": "transmission_tower", "voltage_kv": 345.0},
        ),
        MapOverlayPoint(
            overlay_id="bus:seoul",
            label="서울 버스",
            kind="bus",
            latitude=37.5665,
            longitude=126.9780,
            elevation_m=None,
            elevation_source="not_queried",
            status="normal",
            source="manual",
            metadata={"bus_id": "BUS_001"},
        ),
        MapOverlayPoint(
            overlay_id="bus:daegu",
            label="대구 버스",
            kind="bus",
            latitude=35.8714,
            longitude=128.6014,
            elevation_m=None,
            elevation_source="not_queried",
            status="normal",
            source="manual",
            metadata={"bus_id": "BUS_011"},
        ),
    ]


def _extract_clicked_point(map_data: dict[str, Any] | None) -> MapOverlayPoint | None:
    if not isinstance(map_data, dict):
        return None
    clicked = map_data.get("last_clicked")
    if not isinstance(clicked, dict):
        return None
    latitude = clicked.get("lat")
    longitude = clicked.get("lng")
    if latitude is None or longitude is None:
        return None

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None

    return MapOverlayPoint(
        overlay_id="map-click:last",
        label="선택 지점",
        kind="install_point",
        latitude=lat,
        longitude=lon,
        elevation_m=None,
        coordinate_system="EPSG:4326",
        elevation_source="not_queried",
        status="selected",
        source="manual",
        metadata={"capture_source": "folium_click"},
    )


def _build_installation_point(
    *,
    selected_point: MapOverlayPoint,
    kind: InstallationTargetKind,
    label: str,
    mode: InstallationMode,
    capacity_mw: float | None,
    voltage_kv: float | None,
    notes: str,
) -> InstallationPoint:
    created_at = datetime.now().replace(microsecond=0)
    sequence = len(st.session_state.sgop_landing_installations) + 1
    return InstallationPoint(
        installation_id=f"{kind}-{created_at:%Y%m%d%H%M%S}-{sequence}",
        label=label,
        kind=kind,
        latitude=selected_point.latitude,
        longitude=selected_point.longitude,
        mode=mode,
        elevation_m=None,
        coordinate_system="EPSG:4326",
        elevation_source="not_queried",
        capacity_mw=capacity_mw if kind == "power_plant" else None,
        voltage_kv=voltage_kv if kind == "transmission_tower" else None,
        notes=notes,
        created_at=created_at,
        metadata={
            "source_overlay_id": selected_point.overlay_id,
            "coordinate_status": "xy_only",
        },
    )


def _installation_to_overlay_point(installation: InstallationPoint) -> MapOverlayPoint:
    return MapOverlayPoint(
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
        metadata={
            "installation_id": installation.installation_id,
            "capacity_mw": installation.capacity_mw,
            "voltage_kv": installation.voltage_kv,
            "notes": installation.notes,
        },
    )


def _render_selected_point() -> None:
    selected_point = st.session_state.get("sgop_landing_last_click")
    if not isinstance(selected_point, MapOverlayPoint):
        return

    st.subheader("최근 선택 지점")
    cols = st.columns(2)
    cols[0].metric("x", f"{selected_point.longitude:.6f}")
    cols[1].metric("y", f"{selected_point.latitude:.6f}")


def _render_installation_table() -> None:
    installations: list[InstallationPoint] = st.session_state.sgop_landing_installations
    st.subheader("설치 목록")
    if not installations:
        st.info("저장된 설치 지점이 없습니다.")
        return

    rows = []
    for item in installations:
        rows.append(
            {
                "유형": _kind_label(item.kind),
                "모드": _INSTALLATION_MODE_LABEL[item.mode],
                "이름": item.label,
                "x": round(item.longitude, 6),
                "y": round(item.latitude, 6),
                "용량 (MW)": item.capacity_mw,
                "전압 (kV)": item.voltage_kv,
                "메모": item.notes,
                "생성 시각": item.created_at.isoformat() if item.created_at is not None else "",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


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


def _count_installations(kind: InstallationTargetKind) -> int:
    return sum(
        1
        for installation in st.session_state.sgop_landing_installations
        if installation.kind == kind
    )


def _dedupe_points(points: list[MapOverlayPoint]) -> list[MapOverlayPoint]:
    deduped: dict[str, MapOverlayPoint] = {}
    for point in points:
        deduped[point.overlay_id] = point
    return list(deduped.values())


if __name__ == "__main__":
    main()
