# Streamlit 기반 SGOP 애플리케이션의 진입점이다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import streamlit as st

from src.config.settings import settings
from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.loaders import load_grid_dataset_or_default
from src.data.schemas import (
    InstallationMode,
    InstallationPoint,
    InstallationTargetKind,
    LineStatus,
    MapOverlayLine,
    MapOverlayPoint,
    MapOverlayResult,
    MapOverlayRoute,
    MonitoringResult,
    ScenarioContext,
    StressAnalysisResult,
    TransmissionScenario,
    TransmissionScenarioStatus,
)
from src.engine.stress.route_stress_analyzer import analyze_route_stress
from src.services.map_overlay_service import MapOverlayService
from src.services.geo_place_service import GeoPlaceService
from src.services.monitoring_service import MonitoringService
from src.services.transmission_scenario_service import (
    DEFAULT_TRANSFER_MW,
    TransmissionScenarioService,
)
from src.ui.map_overlay_renderer import render_map_overlay
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

_LANDING_TARGET_STATE_KEY = "sgop_landing_target_label"
_LANDING_NAME_STATE_KEY = "sgop_landing_install_name"
_LANDING_AUTO_NAME_STATE_KEY = "sgop_landing_auto_install_name"
_LANDING_AUTO_KIND_STATE_KEY = "sgop_landing_auto_install_kind"
_LANDING_PENDING_NAME_STATE_KEY = "sgop_landing_pending_install_name"
_LANDING_PENDING_KIND_STATE_KEY = "sgop_landing_pending_install_kind"
_LANDING_MAP_HEIGHT_PX = 860
LANDING_INTERACTION_MODE_STATE_KEY = "sgop_landing_interaction_mode"
GLOBAL_LOAD_SCALE_STATE_KEY = "sgop_global_load_scale"
TRANSMISSION_SCENARIOS_STATE_KEY = "sgop_transmission_scenarios"
TRANSMISSION_SELECTION_STEP_STATE_KEY = "sgop_transmission_selection_step"
TRANSMISSION_START_NODE_ID_STATE_KEY = "sgop_transmission_start_node_id"
TRANSMISSION_START_NODE_LABEL_STATE_KEY = "sgop_transmission_start_node_label"
TRANSMISSION_END_NODE_ID_STATE_KEY = "sgop_transmission_end_node_id"
TRANSMISSION_END_NODE_LABEL_STATE_KEY = "sgop_transmission_end_node_label"
TRANSMISSION_SELECTION_WARNING_STATE_KEY = "sgop_transmission_selection_warning"
TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY = "sgop_transmission_last_click_signature"
TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY = "sgop_transmission_requested_transfer_mw"
TRANSMISSION_CREATE_REQUESTED_STATE_KEY = "sgop_transmission_create_requested"
TRANSMISSION_NEXT_INDEX_STATE_KEY = "sgop_transmission_next_index"
STRESS_ANALYSIS_STATE_KEY = "sgop_stress_analysis_result"
_STRESS_ANALYSIS_CACHE_STATE_KEY = "sgop_stress_analysis_cache"
MONITORING_RESULT_STATE_KEY = "sgop_monitoring_result"
_MONITORING_CACHE_STATE_KEY = "sgop_monitoring_result_cache"
SELECTED_GRID_OBJECT_STATE_KEY = "sgop_selected_grid_object"
_INTERACTION_MODE_LABEL: dict[str, str] = {
    "install": "설치",
    "transmission": "송전 시나리오",
}
_TRANSMISSION_STEP_LABEL: dict[str, str] = {
    "start": "시작 노드",
    "end": "종료 노드",
    "ready": "선택 완료",
}
_TRANSMISSION_SCENARIO_COLORS: tuple[str, ...] = (
    "#dc2626",
    "#2563eb",
    "#059669",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#4f46e5",
)
_TRANSMISSION_NODE_CLICK_THRESHOLD_KM = 5.0
_TRANSMISSION_SELECTABLE_KINDS = {"power_plant", "transmission_tower"}
_STRESS_STATUS_FILTERS: tuple[str, ...] = (
    "전체",
    "정상",
    "경고",
    "위험",
    "과부하",
    "병목만",
)
_STRESS_STATUS_BY_FILTER: dict[str, set[str]] = {
    "정상": {"normal"},
    "경고": {"warning"},
    "위험": {"critical"},
    "과부하": {"overload"},
}

_DEFAULT_POWER_PLANTS: tuple[dict[str, float | str], ...] = (
    {"id": "incheon", "label": "인천 발전소", "latitude": 37.4563, "longitude": 126.7052, "capacity_mw": 1800.0},
    {"id": "gwangju", "label": "광주 발전소", "latitude": 35.1595, "longitude": 126.8526, "capacity_mw": 1200.0},
    {"id": "sokcho", "label": "속초 발전소", "latitude": 38.2070, "longitude": 128.5918, "capacity_mw": 700.0},
    {"id": "busan", "label": "부산 발전소", "latitude": 35.1796, "longitude": 129.0756, "capacity_mw": 1600.0},
    {"id": "ulsan", "label": "울산 발전소", "latitude": 35.5384, "longitude": 129.3114, "capacity_mw": 2400.0},
    {"id": "pohang", "label": "포항 발전소", "latitude": 36.0190, "longitude": 129.3435, "capacity_mw": 1100.0},
)

_DEFAULT_TRANSMISSION_TOWERS: tuple[dict[str, float | str], ...] = (
    {"id": "geochang", "label": "거창 송전탑", "latitude": 35.6867, "longitude": 127.9095},
    {"id": "seoul", "label": "서울 송전탑", "latitude": 37.5665, "longitude": 126.9780},
    {"id": "gangneung", "label": "강릉 송전탑", "latitude": 37.7519, "longitude": 128.8761},
    {"id": "daejeon", "label": "대전 송전탑", "latitude": 36.3504, "longitude": 127.3845},
    {"id": "chuncheon", "label": "춘천 송전탑", "latitude": 37.8813, "longitude": 127.7298},
    {"id": "jeju", "label": "제주도 송전탑", "latitude": 33.4996, "longitude": 126.5312},
    {"id": "gumi", "label": "구미 송전탑", "latitude": 36.1195, "longitude": 128.3446},
    {"id": "daegu", "label": "대구 송전탑", "latitude": 35.8714, "longitude": 128.6014},
    {"id": "changwon", "label": "창원 송전탑", "latitude": 35.2279, "longitude": 128.6811},
    {"id": "yeongcheon", "label": "영천 송전탑", "latitude": 35.9733, "longitude": 128.9388},
    {"id": "sangju", "label": "상주 송전탑", "latitude": 36.4109, "longitude": 128.1591},
    {"id": "haenam", "label": "해남 송전탑", "latitude": 34.5733, "longitude": 126.5993},
)

def main() -> None:
    st.set_page_config(
        page_title="SGOP",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _apply_landing_fullscreen_style()
    _init_landing_state()

    scenario = render_scenario_sidebar()
    map_capability = get_map_capability(prefer_webgl=False)
    st.session_state.sgop_landing_has_vworld_tiles = bool(map_capability.wmts_tile_url)

    interaction_mode, selected_kind, mode, name, capacity_mw, voltage_kv, notes = _render_left_panel()
    global_load_scale = _get_global_load_scale()
    selected_point = st.session_state.get("sgop_landing_last_click")

    if interaction_mode == "install" and st.session_state.get("sgop_landing_add_requested"):
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
            _queue_installation_name_reset(selected_kind)
            st.rerun()
        else:
            st.sidebar.warning("지도에서 설치 지점을 먼저 선택하세요.")
    elif st.session_state.get("sgop_landing_add_requested"):
        st.session_state.sgop_landing_add_requested = False

    if interaction_mode == "transmission" and st.session_state.get(TRANSMISSION_CREATE_REQUESTED_STATE_KEY):
        st.session_state[TRANSMISSION_CREATE_REQUESTED_STATE_KEY] = False
        _create_transmission_scenario_from_selection(
            scenario,
            load_scale=global_load_scale,
        )
        st.rerun()

    _render_landing_map_header(scenario, map_capability)

    monitoring_result, monitoring_warning = _get_landing_monitoring_result(
        scenario,
        load_scale=global_load_scale,
    )
    stress_analysis, stress_warning = _get_landing_stress_analysis(
        scenario,
        load_scale=global_load_scale,
        monitoring_result=monitoring_result,
    )
    with st.sidebar:
        st.divider()
        _render_stress_summary_panel(stress_analysis)
    grid_overlay, grid_warning = _get_grid_overlay(
        scenario,
        map_capability,
        load_scale=global_load_scale,
    )
    service_overlay, overlay_warning = _get_service_overlay(
        scenario,
        map_capability,
        load_scale=global_load_scale,
    )
    overlay_points = _attach_node_stress_metadata(
        _build_landing_points(grid_overlay, service_overlay),
        stress_analysis,
    )
    overlay_lines = _attach_stress_metadata(
        grid_overlay.lines if grid_overlay is not None else [],
        stress_analysis,
    )
    overlay_routes = (
        _build_landing_routes(service_overlay)
        + _build_transmission_scenario_routes(_landing_transmission_scenarios())
    )
    landing_overlay = MapOverlayService().build_landing_overlay(
        scenario=scenario,
        created_at=scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0),
        points=overlay_points,
        lines=overlay_lines,
        routes=overlay_routes,
        warnings=[
            warning
            for warning in [grid_warning, overlay_warning, monitoring_warning, stress_warning]
            if warning
        ],
        map_capability=map_capability,
    )

    selected_line_id = _selected_grid_object_line_id()
    map_data = render_map_overlay(
        landing_overlay,
        map_capability=map_capability,
        selected_line_id=selected_line_id,
        height=_LANDING_MAP_HEIGHT_PX,
        width=None,
        show_point_table=True,
        return_map_data=True,
    )
    clicked_point = _extract_clicked_point(map_data)
    if clicked_point is not None:
        clicked_object = _extract_clicked_grid_object(
            clicked_point,
            overlay_points=overlay_points,
            overlay_lines=overlay_lines,
        )
        if interaction_mode == "transmission":
            if _should_process_transmission_click(clicked_point):
                if clicked_object is not None and clicked_object.get("type") == "line":
                    if _store_selected_grid_object(clicked_object):
                        st.rerun()
                else:
                    clicked_node = _find_clicked_grid_node(clicked_point, overlay_points)
                    if clicked_node is None:
                        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
                            "선택 가능한 발전소 또는 송전탑 노드가 아닙니다."
                        )
                        st.rerun()
                    elif _store_transmission_node_selection(clicked_node):
                        _store_selected_grid_object(_grid_object_from_node_point(clicked_node))
                        st.rerun()
        elif clicked_object is not None:
            if _store_selected_grid_object(clicked_object):
                st.rerun()
        elif _store_last_clicked_point(clicked_point, selected_kind):
            st.rerun()

    _render_selected_grid_object_detail(
        stress_analysis=stress_analysis,
        monitoring_result=monitoring_result,
        overlay_points=overlay_points,
        overlay_lines=overlay_lines,
    )
    _render_stress_detail_panel(stress_analysis)
    _render_installation_table()


def _apply_landing_fullscreen_style() -> None:
    st.markdown(
        """
        <style>
            div[data-testid="stAppViewContainer"] .main .block-container {
                max-width: 100%;
                padding: 0.45rem 0.65rem 0.6rem;
            }
            .sgop-landing-header {
                align-items: center;
                border-bottom: 1px solid rgba(15, 23, 42, 0.12);
                display: flex;
                gap: 0.8rem;
                justify-content: space-between;
                min-height: 2.6rem;
                padding: 0.15rem 0.1rem 0.45rem;
            }
            .sgop-landing-title {
                color: #0f172a;
                font-size: 1.18rem;
                font-weight: 700;
                line-height: 1.15;
                white-space: nowrap;
            }
            .sgop-landing-status {
                color: #475569;
                display: flex;
                flex-wrap: wrap;
                font-size: 0.82rem;
                gap: 0.75rem;
                justify-content: flex-end;
            }
            div[data-testid="stIFrame"] {
                height: calc(100vh - 5.4rem) !important;
                min-height: 720px;
            }
            div[data-testid="stIFrame"] iframe {
                height: calc(100vh - 5.4rem) !important;
                min-height: 720px;
                width: 100% !important;
            }
            @media (max-width: 760px) {
                .sgop-landing-header {
                    align-items: flex-start;
                    flex-direction: column;
                    gap: 0.25rem;
                }
                .sgop-landing-status {
                    justify-content: flex-start;
                }
                div[data-testid="stIFrame"],
                div[data-testid="stIFrame"] iframe {
                    height: calc(100vh - 7.2rem) !important;
                    min-height: 560px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_landing_map_header(
    scenario: ScenarioContext,
    map_capability: MapCapability,
) -> None:
    fallback_label = (
        f"<span>fallback {map_capability.fallback.mode}</span>"
        if map_capability.fallback.enabled
        else ""
    )
    st.markdown(
        f"""
        <div class="sgop-landing-header">
            <div class="sgop-landing-title">SGOP 운영 지도</div>
            <div class="sgop-landing-status">
                <span>시나리오 {scenario.scenario_id}</span>
                <span>지도 {map_capability.rendering_mode}</span>
                <span>추가 지점 {len(st.session_state.sgop_landing_installations)}개</span>
                <span>좌표계 EPSG:4326</span>
                <span>{settings.sgop_env}</span>
                {fallback_label}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _init_landing_state() -> None:
    if "sgop_landing_installations" not in st.session_state:
        st.session_state.sgop_landing_installations = []
    if "sgop_landing_last_click" not in st.session_state:
        st.session_state.sgop_landing_last_click = None
    if "sgop_landing_add_requested" not in st.session_state:
        st.session_state.sgop_landing_add_requested = False
    if _LANDING_TARGET_STATE_KEY not in st.session_state:
        st.session_state[_LANDING_TARGET_STATE_KEY] = "발전소"
    if LANDING_INTERACTION_MODE_STATE_KEY not in st.session_state:
        st.session_state[LANDING_INTERACTION_MODE_STATE_KEY] = "install"
    if GLOBAL_LOAD_SCALE_STATE_KEY not in st.session_state:
        st.session_state[GLOBAL_LOAD_SCALE_STATE_KEY] = 1.0
    if TRANSMISSION_SCENARIOS_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = []
    if TRANSMISSION_SELECTION_STEP_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "start"
    if TRANSMISSION_START_NODE_ID_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_START_NODE_ID_STATE_KEY] = ""
    if TRANSMISSION_START_NODE_LABEL_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_START_NODE_LABEL_STATE_KEY] = ""
    if TRANSMISSION_END_NODE_ID_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_END_NODE_ID_STATE_KEY] = ""
    if TRANSMISSION_END_NODE_LABEL_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_END_NODE_LABEL_STATE_KEY] = ""
    if TRANSMISSION_SELECTION_WARNING_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
    if TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY] = ""
    if TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY] = DEFAULT_TRANSFER_MW
    if TRANSMISSION_CREATE_REQUESTED_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_CREATE_REQUESTED_STATE_KEY] = False
    if TRANSMISSION_NEXT_INDEX_STATE_KEY not in st.session_state:
        st.session_state[TRANSMISSION_NEXT_INDEX_STATE_KEY] = 1
    if SELECTED_GRID_OBJECT_STATE_KEY not in st.session_state:
        st.session_state[SELECTED_GRID_OBJECT_STATE_KEY] = {}


def _render_left_panel() -> tuple[
    str,
    InstallationTargetKind,
    InstallationMode,
    str,
    float | None,
    float | None,
    str,
]:
    with st.sidebar:
        st.header("운영 패널")
        interaction_mode = st.radio(
            "작업 모드",
            options=list(_INTERACTION_MODE_LABEL.keys()),
            format_func=lambda mode: _INTERACTION_MODE_LABEL[mode],
            horizontal=True,
            key=LANDING_INTERACTION_MODE_STATE_KEY,
        )

        if interaction_mode == "transmission":
            _render_transmission_selection_panel()
            st.divider()
            _render_global_load_scale_control()
            _render_connection_status("transmission", "review")
            return (
                interaction_mode,
                "transmission_tower",
                "review",
                "",
                None,
                345.0,
                "",
            )

        st.subheader("설치 패널")
        selected_label = st.radio(
            "설치 대상",
            options=list(_TARGET_KIND_BY_LABEL.keys()),
            horizontal=True,
            key=_LANDING_TARGET_STATE_KEY,
        )
        selected_kind = _TARGET_KIND_BY_LABEL[selected_label]

        selected_mode_label = st.radio(
            "설치 모드",
            options=list(_INSTALLATION_MODE_BY_LABEL.keys()),
            horizontal=True,
        )
        mode = _INSTALLATION_MODE_BY_LABEL[selected_mode_label]
        selected_point = st.session_state.get("sgop_landing_last_click")
        selected_point = selected_point if isinstance(selected_point, MapOverlayPoint) else None
        _sync_installation_name(selected_kind, selected_point)
        name = st.text_input("이름", key=_LANDING_NAME_STATE_KEY)

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

        if isinstance(selected_point, MapOverlayPoint):
            st.divider()
            st.metric("x", f"{selected_point.longitude:.6f}")
            st.metric("y", f"{selected_point.latitude:.6f}")
            nearest_label = _format_nearest_place(selected_point)
            if nearest_label:
                st.caption(f"가장 가까운 지명: {nearest_label}")

        if st.button("설치 지점 추가", type="primary", use_container_width=True):
            st.session_state.sgop_landing_add_requested = True

        if st.button("설치 목록 초기화", use_container_width=True):
            st.session_state.sgop_landing_installations = []
            st.session_state.sgop_landing_last_click = None
            _queue_installation_name_reset(selected_kind)
            st.rerun()

        st.divider()
        _render_global_load_scale_control()

        _render_connection_status("install", mode)

        return (
            interaction_mode,
            selected_kind,
            mode,
            name.strip() or _suggest_installation_name(selected_kind, selected_point),
            capacity_mw,
            voltage_kv,
            notes.strip(),
        )


def _render_connection_status(
    interaction_mode: str,
    install_mode: InstallationMode,
) -> None:
    with st.expander("연결 상태", expanded=False):
        st.write(
            {
                "VWORLD_API_KEY": bool(settings.vworld_api_key),
                "PUBLIC_DATA_API_KEY": bool(settings.public_data_api_key),
                "OPENAI_API_KEY": bool(settings.openai_api_key),
                "map_mode": "2.5D",
                "vworld_tiles": bool(getattr(st.session_state, "sgop_landing_has_vworld_tiles", False)),
                "interaction_mode": interaction_mode,
                "install_mode": _INSTALLATION_MODE_LABEL[install_mode],
            }
        )


def _render_transmission_selection_panel() -> None:
    st.subheader("송전 선택")
    start_label = _transmission_node_label("start")
    end_label = _transmission_node_label("end")
    step = _get_transmission_selection_step()
    st.metric("시작 노드", start_label or "-")
    st.metric("종료 노드", end_label or "-")
    st.caption(f"다음 선택: {_TRANSMISSION_STEP_LABEL[step]}")
    st.number_input(
        "예상 송전량 (MW)",
        min_value=10.0,
        max_value=3000.0,
        value=_get_requested_transfer_mw(),
        step=10.0,
        key=TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY,
    )

    warning = st.session_state.get(TRANSMISSION_SELECTION_WARNING_STATE_KEY, "")
    if isinstance(warning, str) and warning:
        st.warning(warning)

    if st.button(
        "송전 시나리오 생성",
        type="primary",
        use_container_width=True,
        disabled=not _transmission_selection_ready(),
    ):
        st.session_state[TRANSMISSION_CREATE_REQUESTED_STATE_KEY] = True

    if st.button("송전 선택 초기화", use_container_width=True):
        _reset_transmission_selection()
        st.rerun()

    _render_transmission_scenario_list()


def _render_transmission_scenario_list() -> None:
    scenarios = _landing_transmission_scenarios()
    if not scenarios:
        st.caption("생성된 송전 시나리오 없음")
        return

    active_count = sum(1 for scenario in scenarios if scenario.status == "active")
    st.caption(f"송전 시나리오 {len(scenarios)}개 | 활성 {active_count}개")
    for fallback_index, scenario in enumerate(scenarios, start=1):
        scenario_color = _transmission_scenario_color_for_scenario(
            scenario,
            fallback_index=fallback_index,
        )
        marker = (
            f'<span style="display:inline-block;width:0.72rem;height:0.72rem;'
            f'border-radius:999px;background:{scenario_color};margin-right:0.35rem;"></span>'
        )
        st.markdown(f"{marker}{scenario.label}", unsafe_allow_html=True)
        with st.expander("상세", expanded=False):
            st.write(
                {
                    "상태": scenario.status,
                    "시작": scenario.start_node_name or scenario.start_node_id,
                    "종료": scenario.end_node_name or scenario.end_node_id,
                    "송전량(MW)": round(float(scenario.requested_transfer_mw), 2),
                    "경로 노드 수": len(scenario.path_node_ids),
                    "사용 선로 수": len(scenario.used_line_ids),
                    "생성 시각": scenario.created_at.isoformat() if scenario.created_at else "",
                }
            )
            if scenario.status == "active":
                button_label = "비활성화"
                next_status = "disabled"
            else:
                button_label = "재활성화"
                next_status = "active"
            if st.button(
                button_label,
                key=f"tx-scenario-status:{scenario.scenario_route_id}:{next_status}",
                use_container_width=True,
            ):
                _set_transmission_scenario_status(
                    scenario.scenario_route_id,
                    next_status,
                )
                st.rerun()

    if st.button("송전 시나리오 전체 초기화", use_container_width=True):
        _clear_transmission_scenarios()
        st.rerun()


def _render_global_load_scale_control() -> float:
    load_scale = _normalize_global_load_scale_state()
    return st.slider(
        "시스템 전체 부하 배율",
        min_value=0.6,
        max_value=1.5,
        value=load_scale,
        step=0.05,
        key=GLOBAL_LOAD_SCALE_STATE_KEY,
    )


def _render_stress_summary_panel(
    stress_analysis: StressAnalysisResult | None,
) -> None:
    st.subheader("선로 stress")
    if stress_analysis is None:
        st.caption("stress 결과 없음")
        return

    metrics = _stress_summary_metrics(stress_analysis)
    st.metric("활성 시나리오", metrics["활성 시나리오"])
    st.metric("병목 선로", metrics["병목 선로"])
    st.metric("위험/과부하", metrics["위험/과부하"])
    st.metric("최대 이용률", metrics["최대 이용률"])
    max_line_id = metrics["최대 이용률 선로"]
    if max_line_id:
        st.caption(f"최대 선로: {max_line_id}")


def _render_stress_detail_panel(
    stress_analysis: StressAnalysisResult | None,
) -> None:
    st.subheader("선로별 이용률")
    if stress_analysis is None:
        st.info("선로 stress 결과가 없습니다.")
        return

    filter_label = st.selectbox(
        "선로 상태 필터",
        options=list(_STRESS_STATUS_FILTERS),
        index=0,
        key="sgop_stress_line_status_filter",
    )
    utilization_rows = _line_utilization_table_rows(
        stress_analysis,
        status_filter=filter_label,
    )
    if utilization_rows:
        st.dataframe(utilization_rows, use_container_width=True, hide_index=True)
    else:
        st.info("표시할 선로가 없습니다.")

    st.subheader("위험/경고 선로")
    risk_rows = _risk_line_table_rows(stress_analysis)
    if risk_rows:
        st.dataframe(risk_rows, use_container_width=True, hide_index=True)
    else:
        st.success("위험/경고 선로가 없습니다.")


def _render_selected_grid_object_detail(
    *,
    stress_analysis: StressAnalysisResult | None,
    monitoring_result: MonitoringResult | None,
    overlay_points: list[MapOverlayPoint],
    overlay_lines: list[MapOverlayLine],
) -> None:
    st.subheader("선택 상세")
    selected = _selected_grid_object()
    if not selected:
        st.info("노드 또는 선로를 선택하면 상세 상태가 표시됩니다.")
        return

    object_type = selected.get("type")
    object_id = selected.get("id")
    if not isinstance(object_id, str) or not object_id:
        st.info("선택된 객체 정보가 없습니다.")
        return

    if object_type == "line":
        rows = _line_detail_rows(
            object_id,
            overlay_lines=overlay_lines,
            stress_analysis=stress_analysis,
            monitoring_result=monitoring_result,
        )
    elif object_type == "node":
        rows = _node_detail_rows(
            object_id,
            overlay_points=overlay_points,
            stress_analysis=stress_analysis,
        )
    else:
        rows = []

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("선택된 객체의 상세 정보를 찾을 수 없습니다.")


def _line_detail_rows(
    line_id: str,
    *,
    overlay_lines: list[MapOverlayLine],
    stress_analysis: StressAnalysisResult | None,
    monitoring_result: MonitoringResult | None,
) -> list[dict[str, object]]:
    overlay_line = _overlay_line_by_id(overlay_lines).get(line_id)
    stress = _line_stress_by_id(stress_analysis).get(line_id)
    line_status = _line_status_by_id(monitoring_result).get(line_id)
    if overlay_line is None and stress is None and line_status is None:
        return []

    label = (
        overlay_line.label
        if overlay_line is not None
        else f"{stress.from_node_name or stress.from_node_id} -> {stress.to_node_name or stress.to_node_id}"
        if stress is not None
        else f"{line_status.from_bus_name} -> {line_status.to_bus_name}"
    )
    capacity_mw = _first_number(
        stress.capacity_mw if stress is not None else None,
        line_status.capacity_mw if line_status is not None else None,
        overlay_line.metadata.get("capacity_mw") if overlay_line is not None else None,
    )
    rows = [
        {"항목": "객체", "값": "선로"},
        {"항목": "선로 ID", "값": line_id},
        {"항목": "구간", "값": label},
        {"항목": "전압", "값": _format_optional_kv(overlay_line.metadata.get("voltage_kv") if overlay_line is not None else None)},
        {"항목": "용량", "값": _format_optional_mw(capacity_mw)},
        {"항목": "DC 현재 흐름", "값": _format_optional_mw(line_status.flow_mw if line_status is not None else None)},
        {"항목": "DC 이용률", "값": _format_optional_percent(line_status.utilization if line_status is not None else None)},
        {"항목": "DC 손실", "값": _format_optional_mw(line_status.loss_mw if line_status is not None else None)},
        {"항목": "기본 흐름", "값": _format_optional_mw(stress.base_flow_mw if stress is not None else None)},
        {"항목": "시나리오 추가 흐름", "값": _format_optional_mw(stress.scenario_flow_mw if stress is not None else None)},
        {"항목": "예측 추가 흐름", "값": _format_optional_mw(stress.predicted_flow_mw if stress is not None else None)},
        {"항목": "누적 총 흐름", "값": _format_optional_mw(stress.total_flow_mw if stress is not None else None)},
        {"항목": "누적 이용률", "값": _format_optional_percent(stress.utilization if stress is not None else None)},
        {"항목": "상태", "값": stress.status if stress is not None else line_status.status if line_status is not None else ""},
        {"항목": "위험도", "값": stress.risk_level if stress is not None else line_status.risk_level if line_status is not None else ""},
        {"항목": "공유 시나리오 수", "값": stress.shared_route_count if stress is not None else 0},
        {"항목": "기여 시나리오", "값": ", ".join(stress.contributing_scenario_ids) if stress is not None else ""},
        {"항목": "용량 여유", "값": _format_optional_mw(stress.metadata.get("capacity_margin_mw") if stress is not None else None)},
        {"항목": "데이터 소스", "값": monitoring_result.source if monitoring_result is not None else "not_available"},
    ]
    return rows


def _node_detail_rows(
    node_id: str,
    *,
    overlay_points: list[MapOverlayPoint],
    stress_analysis: StressAnalysisResult | None,
) -> list[dict[str, object]]:
    point = _overlay_point_by_node_id(overlay_points).get(node_id)
    node_stress = _node_stress_by_id(stress_analysis).get(node_id)
    if point is None and node_stress is None:
        return []

    label = point.label if point is not None else node_stress.node_name
    metadata = point.metadata if point is not None else {}
    rows = [
        {"항목": "객체", "값": "노드"},
        {"항목": "노드 ID", "값": node_id},
        {"항목": "이름", "값": label},
        {"항목": "유형", "값": point.kind if point is not None else node_stress.node_type},
        {"항목": "전압", "값": _format_optional_kv(metadata.get("voltage_kv"))},
        {"항목": "발전량", "값": _format_optional_mw(node_stress.generation_mw if node_stress is not None else metadata.get("generation_mw"))},
        {"항목": "부하량", "값": _format_optional_mw(node_stress.load_mw if node_stress is not None else metadata.get("load_mw"))},
        {"항목": "순주입량", "값": _format_optional_mw(node_stress.net_injection_mw if node_stress is not None else metadata.get("net_injection_mw"))},
        {"항목": "연결 선로 수", "값": node_stress.metadata.get("connected_line_count", len(node_stress.connected_line_ids)) if node_stress is not None else ""},
        {"항목": "연결 선로", "값": ", ".join(node_stress.connected_line_ids) if node_stress is not None else ""},
        {"항목": "연결 시나리오", "값": ", ".join(node_stress.connected_scenario_ids) if node_stress is not None else ""},
        {"항목": "최대 연결 이용률", "값": _format_optional_percent(node_stress.metadata.get("max_connected_utilization") if node_stress is not None else None)},
        {"항목": "최대 이용률 선로", "값": node_stress.metadata.get("max_connected_line_id", "") if node_stress is not None else ""},
        {"항목": "위험도", "값": node_stress.risk_level if node_stress is not None else ""},
        {"항목": "데이터 소스", "값": "DC Power Flow + route stress"},
    ]
    return rows


def _stress_status_counts(
    stress_analysis: StressAnalysisResult,
) -> dict[str, int]:
    counts = {
        "normal": 0,
        "warning": 0,
        "critical": 0,
        "overload": 0,
    }
    for stress in stress_analysis.line_stresses:
        if stress.status in counts:
            counts[stress.status] += 1
    return counts


def _stress_summary_metrics(
    stress_analysis: StressAnalysisResult,
) -> dict[str, object]:
    counts = _stress_status_counts(stress_analysis)
    max_line = max(
        stress_analysis.line_stresses,
        key=lambda stress: stress.utilization,
        default=None,
    )
    return {
        "활성 시나리오": len(stress_analysis.transmission_scenarios),
        "분석 선로": len(stress_analysis.line_stresses),
        "정상 선로": counts["normal"],
        "경고 선로": counts["warning"],
        "위험/과부하": counts["critical"] + counts["overload"],
        "병목 선로": len(stress_analysis.bottleneck_line_ids),
        "최대 이용률": _format_percent(max_line.utilization if max_line else 0.0),
        "최대 이용률 선로": max_line.line_id if max_line else "",
    }


def _line_utilization_table_rows(
    stress_analysis: StressAnalysisResult,
    *,
    status_filter: str = "전체",
) -> list[dict[str, object]]:
    bottleneck_line_ids = set(stress_analysis.bottleneck_line_ids)
    accepted_statuses = _STRESS_STATUS_BY_FILTER.get(status_filter)
    rows: list[dict[str, object]] = []
    for stress in stress_analysis.line_stresses:
        is_bottleneck = stress.line_id in bottleneck_line_ids
        if status_filter == "병목만" and not is_bottleneck:
            continue
        if accepted_statuses is not None and stress.status not in accepted_statuses:
            continue

        rows.append(_line_stress_table_row(stress, is_bottleneck=is_bottleneck))
    return sorted(
        rows,
        key=lambda row: float(row["이용률"]),
        reverse=True,
    )


def _risk_line_table_rows(
    stress_analysis: StressAnalysisResult,
) -> list[dict[str, object]]:
    target_line_ids = set(stress_analysis.warning_line_ids)
    target_line_ids.update(stress_analysis.critical_line_ids)
    target_line_ids.update(stress_analysis.bottleneck_line_ids)
    return [
        row
        for row in _line_utilization_table_rows(stress_analysis)
        if row["선로 ID"] in target_line_ids
    ]


def _line_stress_table_row(
    stress: Any,
    *,
    is_bottleneck: bool,
) -> dict[str, object]:
    capacity_margin_mw = stress.metadata.get(
        "capacity_margin_mw",
        stress.capacity_mw - stress.total_flow_mw,
    )
    return {
        "선로 ID": stress.line_id,
        "From": stress.from_node_name or stress.from_node_id,
        "To": stress.to_node_name or stress.to_node_id,
        "용량 MW": round(float(stress.capacity_mw), 2),
        "기본 흐름 MW": round(float(stress.base_flow_mw), 2),
        "시나리오 추가 MW": round(float(stress.scenario_flow_mw), 2),
        "총 흐름 MW": round(float(stress.total_flow_mw), 2),
        "이용률": round(float(stress.utilization), 6),
        "이용률 %": _format_percent(float(stress.utilization)),
        "상태": stress.status,
        "위험도": stress.risk_level,
        "공유 시나리오 수": int(stress.shared_route_count),
        "기여 시나리오": ", ".join(stress.contributing_scenario_ids),
        "용량 여유 MW": round(float(capacity_margin_mw), 2),
        "병목": "Y" if is_bottleneck else "",
    }


def _line_status_by_id(
    monitoring_result: MonitoringResult | None,
) -> dict[str, LineStatus]:
    if monitoring_result is None:
        return {}
    return {
        status.line_id: status
        for status in monitoring_result.line_statuses
        if isinstance(status, LineStatus)
    }


def _line_stress_by_id(
    stress_analysis: StressAnalysisResult | None,
) -> dict[str, Any]:
    if stress_analysis is None:
        return {}
    return {
        stress.line_id: stress
        for stress in stress_analysis.line_stresses
    }


def _node_stress_by_id(
    stress_analysis: StressAnalysisResult | None,
) -> dict[str, Any]:
    if stress_analysis is None:
        return {}
    return {
        stress.node_id: stress
        for stress in stress_analysis.node_stresses
    }


def _overlay_point_by_node_id(
    points: list[MapOverlayPoint],
) -> dict[str, MapOverlayPoint]:
    return {
        node_id: point
        for point in points
        if (node_id := _node_id_from_overlay_point(point))
    }


def _first_number(*values: object) -> float | None:
    for value in values:
        if isinstance(value, (float, int)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _format_optional_mw(value: object) -> str:
    number = _first_number(value)
    return f"{number:.2f} MW" if number is not None else ""


def _format_optional_kv(value: object) -> str:
    number = _first_number(value)
    return f"{number:.1f} kV" if number is not None else ""


def _format_optional_percent(value: object) -> str:
    number = _first_number(value)
    return _format_percent(number) if number is not None else ""


def _format_percent(value: float) -> str:
    return f"{value:.1%}"


def _get_global_load_scale() -> float:
    raw_value = st.session_state.get(GLOBAL_LOAD_SCALE_STATE_KEY, 1.0)
    try:
        load_scale = float(raw_value)
    except (TypeError, ValueError):
        load_scale = 1.0
    return min(1.5, max(0.6, load_scale))


def _normalize_global_load_scale_state() -> float:
    load_scale = _get_global_load_scale()
    st.session_state[GLOBAL_LOAD_SCALE_STATE_KEY] = load_scale
    return load_scale


def _get_requested_transfer_mw() -> float:
    raw_value = st.session_state.get(
        TRANSMISSION_REQUESTED_TRANSFER_MW_STATE_KEY,
        DEFAULT_TRANSFER_MW,
    )
    try:
        transfer_mw = float(raw_value)
    except (TypeError, ValueError):
        transfer_mw = DEFAULT_TRANSFER_MW
    return min(3000.0, max(10.0, transfer_mw))


def _transmission_selection_ready() -> bool:
    start_node_id = str(st.session_state.get(TRANSMISSION_START_NODE_ID_STATE_KEY, ""))
    end_node_id = str(st.session_state.get(TRANSMISSION_END_NODE_ID_STATE_KEY, ""))
    return (
        _get_transmission_selection_step() == "ready"
        and bool(start_node_id)
        and bool(end_node_id)
        and start_node_id != end_node_id
    )


def _get_transmission_selection_step() -> str:
    step = st.session_state.get(TRANSMISSION_SELECTION_STEP_STATE_KEY, "start")
    if step not in _TRANSMISSION_STEP_LABEL:
        step = "start"
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = step
    return str(step)


def _transmission_node_label(role: str) -> str:
    if role == "start":
        label = st.session_state.get(TRANSMISSION_START_NODE_LABEL_STATE_KEY, "")
        node_id = st.session_state.get(TRANSMISSION_START_NODE_ID_STATE_KEY, "")
    else:
        label = st.session_state.get(TRANSMISSION_END_NODE_LABEL_STATE_KEY, "")
        node_id = st.session_state.get(TRANSMISSION_END_NODE_ID_STATE_KEY, "")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return str(node_id or "")


def _reset_transmission_selection() -> None:
    st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "start"
    st.session_state[TRANSMISSION_START_NODE_ID_STATE_KEY] = ""
    st.session_state[TRANSMISSION_START_NODE_LABEL_STATE_KEY] = ""
    st.session_state[TRANSMISSION_END_NODE_ID_STATE_KEY] = ""
    st.session_state[TRANSMISSION_END_NODE_LABEL_STATE_KEY] = ""
    st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
    st.session_state[TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY] = ""


def _clear_transmission_scenarios() -> None:
    st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = []
    st.session_state[TRANSMISSION_NEXT_INDEX_STATE_KEY] = 1
    _reset_transmission_selection()


def _set_transmission_scenario_status(
    scenario_route_id: str,
    status: TransmissionScenarioStatus,
) -> bool:
    scenarios = list(st.session_state.get(TRANSMISSION_SCENARIOS_STATE_KEY, []))
    updated_scenarios: list[object] = []
    changed = False
    duplicate_blocked = False

    for scenario in scenarios:
        if not isinstance(scenario, TransmissionScenario):
            updated_scenarios.append(scenario)
            continue
        if scenario.scenario_route_id != scenario_route_id:
            updated_scenarios.append(scenario)
            continue
        if status == "active" and _has_active_transmission_duplicate(
            scenario,
            [item for item in scenarios if isinstance(item, TransmissionScenario)],
            exclude_scenario_route_id=scenario_route_id,
        ):
            updated_scenarios.append(scenario)
            duplicate_blocked = True
            continue
        updated_scenarios.append(replace(scenario, status=status))
        changed = changed or scenario.status != status

    st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = updated_scenarios
    if duplicate_blocked:
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            "같은 시작/종료/송전량/경로의 활성 송전 시나리오가 이미 있습니다."
        )
    elif changed:
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
    return changed


def _has_active_transmission_duplicate(
    candidate: TransmissionScenario,
    scenarios: list[TransmissionScenario],
    *,
    exclude_scenario_route_id: str = "",
) -> bool:
    candidate_signature = _transmission_scenario_signature(candidate)
    return any(
        scenario.scenario_route_id != exclude_scenario_route_id
        and scenario.status == "active"
        and _transmission_scenario_signature(scenario) == candidate_signature
        for scenario in scenarios
    )


def _should_process_transmission_click(clicked_point: MapOverlayPoint) -> bool:
    signature = _map_click_signature(clicked_point)
    if st.session_state.get(TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY) == signature:
        return False
    st.session_state[TRANSMISSION_LAST_CLICK_SIGNATURE_STATE_KEY] = signature
    return True


def _map_click_signature(clicked_point: MapOverlayPoint) -> tuple[object, ...]:
    return (
        round(clicked_point.latitude, 7),
        round(clicked_point.longitude, 7),
        clicked_point.metadata.get("capture_source", ""),
        clicked_point.metadata.get("object_tooltip", ""),
    )


def _store_transmission_node_selection(clicked_node: MapOverlayPoint) -> bool:
    node_id = _node_id_from_overlay_point(clicked_node)
    if not node_id:
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            "선택한 지점에 GridNode ID가 없습니다."
        )
        return True

    step = _get_transmission_selection_step()
    if step == "ready":
        st.session_state[TRANSMISSION_START_NODE_ID_STATE_KEY] = node_id
        st.session_state[TRANSMISSION_START_NODE_LABEL_STATE_KEY] = clicked_node.label
        st.session_state[TRANSMISSION_END_NODE_ID_STATE_KEY] = ""
        st.session_state[TRANSMISSION_END_NODE_LABEL_STATE_KEY] = ""
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "end"
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
        return True

    if step == "start":
        st.session_state[TRANSMISSION_START_NODE_ID_STATE_KEY] = node_id
        st.session_state[TRANSMISSION_START_NODE_LABEL_STATE_KEY] = clicked_node.label
        if st.session_state.get(TRANSMISSION_END_NODE_ID_STATE_KEY) == node_id:
            st.session_state[TRANSMISSION_END_NODE_ID_STATE_KEY] = ""
            st.session_state[TRANSMISSION_END_NODE_LABEL_STATE_KEY] = ""
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "end"
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
        return True

    start_node_id = str(st.session_state.get(TRANSMISSION_START_NODE_ID_STATE_KEY, ""))
    if not start_node_id:
        st.session_state[TRANSMISSION_START_NODE_ID_STATE_KEY] = node_id
        st.session_state[TRANSMISSION_START_NODE_LABEL_STATE_KEY] = clicked_node.label
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "end"
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
        return True
    if node_id == start_node_id:
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            "송전 시작 노드와 종료 노드는 달라야 합니다."
        )
        st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "end"
        return True

    st.session_state[TRANSMISSION_END_NODE_ID_STATE_KEY] = node_id
    st.session_state[TRANSMISSION_END_NODE_LABEL_STATE_KEY] = clicked_node.label
    st.session_state[TRANSMISSION_SELECTION_STEP_STATE_KEY] = "ready"
    st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = ""
    return True


def _create_transmission_scenario_from_selection(
    scenario: ScenarioContext,
    *,
    load_scale: float,
) -> bool:
    if not _transmission_selection_ready():
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            "시작 노드와 종료 노드를 먼저 선택하세요."
        )
        return False

    start_node_id = str(st.session_state.get(TRANSMISSION_START_NODE_ID_STATE_KEY, ""))
    end_node_id = str(st.session_state.get(TRANSMISSION_END_NODE_ID_STATE_KEY, ""))
    requested_transfer_mw = _get_requested_transfer_mw()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    scenario_index = _next_transmission_scenario_index()

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=_landing_installations(),
            created_at=created_at,
            load_scale=load_scale,
        )
        service = TransmissionScenarioService()
        route = service.build_route_between_nodes(
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            grid_dataset=dataset,
            load_scale=load_scale,
            route_id=f"tx-route-{scenario_index:03d}",
        )
        transmission_scenario = service.create_transmission_scenario(
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            grid_dataset=dataset,
            requested_transfer_mw=requested_transfer_mw,
            scenario_index=scenario_index,
            route=route,
            created_at=created_at,
            source="astar",
        )
        transmission_scenario = replace(
            transmission_scenario,
            metadata={
                **transmission_scenario.metadata,
                "scenario_order": scenario_index,
                "scenario_color": _transmission_scenario_color(scenario_index),
            },
        )
        if transmission_scenario.status != "active":
            st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = " ".join(transmission_scenario.warnings)
            return False
        if _is_duplicate_transmission_scenario(
            transmission_scenario,
            _landing_transmission_scenarios(),
        ):
            st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
                "같은 시작/종료/송전량/경로의 송전 시나리오가 이미 있습니다."
            )
            return False

        scenarios = list(st.session_state.get(TRANSMISSION_SCENARIOS_STATE_KEY, []))
        scenarios.append(transmission_scenario)
        st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = scenarios
        st.session_state[TRANSMISSION_NEXT_INDEX_STATE_KEY] = scenario_index + 1
        _reset_transmission_selection()
        return True
    except Exception as exc:  # noqa: BLE001
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            f"송전 시나리오를 생성하지 못했습니다. 원인: {exc}"
        )
        return False


def _next_transmission_scenario_index() -> int:
    raw_index = st.session_state.get(TRANSMISSION_NEXT_INDEX_STATE_KEY, 1)
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        index = 1
    return max(1, index)


def _transmission_scenario_color(scenario_order: int) -> str:
    normalized_order = max(1, int(scenario_order))
    return _TRANSMISSION_SCENARIO_COLORS[
        (normalized_order - 1) % len(_TRANSMISSION_SCENARIO_COLORS)
    ]


def _transmission_scenario_order(
    scenario: TransmissionScenario,
    *,
    fallback_index: int,
) -> int:
    raw_order = scenario.metadata.get("scenario_order", fallback_index)
    try:
        scenario_order = int(raw_order)
    except (TypeError, ValueError):
        scenario_order = fallback_index
    return max(1, scenario_order)


def _transmission_scenario_color_for_scenario(
    scenario: TransmissionScenario,
    *,
    fallback_index: int,
) -> str:
    raw_color = scenario.metadata.get("scenario_color", "")
    if isinstance(raw_color, str) and raw_color.strip():
        return raw_color.strip()
    return _transmission_scenario_color(
        _transmission_scenario_order(scenario, fallback_index=fallback_index)
    )


def _is_duplicate_transmission_scenario(
    candidate: TransmissionScenario,
    scenarios: list[TransmissionScenario],
) -> bool:
    return _has_active_transmission_duplicate(candidate, scenarios)


def _transmission_scenario_signature(
    scenario: TransmissionScenario,
) -> tuple[object, ...]:
    return (
        scenario.start_node_id,
        scenario.end_node_id,
        round(float(scenario.requested_transfer_mw), 4),
        tuple(scenario.path_node_ids),
        tuple(scenario.used_line_ids),
    )


def _sync_installation_name(
    kind: InstallationTargetKind,
    selected_point: MapOverlayPoint | None,
) -> None:
    pending_name = st.session_state.pop(_LANDING_PENDING_NAME_STATE_KEY, None)
    pending_kind = st.session_state.pop(_LANDING_PENDING_KIND_STATE_KEY, None)
    if isinstance(pending_name, str) and pending_kind == kind:
        _set_installation_name_state(kind, pending_name)
        return

    suggested_name = _suggest_installation_name(kind, selected_point)
    current_name = st.session_state.get(_LANDING_NAME_STATE_KEY)
    previous_auto_name = st.session_state.get(_LANDING_AUTO_NAME_STATE_KEY)
    previous_auto_kind = st.session_state.get(_LANDING_AUTO_KIND_STATE_KEY)

    if (
        not isinstance(current_name, str)
        or not current_name.strip()
        or current_name == previous_auto_name
        or previous_auto_kind != kind
    ):
        _set_installation_name_state(kind, suggested_name)


def _set_installation_name_state(
    kind: InstallationTargetKind,
    suggested_name: str,
) -> None:
    st.session_state[_LANDING_NAME_STATE_KEY] = suggested_name
    st.session_state[_LANDING_AUTO_NAME_STATE_KEY] = suggested_name
    st.session_state[_LANDING_AUTO_KIND_STATE_KEY] = kind


def _queue_installation_name_reset(
    kind: InstallationTargetKind,
    selected_point: MapOverlayPoint | None = None,
) -> None:
    suggested_name = _suggest_installation_name(kind, selected_point)
    st.session_state[_LANDING_PENDING_NAME_STATE_KEY] = suggested_name
    st.session_state[_LANDING_PENDING_KIND_STATE_KEY] = kind


def _suggest_installation_name(
    kind: InstallationTargetKind,
    selected_point: MapOverlayPoint | None = None,
) -> str:
    if isinstance(selected_point, MapOverlayPoint):
        place_name = selected_point.metadata.get("nearest_place_name")
        if isinstance(place_name, str) and place_name.strip():
            return f"{place_name.strip()} {_installation_suffix(kind)}"

    sequence = len(st.session_state.get("sgop_landing_installations", [])) + 1
    default_name = _TARGET_DEFAULT_NAME[kind]
    return f"{default_name} {sequence}"


def _installation_suffix(kind: InstallationTargetKind) -> str:
    labels: dict[InstallationTargetKind, str] = {
        "power_plant": "발전소",
        "transmission_tower": "송전탑",
        "start_point": "시작점",
        "end_point": "종료점",
    }
    return labels[kind]


def _store_last_clicked_point(
    clicked_point: MapOverlayPoint,
    kind: InstallationTargetKind,
) -> bool:
    current_point = st.session_state.get("sgop_landing_last_click")
    changed = not _same_map_point(current_point, clicked_point)
    if changed:
        st.session_state.sgop_landing_last_click = clicked_point
        _queue_installation_name_reset(kind, clicked_point)
    return changed


def _same_map_point(
    current_point: object,
    clicked_point: MapOverlayPoint,
) -> bool:
    if not isinstance(current_point, MapOverlayPoint):
        return False
    return (
        abs(current_point.latitude - clicked_point.latitude) < 1e-9
        and abs(current_point.longitude - clicked_point.longitude) < 1e-9
        and current_point.metadata.get("nearest_place_id")
        == clicked_point.metadata.get("nearest_place_id")
    )


def _find_clicked_grid_node(
    clicked_point: MapOverlayPoint,
    overlay_points: list[MapOverlayPoint],
    *,
    max_distance_km: float = _TRANSMISSION_NODE_CLICK_THRESHOLD_KM,
) -> MapOverlayPoint | None:
    candidates = [
        point
        for point in overlay_points
        if point.kind in _TRANSMISSION_SELECTABLE_KINDS
        and _node_id_from_overlay_point(point)
    ]
    if not candidates:
        return None

    object_tooltip = clicked_point.metadata.get("object_tooltip")
    if isinstance(object_tooltip, str) and object_tooltip.strip():
        tooltip = object_tooltip.strip()
        tooltip_matches = [
            point
            for point in candidates
            if point.label == tooltip
        ]
        if not tooltip_matches:
            return None
        candidates = tooltip_matches

    nearest_point = min(
        candidates,
        key=lambda point: _distance_km(
            clicked_point.latitude,
            clicked_point.longitude,
            point.latitude,
            point.longitude,
        ),
    )
    distance_km = _distance_km(
        clicked_point.latitude,
        clicked_point.longitude,
        nearest_point.latitude,
        nearest_point.longitude,
    )
    if distance_km > max_distance_km:
        return None

    return nearest_point


def _extract_clicked_grid_object(
    clicked_point: MapOverlayPoint,
    *,
    overlay_points: list[MapOverlayPoint],
    overlay_lines: list[MapOverlayLine],
) -> dict[str, object] | None:
    clicked_line = _find_clicked_grid_line(clicked_point, overlay_lines)
    if clicked_line is not None:
        return _grid_object_from_line(clicked_line)

    clicked_node = _find_clicked_grid_node(clicked_point, overlay_points)
    if clicked_node is not None:
        return _grid_object_from_node_point(clicked_node)

    return None


def _find_clicked_grid_line(
    clicked_point: MapOverlayPoint,
    overlay_lines: list[MapOverlayLine],
) -> MapOverlayLine | None:
    object_tooltip = clicked_point.metadata.get("object_tooltip")
    line_id = _parse_line_click_tooltip(object_tooltip)
    if not line_id:
        return None
    return _overlay_line_by_id(overlay_lines).get(line_id)


def _parse_line_click_tooltip(tooltip: object) -> str:
    if not isinstance(tooltip, str) or "|" not in tooltip:
        return ""
    line_id = tooltip.split("|", 1)[0].strip()
    return line_id if line_id else ""


def _grid_object_from_node_point(point: MapOverlayPoint) -> dict[str, object]:
    return {
        "type": "node",
        "id": _node_id_from_overlay_point(point),
        "label": point.label,
        "source": "map_click",
    }


def _grid_object_from_line(line: MapOverlayLine) -> dict[str, object]:
    line_id = str(line.metadata.get("line_id", line.overlay_id))
    return {
        "type": "line",
        "id": line_id,
        "label": line.label,
        "source": "map_click",
    }


def _store_selected_grid_object(grid_object: dict[str, object]) -> bool:
    object_type = grid_object.get("type")
    object_id = grid_object.get("id")
    if object_type not in {"node", "line"} or not isinstance(object_id, str) or not object_id:
        return False

    normalized = {
        "type": object_type,
        "id": object_id,
        "label": str(grid_object.get("label", object_id)),
        "source": str(grid_object.get("source", "map_click")),
    }
    current = st.session_state.get(SELECTED_GRID_OBJECT_STATE_KEY)
    if isinstance(current, dict) and (
        current.get("type"),
        current.get("id"),
    ) == (
        normalized["type"],
        normalized["id"],
    ):
        return False
    st.session_state[SELECTED_GRID_OBJECT_STATE_KEY] = normalized
    return True


def _selected_grid_object() -> dict[str, object]:
    selected = st.session_state.get(SELECTED_GRID_OBJECT_STATE_KEY)
    if isinstance(selected, dict):
        return selected
    return {}


def _selected_grid_object_line_id() -> str | None:
    selected = _selected_grid_object()
    if selected.get("type") != "line":
        return None
    line_id = selected.get("id")
    return line_id if isinstance(line_id, str) and line_id else None


def _overlay_line_by_id(lines: list[MapOverlayLine]) -> dict[str, MapOverlayLine]:
    return {
        str(line.metadata.get("line_id", line.overlay_id)): line
        for line in lines
    }


def _node_id_from_overlay_point(point: MapOverlayPoint) -> str:
    for key in ("node_id", "bus_id", "candidate_id"):
        value = point.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if point.overlay_id.startswith("grid-node:"):
        return point.overlay_id.split("grid-node:", 1)[1].strip()
    return ""


def _distance_km(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    radius_km = 6371.0
    lat_a = radians(start_latitude)
    lat_b = radians(end_latitude)
    delta_lat = radians(end_latitude - start_latitude)
    delta_lon = radians(end_longitude - start_longitude)
    haversine = (
        sin(delta_lat / 2.0) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * radius_km * atan2(sqrt(haversine), sqrt(1.0 - haversine))


def _get_landing_monitoring_result(
    scenario: ScenarioContext,
    *,
    load_scale: float,
) -> tuple[MonitoringResult | None, str]:
    installations = _landing_installations()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    cache_key = (
        scenario.scenario_id,
        created_at.isoformat(),
        round(load_scale, 4),
        _installations_cache_key(installations),
    )
    cached = st.session_state.get(_MONITORING_CACHE_STATE_KEY)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        st.session_state[MONITORING_RESULT_STATE_KEY] = cached[1]
        return cached[1], cached[2]

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        result = MonitoringService().run_dc_power_flow(
            scenario=scenario,
            load_scale=load_scale,
            created_at=created_at,
            grid_dataset=dataset,
        )
        warning = ""
        if result.source != "dc_power_flow" or result.fallback.enabled:
            warning = "Monitoring DC Power Flow 결과를 만들지 못해 fallback 결과를 사용합니다."
        st.session_state[MONITORING_RESULT_STATE_KEY] = result
        st.session_state[_MONITORING_CACHE_STATE_KEY] = (cache_key, result, warning)
        return result, warning
    except Exception as exc:  # noqa: BLE001
        warning = f"Monitoring DC Power Flow 결과를 만들지 못했습니다. 원인: {exc}"
        st.session_state[MONITORING_RESULT_STATE_KEY] = None
        st.session_state[_MONITORING_CACHE_STATE_KEY] = (cache_key, None, warning)
        return None, warning


def _get_landing_stress_analysis(
    scenario: ScenarioContext,
    *,
    load_scale: float,
    monitoring_result: MonitoringResult | None = None,
) -> tuple[StressAnalysisResult | None, str]:
    transmission_scenarios = _landing_transmission_scenarios()
    installations = _landing_installations()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    cache_key = (
        scenario.scenario_id,
        created_at.isoformat(),
        round(load_scale, 4),
        _installations_cache_key(installations),
        _transmission_scenarios_cache_key(transmission_scenarios),
        _monitoring_result_cache_key(monitoring_result),
    )
    cached = st.session_state.get(_STRESS_ANALYSIS_CACHE_STATE_KEY)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        st.session_state[STRESS_ANALYSIS_STATE_KEY] = cached[1]
        return cached[1], cached[2]

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        stress_analysis = analyze_route_stress(
            scenario=scenario,
            grid_dataset=dataset,
            transmission_scenarios=transmission_scenarios,
            load_scale=load_scale,
            created_at=created_at,
            monitoring_result=monitoring_result,
        )
        st.session_state[STRESS_ANALYSIS_STATE_KEY] = stress_analysis
        st.session_state[_STRESS_ANALYSIS_CACHE_STATE_KEY] = (cache_key, stress_analysis, "")
        return stress_analysis, ""
    except Exception as exc:  # noqa: BLE001
        warning = f"송전 시나리오 stress 분석을 만들지 못했습니다. 원인: {exc}"
        st.session_state[_STRESS_ANALYSIS_CACHE_STATE_KEY] = (cache_key, None, warning)
        st.session_state[STRESS_ANALYSIS_STATE_KEY] = None
        return None, warning


def _landing_transmission_scenarios() -> list[TransmissionScenario]:
    return [
        scenario
        for scenario in st.session_state.get(TRANSMISSION_SCENARIOS_STATE_KEY, [])
        if isinstance(scenario, TransmissionScenario)
    ]


def _transmission_scenarios_cache_key(
    scenarios: list[TransmissionScenario],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            scenario.scenario_route_id,
            scenario.status,
            scenario.start_node_id,
            scenario.end_node_id,
            round(float(scenario.requested_transfer_mw), 4),
            tuple(scenario.path_node_ids),
            tuple(scenario.used_line_ids),
        )
        for scenario in scenarios
    )


def _monitoring_result_cache_key(
    monitoring_result: MonitoringResult | None,
) -> tuple[object, ...]:
    if monitoring_result is None:
        return ("none",)
    return (
        monitoring_result.source,
        monitoring_result.created_at.isoformat(),
        round(float(monitoring_result.load_scale), 4),
        tuple(
            (
                status.line_id,
                round(float(status.flow_mw), 4),
                round(float(status.utilization), 6),
                status.status,
            )
            for status in monitoring_result.line_statuses
        ),
    )


def _attach_stress_metadata(
    lines: list[MapOverlayLine],
    stress_analysis: StressAnalysisResult | None,
) -> list[MapOverlayLine]:
    if stress_analysis is None:
        return list(lines)

    bottleneck_line_ids = set(stress_analysis.bottleneck_line_ids)
    stress_by_line_id = {
        stress.line_id: stress
        for stress in stress_analysis.line_stresses
    }
    enriched_lines: list[MapOverlayLine] = []
    for line in lines:
        line_id = str(line.metadata.get("line_id", line.overlay_id))
        stress = stress_by_line_id.get(line_id)
        if stress is None:
            enriched_lines.append(line)
            continue

        enriched_lines.append(
            replace(
                line,
                metadata={
                    **line.metadata,
                    "stress_utilization": stress.utilization,
                    "stress_status": stress.status,
                    "stress_risk_level": stress.risk_level,
                    "stress_capacity_mw": stress.capacity_mw,
                    "stress_base_flow_mw": stress.base_flow_mw,
                    "stress_total_flow_mw": stress.total_flow_mw,
                    "stress_scenario_flow_mw": stress.scenario_flow_mw,
                    "stress_predicted_flow_mw": stress.predicted_flow_mw,
                    "stress_shared_route_count": stress.shared_route_count,
                    "stress_capacity_margin_mw": stress.metadata.get(
                        "capacity_margin_mw",
                        stress.capacity_mw - stress.total_flow_mw,
                    ),
                    "is_bottleneck": stress.line_id in bottleneck_line_ids,
                    "contributing_scenario_ids": list(stress.contributing_scenario_ids),
                },
            )
        )
    return enriched_lines


def _attach_node_stress_metadata(
    points: list[MapOverlayPoint],
    stress_analysis: StressAnalysisResult | None,
) -> list[MapOverlayPoint]:
    if stress_analysis is None:
        return list(points)

    stress_by_node_id = {
        stress.node_id: stress
        for stress in stress_analysis.node_stresses
    }
    enriched_points: list[MapOverlayPoint] = []
    for point in points:
        if point.kind not in {"power_plant", "transmission_tower"}:
            enriched_points.append(point)
            continue

        node_id = _node_id_from_overlay_point(point)
        node_stress = stress_by_node_id.get(node_id)
        if node_stress is None:
            enriched_points.append(point)
            continue

        enriched_points.append(
            replace(
                point,
                metadata={
                    **point.metadata,
                    "stress_node_risk_level": node_stress.risk_level,
                    "stress_node_generation_mw": node_stress.generation_mw,
                    "stress_node_load_mw": node_stress.load_mw,
                    "stress_node_net_injection_mw": node_stress.net_injection_mw,
                    "stress_node_connected_line_ids": list(node_stress.connected_line_ids),
                    "stress_node_connected_scenario_ids": list(
                        node_stress.connected_scenario_ids
                    ),
                    "stress_node_connected_line_count": node_stress.metadata.get(
                        "connected_line_count",
                        len(node_stress.connected_line_ids),
                    ),
                    "stress_node_connected_scenario_count": node_stress.metadata.get(
                        "connected_scenario_count",
                        len(node_stress.connected_scenario_ids),
                    ),
                    "stress_node_max_connected_utilization": node_stress.metadata.get(
                        "max_connected_utilization",
                        0.0,
                    ),
                    "stress_node_max_connected_line_id": node_stress.metadata.get(
                        "max_connected_line_id",
                        "",
                    ),
                },
            )
        )
    return enriched_points


def _get_service_overlay(
    scenario: ScenarioContext,
    map_capability: MapCapability,
    *,
    load_scale: float = 1.0,
) -> tuple[MapOverlayResult | None, str]:
    cache_key = (
        scenario.scenario_id,
        scenario.created_at.isoformat() if scenario.created_at is not None else "",
        map_capability.rendering_mode,
        map_capability.vworld_available,
        round(load_scale, 4),
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
            load_scale=load_scale,
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


def _get_grid_overlay(
    scenario: ScenarioContext,
    map_capability: MapCapability,
    *,
    load_scale: float = 1.0,
) -> tuple[MapOverlayResult | None, str]:
    installations = _landing_installations()
    cache_key = (
        scenario.scenario_id,
        scenario.created_at.isoformat() if scenario.created_at is not None else "",
        map_capability.rendering_mode,
        map_capability.vworld_available,
        round(load_scale, 4),
        _installations_cache_key(installations),
    )
    cached = st.session_state.get("sgop_landing_grid_overlay")
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        return cached[1], cached[2]

    try:
        created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        overlay = MapOverlayService().build_grid_overlay(
            dataset,
            scenario=scenario,
            created_at=created_at,
            map_capability=map_capability,
        )
        st.session_state.sgop_landing_grid_overlay = (cache_key, overlay, "")
        return overlay, ""
    except Exception as exc:  # noqa: BLE001
        warning = f"Grid overlay를 만들지 못해 기본 지도 지점만 표시합니다. 원인: {exc}"
        fallback_overlay = MapOverlayService().build_landing_overlay(
            scenario=scenario,
            created_at=scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0),
            points=_build_mock_grid_points(),
            warnings=[warning],
            map_capability=map_capability,
        )
        st.session_state.sgop_landing_grid_overlay = (cache_key, fallback_overlay, warning)
        return fallback_overlay, warning


def _landing_installations() -> list[InstallationPoint]:
    return [
        installation
        for installation in st.session_state.get("sgop_landing_installations", [])
        if isinstance(installation, InstallationPoint)
    ]


def _installations_cache_key(installations: list[InstallationPoint]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            installation.installation_id,
            installation.label,
            installation.kind,
            installation.mode,
            round(installation.latitude, 8),
            round(installation.longitude, 8),
            installation.capacity_mw,
            installation.voltage_kv,
            installation.notes,
        )
        for installation in installations
    )


def _build_landing_points(
    grid_overlay: MapOverlayResult | None,
    service_overlay: MapOverlayResult | None,
) -> list[MapOverlayPoint]:
    points = list(grid_overlay.points) if grid_overlay is not None else _build_mock_grid_points()
    grid_node_ids = {
        str(point.metadata.get("node_id"))
        for point in points
        if point.metadata.get("node_id")
    }
    if service_overlay is not None:
        points.extend(
            point
            for point in service_overlay.points
            if point.kind in {"tower_candidate", "route_point"}
            and str(point.metadata.get("candidate_id") or point.metadata.get("point_id") or "")
            not in grid_node_ids
        )
    return _mark_transmission_selection_points(_dedupe_points(points))


def _mark_transmission_selection_points(
    points: list[MapOverlayPoint],
) -> list[MapOverlayPoint]:
    start_node_id = str(st.session_state.get(TRANSMISSION_START_NODE_ID_STATE_KEY, ""))
    end_node_id = str(st.session_state.get(TRANSMISSION_END_NODE_ID_STATE_KEY, ""))
    if not start_node_id and not end_node_id:
        return list(points)

    marked_points: list[MapOverlayPoint] = []
    for point in points:
        node_id = _node_id_from_overlay_point(point)
        selection_role = ""
        if node_id and node_id == start_node_id:
            selection_role = "start"
        elif node_id and node_id == end_node_id:
            selection_role = "end"

        if not selection_role:
            marked_points.append(point)
            continue

        marked_points.append(
            replace(
                point,
                status="selected",
                metadata={
                    **point.metadata,
                    "selection_role": selection_role,
                    "selected_for": "transmission_scenario",
                },
            )
        )
    return marked_points


def _build_landing_routes(
    service_overlay: MapOverlayResult | None,
) -> list[MapOverlayRoute]:
    """Keep app landing quiet until an explicit route simulation is requested."""
    if service_overlay is None:
        return []

    visible_statuses = {"active_simulation", "optimal_route", "selected"}
    return [
        route
        for route in service_overlay.routes
        if route.metadata.get("landing_visible") is True
        or str(route.metadata.get("display_status", "")) in visible_statuses
    ]


def _build_transmission_scenario_routes(
    scenarios: list[TransmissionScenario],
) -> list[MapOverlayRoute]:
    routes: list[MapOverlayRoute] = []
    for fallback_index, scenario in enumerate(scenarios, start=1):
        if scenario.status != "active" or scenario.route is None:
            continue
        scenario_order = _transmission_scenario_order(
            scenario,
            fallback_index=fallback_index,
        )
        scenario_color = _transmission_scenario_color_for_scenario(
            scenario,
            fallback_index=fallback_index,
        )
        route_points = [
            MapOverlayPoint(
                overlay_id=f"transmission-route-point:{scenario.scenario_route_id}:{point.point_id}",
                label=point.label,
                kind="route_point",
                latitude=point.latitude,
                longitude=point.longitude,
                elevation_m=None,
                elevation_source="not_queried",
                status="selected",
                source=scenario.route.source,
                metadata={
                    "transmission_scenario_id": scenario.scenario_route_id,
                    "scenario_order": scenario_order,
                    "scenario_color": scenario_color,
                    "node_id": point.point_id,
                    "selection_role": "route",
                },
            )
            for point in scenario.route.waypoints
        ]
        routes.append(
            MapOverlayRoute(
                overlay_id=f"transmission-route:{scenario.scenario_route_id}",
                label=scenario.label,
                route_id=scenario.route.route_id,
                candidate_id=scenario.scenario_route_id,
                rank=None,
                points=route_points,
                total_distance_km=scenario.route.total_distance_km,
                estimated_cost=scenario.route.estimated_cost,
                source=scenario.route.source,
                metadata={
                    "landing_visible": True,
                    "display_status": "active_simulation",
                    "transmission_scenario_id": scenario.scenario_route_id,
                    "scenario_order": scenario_order,
                    "scenario_color": scenario_color,
                    "requested_transfer_mw": scenario.requested_transfer_mw,
                    "used_line_ids": list(scenario.used_line_ids),
                    "path_node_ids": list(scenario.path_node_ids),
                },
            )
        )
    return routes


def _build_mock_grid_points() -> list[MapOverlayPoint]:
    points: list[MapOverlayPoint] = []
    for plant in _DEFAULT_POWER_PLANTS:
        points.append(
            MapOverlayPoint(
                overlay_id=f"plant:{plant['id']}",
                label=str(plant["label"]),
                kind="power_plant",
                latitude=float(plant["latitude"]),
                longitude=float(plant["longitude"]),
                elevation_m=None,
                elevation_source="not_queried",
                status="normal",
                source="manual",
                metadata={
                    "asset_type": "power_plant",
                    "default_asset": True,
                    "capacity_mw": float(plant["capacity_mw"]),
                },
            )
        )
    for tower in _DEFAULT_TRANSMISSION_TOWERS:
        points.append(
            MapOverlayPoint(
                overlay_id=f"tower:{tower['id']}",
                label=str(tower["label"]),
                kind="transmission_tower",
                latitude=float(tower["latitude"]),
                longitude=float(tower["longitude"]),
                elevation_m=None,
                elevation_source="not_queried",
                status="normal",
                source="manual",
                metadata={
                    "asset_type": "transmission_tower",
                    "default_asset": True,
                    "voltage_kv": 345.0,
                },
            )
        )
    return points


def _extract_clicked_point(map_data: dict[str, Any] | None) -> MapOverlayPoint | None:
    if not isinstance(map_data, dict):
        return None
    clicked = map_data.get("last_object_clicked")
    capture_source = "folium_object_click"
    if not isinstance(clicked, dict):
        clicked = map_data.get("last_clicked")
        capture_source = "folium_click"
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

    metadata: dict[str, object] = {"capture_source": capture_source}
    object_tooltip = map_data.get("last_object_clicked_tooltip")
    if isinstance(object_tooltip, str) and object_tooltip.strip():
        metadata["object_tooltip"] = object_tooltip.strip()
    metadata.update(_nearest_place_metadata(lat, lon))
    nearest_place_name = metadata.get("nearest_place_name")
    label = (
        f"{nearest_place_name} 선택 지점"
        if isinstance(nearest_place_name, str) and nearest_place_name.strip()
        else "선택 지점"
    )

    return MapOverlayPoint(
        overlay_id="map-click:last",
        label=label,
        kind="install_point",
        latitude=lat,
        longitude=lon,
        elevation_m=None,
        coordinate_system="EPSG:4326",
        elevation_source="not_queried",
        status="selected",
        source="manual",
        metadata=metadata,
    )


def _nearest_place_metadata(latitude: float, longitude: float) -> dict[str, object]:
    try:
        return GeoPlaceService().find_nearest_place(latitude, longitude).to_metadata()
    except Exception as exc:  # noqa: BLE001
        return {"nearest_place_lookup_error": str(exc)}


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
    metadata: dict[str, object] = {
        "source_overlay_id": selected_point.overlay_id,
        "coordinate_status": "xy_only",
        "suggested_label": _suggest_installation_name(kind, selected_point),
    }
    for key, value in selected_point.metadata.items():
        if key.startswith("nearest_place"):
            metadata[key] = value

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
        metadata=metadata,
    )


def _installation_to_overlay_point(installation: InstallationPoint) -> MapOverlayPoint:
    metadata: dict[str, object] = dict(installation.metadata)
    metadata.update(
        {
            "installation_id": installation.installation_id,
            "capacity_mw": installation.capacity_mw,
            "voltage_kv": installation.voltage_kv,
            "notes": installation.notes,
        }
    )
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
        metadata=metadata,
    )


def _format_nearest_place(point: MapOverlayPoint) -> str:
    place_name = point.metadata.get("nearest_place_name")
    if not isinstance(place_name, str) or not place_name.strip():
        return ""

    province = point.metadata.get("nearest_place_province")
    location = (
        f"{province} {place_name}".strip()
        if isinstance(province, str) and province.strip()
        else place_name.strip()
    )
    distance = point.metadata.get("nearest_place_distance_km")
    if isinstance(distance, (float, int)):
        return f"{location} ({distance:.1f} km)"
    return location


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


def _dedupe_points(points: list[MapOverlayPoint]) -> list[MapOverlayPoint]:
    deduped: dict[str, MapOverlayPoint] = {}
    for point in points:
        deduped[point.overlay_id] = point
    return list(deduped.values())


if __name__ == "__main__":
    main()
