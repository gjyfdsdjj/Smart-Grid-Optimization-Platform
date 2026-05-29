# Streamlit 기반 SGOP 애플리케이션의 진입점이다.
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from src.config.settings import settings
from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.loaders import load_grid_dataset_or_default
from src.data.schemas import (
    GridDataset,
    GridImprovementProposal,
    InstallationMode,
    InstallationPoint,
    InstallationTargetKind,
    LineStatus,
    MapOverlayLine,
    MapOverlayPoint,
    MapOverlayResult,
    MapOverlayRoute,
    MonitoringResult,
    PredictionResult,
    RerouteCandidate,
    ScenarioContext,
    StressAnalysisResult,
    SuggestedGridNode,
    TransmissionScenario,
    TransmissionScenarioStatus,
)
from src.engine.stress.route_stress_analyzer import (
    DEFAULT_BASE_FLOW_RATIO,
    analyze_route_stress,
)
from src.engine.explain.xai_reporter import (
    build_line_xai_explanation,
    xai_explanation_to_metadata,
)
from src.engine.recommend.grid_improvement_recommender import (
    build_grid_improvement_proposal,
)
from src.services.map_overlay_service import MapOverlayService
from src.services.geo_place_service import GeoPlaceService
from src.services.monitoring_service import MonitoringService
from src.services.prediction_service import PredictionService
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
PREDICTION_ENABLED_STATE_KEY = "sgop_landing_prediction_enabled"
PREDICTION_MODEL_STATE_KEY = "sgop_landing_prediction_model"
PREDICTION_RESULT_STATE_KEY = "sgop_landing_prediction_result"
_PREDICTION_CACHE_STATE_KEY = "sgop_landing_prediction_cache"
SELECTED_GRID_OBJECT_STATE_KEY = "sgop_selected_grid_object"
GRID_IMPROVEMENT_PROPOSAL_STATE_KEY = "sgop_grid_improvement_proposal"
_GRID_IMPROVEMENT_PROPOSAL_CACHE_STATE_KEY = "sgop_grid_improvement_proposal_cache"
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
_PREDICTION_RAW_DIR = "data/raw"
_PREDICTION_MODEL_OPTIONS: tuple[str, ...] = (
    "Mock",
    "Baseline",
    "LSTM",
    "GNN",
    "Neural GNN(beta)",
    "LSTM+GNN",
    "LSTM+Neural GNN(beta)",
)
_PREDICTION_BRIEFING_CACHE_STATE_KEY = "sgop_landing_prediction_briefing_cache"
_PREDICTION_EXPECTED_SOURCE_BY_MODEL: dict[str, str] = {
    "Mock": "mock",
    "Baseline": "baseline",
    "LSTM": "lstm",
    "GNN": "gnn",
    "Neural GNN(beta)": "neural_gnn",
    "LSTM+GNN": "hybrid",
    "LSTM+Neural GNN(beta)": "hybrid_neural_gnn",
}
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
_STRESS_STATUS_BAR_COLORS: dict[str, str] = {
    "normal": "#16a34a",
    "warning": "#f59e0b",
    "critical": "#dc2626",
    "overload": "#7f1d1d",
    "bottleneck": "#ea580c",
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


@dataclass
class PredictionBriefingComparison:
    """Baseline과 현재 선택 Prediction 모델의 stress 반영 결과 비교."""

    baseline_result: PredictionResult
    selected_result: PredictionResult
    baseline_stress: StressAnalysisResult
    selected_stress: StressAnalysisResult
    selected_model_label: str
    summary_rows: list[dict[str, object]]
    line_delta_rows: list[dict[str, object]]
    warning: str = ""

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
    prediction_result, prediction_warning = _get_landing_prediction_result(
        scenario,
        load_scale=global_load_scale,
    )
    stress_analysis, stress_warning = _get_landing_stress_analysis(
        scenario,
        load_scale=global_load_scale,
        monitoring_result=monitoring_result,
        prediction_result=prediction_result,
    )
    prediction_comparison, prediction_comparison_warning = (
        _get_landing_prediction_briefing_comparison(
            scenario,
            load_scale=global_load_scale,
            monitoring_result=monitoring_result,
            selected_prediction_result=prediction_result,
            selected_stress_analysis=stress_analysis,
        )
    )
    selected_line_id = _selected_grid_object_line_id()
    improvement_proposal, improvement_warning = _get_landing_improvement_proposal(
        scenario,
        target_line_id=selected_line_id,
        stress_analysis=stress_analysis,
        load_scale=global_load_scale,
        monitoring_result=monitoring_result,
        prediction_result=prediction_result,
    )
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
    with st.sidebar:
        st.divider()
        _render_prediction_control_panel(
            prediction_result,
        )
        st.divider()
        _render_stress_summary_panel(stress_analysis)
    _render_operation_status_bar(
        interaction_mode=interaction_mode,
        stress_analysis=stress_analysis,
        prediction_result=prediction_result,
        improvement_proposal=improvement_proposal,
    )
    _render_map_layer_legend()
    overlay_points = _attach_node_stress_metadata(
        _build_landing_points(grid_overlay, service_overlay)
        + _build_improvement_suggested_points(improvement_proposal),
        stress_analysis,
    )
    overlay_lines = _attach_improvement_metadata(
        _attach_stress_metadata(
            grid_overlay.lines if grid_overlay is not None else [],
            stress_analysis,
        ),
        improvement_proposal,
    )
    overlay_routes = (
        _build_landing_routes(service_overlay)
        + _build_transmission_scenario_routes(_landing_transmission_scenarios())
        + _build_improvement_reroute_routes(improvement_proposal)
    )
    landing_overlay = MapOverlayService().build_landing_overlay(
        scenario=scenario,
        created_at=scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0),
        points=overlay_points,
        lines=overlay_lines,
        routes=overlay_routes,
        warnings=[
            warning
            for warning in [
                grid_warning,
                overlay_warning,
                monitoring_warning,
                prediction_warning,
                stress_warning,
                prediction_comparison_warning,
                improvement_warning,
            ]
            if warning
        ],
        map_capability=map_capability,
    )

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

    _render_operation_console_panels(
        stress_analysis=stress_analysis,
        improvement_proposal=improvement_proposal,
        prediction_comparison=prediction_comparison,
    )


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
            .sgop-console-kpis {
                display: grid;
                gap: 0.55rem;
                grid-template-columns: repeat(6, minmax(0, 1fr));
                margin: 0.55rem 0 0.45rem;
            }
            .sgop-console-kpi {
                background: #ffffff;
                border: 1px solid rgba(15, 23, 42, 0.12);
                border-radius: 8px;
                min-width: 0;
                padding: 0.48rem 0.58rem;
            }
            .sgop-console-kpi-label {
                color: #64748b;
                font-size: 0.72rem;
                line-height: 1.1;
                margin-bottom: 0.18rem;
                white-space: nowrap;
            }
            .sgop-console-kpi-value {
                color: #0f172a;
                font-size: 0.98rem;
                font-weight: 700;
                line-height: 1.15;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .sgop-layer-legend {
                align-items: center;
                border-bottom: 1px solid rgba(15, 23, 42, 0.08);
                color: #334155;
                display: flex;
                flex-wrap: wrap;
                font-size: 0.78rem;
                gap: 0.58rem;
                margin: 0 0 0.45rem;
                padding: 0 0 0.45rem;
            }
            .sgop-layer-legend-item {
                align-items: center;
                display: inline-flex;
                gap: 0.25rem;
                white-space: nowrap;
            }
            .sgop-layer-swatch {
                border-radius: 999px;
                display: inline-block;
                height: 0.62rem;
                width: 1.25rem;
            }
            div[data-testid="stIFrame"] {
                height: calc(100vh - 9.6rem) !important;
                min-height: 640px;
            }
            div[data-testid="stIFrame"] iframe {
                height: calc(100vh - 9.6rem) !important;
                min-height: 640px;
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
                .sgop-console-kpis {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
                div[data-testid="stIFrame"],
                div[data-testid="stIFrame"] iframe {
                    height: calc(100vh - 13.2rem) !important;
                    min-height: 520px;
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


def _render_operation_status_bar(
    *,
    interaction_mode: str,
    stress_analysis: StressAnalysisResult | None,
    prediction_result: PredictionResult | None,
    improvement_proposal: GridImprovementProposal | None,
) -> None:
    items = _operation_status_items(
        interaction_mode=interaction_mode,
        stress_analysis=stress_analysis,
        prediction_result=prediction_result,
        improvement_proposal=improvement_proposal,
    )
    item_html = "".join(
        '<div class="sgop-console-kpi">'
        f'<div class="sgop-console-kpi-label">{escape(label)}</div>'
        f'<div class="sgop-console-kpi-value">{escape(value)}</div>'
        "</div>"
        for label, value in items
    )
    st.markdown(
        f'<div class="sgop-console-kpis">{item_html}</div>',
        unsafe_allow_html=True,
    )


def _operation_status_items(
    *,
    interaction_mode: str,
    stress_analysis: StressAnalysisResult | None,
    prediction_result: PredictionResult | None,
    improvement_proposal: GridImprovementProposal | None,
) -> list[tuple[str, str]]:
    metrics = _stress_summary_metrics(stress_analysis) if stress_analysis is not None else {}
    selected_line_id = _selected_grid_object_line_id() or "선택 없음"
    prediction_label = "반영" if prediction_result is not None else "미반영"
    improvement_label = (
        f"{len(improvement_proposal.reroute_candidates)}개 우회"
        if improvement_proposal is not None
        else "선로 선택 전"
    )
    return [
        ("작업 모드", _INTERACTION_MODE_LABEL.get(interaction_mode, interaction_mode)),
        ("활성 시나리오", str(metrics.get("활성 시나리오", 0))),
        ("병목 선로", str(metrics.get("병목 선로", 0))),
        ("위험/과부하", str(metrics.get("위험/과부하", 0))),
        ("최대 이용률", str(metrics.get("최대 이용률", "-"))),
        ("선택 선로", selected_line_id),
        ("Prediction", prediction_label),
        ("개선안", improvement_label),
    ]


def _render_map_layer_legend() -> None:
    item_html = "".join(
        '<span class="sgop-layer-legend-item">'
        f'<span class="sgop-layer-swatch" style="background:{escape(color)};{escape(style)}"></span>'
        f"{escape(label)}"
        "</span>"
        for label, color, style in _map_layer_legend_items()
    )
    st.markdown(
        f'<div class="sgop-layer-legend">{item_html}</div>',
        unsafe_allow_html=True,
    )


def _map_layer_legend_items() -> list[tuple[str, str, str]]:
    return [
        ("선로 <50%", "#64748b", ""),
        ("선로 50-70%", "#22c55e", ""),
        ("선로 70-85%", "#f59e0b", ""),
        ("선로 85-100%", "#f97316", ""),
        ("선로 100-125%", "#dc2626", ""),
        ("선로 125%+", "#7f1d1d", ""),
        ("활성 송전 시나리오", "#dc2626", ""),
        ("선택 선로", "#7c3aed", ""),
        ("우회 경로 후보", "#2563eb", "border:2px dashed #2563eb;background:#ffffff;"),
        ("신규 송전탑 후보", "#34d399", ""),
    ]


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
    if PREDICTION_ENABLED_STATE_KEY not in st.session_state:
        st.session_state[PREDICTION_ENABLED_STATE_KEY] = False
    if PREDICTION_MODEL_STATE_KEY not in st.session_state:
        st.session_state[PREDICTION_MODEL_STATE_KEY] = "Baseline"
    if PREDICTION_RESULT_STATE_KEY not in st.session_state:
        st.session_state[PREDICTION_RESULT_STATE_KEY] = None
    if SELECTED_GRID_OBJECT_STATE_KEY not in st.session_state:
        st.session_state[SELECTED_GRID_OBJECT_STATE_KEY] = {}
    if GRID_IMPROVEMENT_PROPOSAL_STATE_KEY not in st.session_state:
        st.session_state[GRID_IMPROVEMENT_PROPOSAL_STATE_KEY] = None


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
        max_value=2.0,
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


def _render_prediction_control_panel(
    prediction_result: PredictionResult | None,
) -> None:
    st.subheader("Prediction")
    st.checkbox(
        "예측 부하 반영",
        key=PREDICTION_ENABLED_STATE_KEY,
    )
    _normalize_prediction_model_state()
    st.selectbox(
        "예측 모델",
        options=list(_PREDICTION_MODEL_OPTIONS),
        key=PREDICTION_MODEL_STATE_KEY,
    )

    if prediction_result is None:
        st.caption("예측 부하 미반영")
        return

    st.metric("미래 위험 선로", len(prediction_result.risk_lines))
    st.caption(f"source: {prediction_result.source}")
    if prediction_result.fallback.enabled:
        st.caption(f"fallback: {prediction_result.fallback.mode}")


def _render_stress_detail_panel(
    stress_analysis: StressAnalysisResult | None,
) -> None:
    _render_line_utilization_panel(stress_analysis)
    _render_risk_line_panel(stress_analysis)


def _render_operation_console_panels(
    *,
    stress_analysis: StressAnalysisResult | None,
    improvement_proposal: GridImprovementProposal | None,
    prediction_comparison: PredictionBriefingComparison | None,
) -> None:
    prediction_tab, improvement_tab, utilization_tab, risk_tab, scenario_tab = st.tabs(
        ["Prediction 비교", "개선안", "선로별 이용률", "위험/경고 선로", "시나리오/설치"]
    )
    with prediction_tab:
        _render_prediction_comparison_panel(prediction_comparison)
    with improvement_tab:
        _render_improvement_panel(improvement_proposal)
    with utilization_tab:
        _render_line_utilization_panel(stress_analysis)
    with risk_tab:
        _render_risk_line_panel(stress_analysis)
    with scenario_tab:
        _render_scenario_asset_panel()


def _render_prediction_comparison_panel(
    comparison: PredictionBriefingComparison | None,
) -> None:
    st.subheader("Prediction 비교")
    if comparison is None:
        st.info("예측 부하 반영을 켜고 Baseline 외 모델을 선택하면 비교 결과가 표시됩니다.")
        return

    st.caption(
        f"Baseline 기준 stress와 선택 모델({comparison.selected_model_label}) stress를 같은 부하 배율로 비교합니다."
    )
    if comparison.warning:
        st.warning(comparison.warning)

    st.dataframe(comparison.summary_rows, use_container_width=True, hide_index=True)

    if not comparison.line_delta_rows:
        st.info("Baseline과 선택 모델의 선로별 stress 차이가 없습니다.")
        return

    top_rows = comparison.line_delta_rows[:20]
    st.dataframe(top_rows, use_container_width=True, hide_index=True)
    _render_prediction_comparison_delta_chart(top_rows)


def _render_prediction_comparison_delta_chart(
    line_delta_rows: list[dict[str, object]],
) -> None:
    if not line_delta_rows:
        return

    max_abs_delta = max(abs(float(row["변화 pp"])) for row in line_delta_rows)
    x_limit = max(5.0, max_abs_delta * 1.18)
    fig = go.Figure(
        go.Bar(
            x=[float(row["변화 pp"]) for row in line_delta_rows],
            y=[str(row["구간"]) for row in line_delta_rows],
            customdata=[
                [
                    row["선로 ID"],
                    row["Baseline 이용률"],
                    row["선택 모델 이용률"],
                    row["Baseline 예측 MW"],
                    row["선택 예측 MW"],
                ]
                for row in line_delta_rows
            ],
            hovertemplate=(
                "구간: %{y}<br>"
                "선로 ID: %{customdata[0]}<br>"
                "이용률 변화: %{x:+.1f} pp<br>"
                "Baseline 이용률: %{customdata[1]}<br>"
                "선택 모델 이용률: %{customdata[2]}<br>"
                "Baseline 예측 추가: %{customdata[3]}<br>"
                "선택 모델 예측 추가: %{customdata[4]}<extra></extra>"
            ),
            marker_color=[
                "#16a34a" if float(row["변화 pp"]) < 0.0 else "#dc2626"
                if float(row["변화 pp"]) > 0.0
                else "#64748b"
                for row in line_delta_rows
            ],
            orientation="h",
            text=[f"{float(row['변화 pp']):+.1f} pp" for row in line_delta_rows],
            textposition="outside",
        )
    )
    fig.add_vline(x=0, line_color="#64748b", line_width=1)
    fig.update_layout(
        height=max(280, min(680, 110 + 30 * len(line_delta_rows))),
        margin={"l": 12, "r": 30, "t": 18, "b": 34},
        showlegend=False,
        xaxis={
            "range": [-x_limit, x_limit],
            "title": "Baseline 대비 이용률 변화 (percentage point)",
            "ticksuffix": " pp",
        },
        yaxis={
            "autorange": "reversed",
            "title": "",
        },
    )
    st.plotly_chart(fig, width="stretch")


def _render_line_utilization_panel(
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
        _render_line_utilization_chart(utilization_rows)
    else:
        st.info("표시할 선로가 없습니다.")


def _render_risk_line_panel(
    stress_analysis: StressAnalysisResult | None,
) -> None:
    st.subheader("위험/경고 선로")
    if stress_analysis is None:
        st.info("선로 stress 결과가 없습니다.")
        return

    risk_rows = _risk_line_table_rows(stress_analysis)
    if risk_rows:
        st.dataframe(risk_rows, use_container_width=True, hide_index=True)
    else:
        st.success("위험/경고 선로가 없습니다.")


def _render_scenario_asset_panel() -> None:
    scenario_rows = _transmission_scenario_table_rows(_landing_transmission_scenarios())
    st.subheader("송전 시나리오 목록")
    if scenario_rows:
        st.dataframe(scenario_rows, use_container_width=True, hide_index=True)
    else:
        st.info("지도에서 시작 노드와 종료 노드를 선택해 송전 시나리오를 생성하세요.")
    _render_installation_table()


def _render_improvement_panel(
    proposal: GridImprovementProposal | None,
) -> None:
    if proposal is None:
        st.subheader("개선안 제안")
        st.info("병목 또는 위험 선로를 클릭하면 xAI 설명과 우회 경로/신규 송전탑 개선안이 표시됩니다.")
        return

    st.subheader("개선안 제안")
    st.caption(proposal.summary or f"{proposal.target_line_id} 개선안")

    if proposal.warnings:
        with st.expander("개선안 생성 참고사항"):
            for warning in proposal.warnings:
                st.caption(warning)

    if proposal.reroute_candidates:
        st.markdown("**우회 경로 후보**")
        st.dataframe(
            _reroute_candidate_table_rows(proposal.reroute_candidates),
            use_container_width=True,
            hide_index=True,
        )
        for candidate in proposal.reroute_candidates[:2]:
            with st.container(border=True):
                st.markdown(f"**{candidate.scenario_label or candidate.scenario_route_id}**")
                st.caption(candidate.rationale)
                if st.button(
                    "우회 경로 적용",
                    key=f"apply-reroute:{proposal.proposal_id}:{candidate.candidate_id}",
                    use_container_width=True,
                ):
                    if _apply_reroute_candidate(candidate):
                        st.rerun()
    else:
        st.info("현재 선택 선로를 회피하는 대체 경로 후보를 찾지 못했습니다.")

    if proposal.suggested_nodes:
        st.markdown("**신규 송전탑 후보**")
        st.dataframe(
            _suggested_node_table_rows(proposal.suggested_nodes),
            use_container_width=True,
            hide_index=True,
        )
        for suggested_node in proposal.suggested_nodes[:2]:
            with st.container(border=True):
                st.markdown(f"**{suggested_node.label}**")
                st.caption(suggested_node.reason)
                if st.button(
                    "신규 송전탑 후보 승인",
                    key=f"apply-node:{proposal.proposal_id}:{suggested_node.suggested_node_id}",
                    use_container_width=True,
                ):
                    if _apply_suggested_grid_node(suggested_node):
                        st.rerun()


def _reroute_candidate_table_rows(
    candidates: list[RerouteCandidate],
) -> list[dict[str, object]]:
    return [
        {
            "후보 ID": candidate.candidate_id,
            "대상 시나리오": candidate.scenario_label or candidate.scenario_route_id,
            "회피 선로": ", ".join(candidate.avoided_line_ids),
            "목표 이용률 전": _format_percent(candidate.before_target_utilization),
            "목표 이용률 후": _format_percent(candidate.after_target_utilization),
            "최대 이용률 후": _format_percent(candidate.after_max_utilization),
            "병목 수": f"{candidate.before_bottleneck_line_count} -> {candidate.after_bottleneck_line_count}",
            "위험 수": f"{candidate.before_critical_line_count} -> {candidate.after_critical_line_count}",
            "추가 거리": _format_optional_km(candidate.added_distance_km),
            "점수": round(float(candidate.score), 2),
        }
        for candidate in candidates
    ]


def _suggested_node_table_rows(
    suggested_nodes: list[SuggestedGridNode],
) -> list[dict[str, object]]:
    return [
        {
            "후보 ID": node.suggested_node_id,
            "이름": node.label,
            "x": f"{node.longitude:.6f}",
            "y": f"{node.latitude:.6f}",
            "전압": _format_optional_kv(node.voltage_kv),
            "권장 용량": _format_optional_mw(node.capacity_mw),
            "예상 비용": f"{node.install_cost_billion:.2f}십억",
            "완화 선로": ", ".join(node.relief_line_ids),
            "예상 이용률 변화": _format_optional_percent(node.expected_utilization_delta),
        }
        for node in suggested_nodes
    ]


def _transmission_scenario_table_rows(
    scenarios: list[TransmissionScenario],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for fallback_index, scenario in enumerate(scenarios, start=1):
        rows.append(
            {
                "순번": _transmission_scenario_order(
                    scenario,
                    fallback_index=fallback_index,
                ),
                "상태": scenario.status,
                "시나리오": scenario.label,
                "시작": scenario.start_node_name or scenario.start_node_id,
                "종료": scenario.end_node_name or scenario.end_node_id,
                "송전량 MW": round(float(scenario.requested_transfer_mw), 2),
                "경로 노드 수": len(scenario.path_node_ids),
                "사용 선로 수": len(scenario.used_line_ids),
                "경로 source": scenario.source,
                "생성 시각": scenario.created_at.isoformat() if scenario.created_at else "",
            }
        )
    return rows


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


def _line_utilization_chart_rows(
    utilization_rows: list[dict[str, object]],
    *,
    limit: int = 20,
) -> list[dict[str, object]]:
    chart_rows: list[dict[str, object]] = []
    for row in utilization_rows[:limit]:
        status = str(row.get("상태", "normal"))
        is_bottleneck = str(row.get("병목", "")) == "Y"
        color_key = "bottleneck" if is_bottleneck and status == "normal" else status
        utilization = float(row.get("이용률", 0.0))
        chart_rows.append(
            {
                "선로 ID": str(row.get("선로 ID", "")),
                "표시명": _line_utilization_display_label(row),
                "이용률": utilization,
                "이용률 % 값": round(utilization * 100.0, 2),
                "총 흐름 MW": float(row.get("총 흐름 MW", 0.0)),
                "용량 MW": float(row.get("용량 MW", 0.0)),
                "상태": status,
                "병목": is_bottleneck,
                "막대 색상": _STRESS_STATUS_BAR_COLORS.get(
                    color_key,
                    _STRESS_STATUS_BAR_COLORS["normal"],
                ),
            }
        )
    return chart_rows


def _line_utilization_display_label(row: dict[str, object]) -> str:
    from_label = str(row.get("From", "")).strip()
    to_label = str(row.get("To", "")).strip()
    if from_label and to_label:
        return f"{from_label}->{to_label}"
    return str(row.get("선로 ID", "")).strip()


def _render_line_utilization_chart(
    utilization_rows: list[dict[str, object]],
) -> None:
    chart_rows = _line_utilization_chart_rows(utilization_rows)
    if not chart_rows:
        return

    max_utilization_percent = max(float(row["이용률 % 값"]) for row in chart_rows)
    x_range_max = max(105.0, max_utilization_percent * 1.08)
    fig = go.Figure(
        go.Bar(
            x=[row["이용률 % 값"] for row in chart_rows],
            y=[row["표시명"] for row in chart_rows],
            customdata=[
                [
                    row["선로 ID"],
                    row["상태"],
                    row["총 흐름 MW"],
                    row["용량 MW"],
                    "Y" if row["병목"] else "",
                ]
                for row in chart_rows
            ],
            hovertemplate=(
                "구간: %{y}<br>"
                "선로 ID: %{customdata[0]}<br>"
                "이용률: %{x:.1f}%<br>"
                "상태: %{customdata[1]}<br>"
                "총 흐름: %{customdata[2]:.2f} MW<br>"
                "용량: %{customdata[3]:.2f} MW<br>"
                "병목: %{customdata[4]}<extra></extra>"
            ),
            marker_color=[row["막대 색상"] for row in chart_rows],
            orientation="h",
            text=[f"{float(row['이용률 % 값']):.1f}%" for row in chart_rows],
            textposition="outside",
        )
    )
    fig.add_vline(x=80, line_color="#f59e0b", line_dash="dot", line_width=1)
    fig.add_vline(x=95, line_color="#dc2626", line_dash="dot", line_width=1)
    fig.update_layout(
        height=max(280, min(680, 110 + 30 * len(chart_rows))),
        margin={"l": 12, "r": 30, "t": 18, "b": 34},
        showlegend=False,
        xaxis={
            "range": [0, x_range_max],
            "title": "누적 이용률 (%)",
            "ticksuffix": "%",
        },
        yaxis={
            "autorange": "reversed",
            "title": "",
        },
    )
    st.plotly_chart(fig, width="stretch")


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
        "예측 추가 MW": round(float(stress.predicted_flow_mw), 2),
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


def _format_optional_km(value: object) -> str:
    number = _first_number(value)
    return f"{number:.2f} km" if number is not None else ""


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
    return min(2.0, max(0.6, load_scale))


def _normalize_global_load_scale_state() -> float:
    load_scale = _get_global_load_scale()
    st.session_state[GLOBAL_LOAD_SCALE_STATE_KEY] = load_scale
    return load_scale


def _normalize_prediction_model_state() -> str:
    model_source = str(st.session_state.get(PREDICTION_MODEL_STATE_KEY, "Baseline"))
    if model_source not in _PREDICTION_MODEL_OPTIONS:
        model_source = "Baseline"
        st.session_state[PREDICTION_MODEL_STATE_KEY] = model_source
    return model_source


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
    _invalidate_landing_analysis_caches()


def _apply_reroute_candidate(candidate: RerouteCandidate) -> bool:
    if candidate.route is None:
        return False

    scenarios = list(st.session_state.get(TRANSMISSION_SCENARIOS_STATE_KEY, []))
    updated_scenarios: list[object] = []
    changed = False
    for item in scenarios:
        if not isinstance(item, TransmissionScenario):
            updated_scenarios.append(item)
            continue
        if item.scenario_route_id != candidate.scenario_route_id:
            updated_scenarios.append(item)
            continue

        updated_scenarios.append(
            replace(
                item,
                route=candidate.route,
                path_node_ids=list(candidate.rerouted_path_node_ids),
                used_line_ids=list(candidate.rerouted_line_ids),
                source=candidate.route.source,
                status="active",
                metadata={
                    **item.metadata,
                    "applied_reroute_candidate_id": candidate.candidate_id,
                    "applied_reroute_target_line_id": candidate.target_line_id,
                    "reroute_before_target_utilization": candidate.before_target_utilization,
                    "reroute_after_target_utilization": candidate.after_target_utilization,
                },
            )
        )
        changed = True

    if not changed:
        return False

    st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = updated_scenarios
    st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
        f"{candidate.scenario_label or candidate.scenario_route_id} 우회 경로를 적용했습니다."
    )
    _invalidate_landing_analysis_caches()
    return True


def _apply_suggested_grid_node(suggested_node: SuggestedGridNode) -> bool:
    installations = list(st.session_state.get("sgop_landing_installations", []))
    if any(
        isinstance(installation, InstallationPoint)
        and installation.metadata.get("suggested_node_id") == suggested_node.suggested_node_id
        for installation in installations
    ):
        st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
            f"{suggested_node.label} 후보는 이미 승인되어 있습니다."
        )
        return False

    installations.append(_suggested_node_to_installation_point(suggested_node))
    st.session_state.sgop_landing_installations = installations
    _rebuild_active_transmission_scenario_routes(load_scale=_get_global_load_scale())
    st.session_state[TRANSMISSION_SELECTION_WARNING_STATE_KEY] = (
        f"{suggested_node.label} 후보를 설치 검토 지점으로 추가했습니다."
    )
    _invalidate_landing_analysis_caches()
    return True


def _suggested_node_to_installation_point(
    suggested_node: SuggestedGridNode,
) -> InstallationPoint:
    created_at = datetime.now().replace(microsecond=0)
    return InstallationPoint(
        installation_id=f"suggested-{suggested_node.suggested_node_id.lower()}",
        label=suggested_node.label,
        kind="transmission_tower",
        latitude=suggested_node.latitude,
        longitude=suggested_node.longitude,
        mode="review",
        elevation_m=suggested_node.elevation_m,
        coordinate_system=suggested_node.coordinate_system,
        elevation_source=suggested_node.elevation_source,
        capacity_mw=None,
        voltage_kv=suggested_node.voltage_kv,
        notes=suggested_node.reason,
        created_at=created_at,
        metadata={
            **suggested_node.metadata,
            "suggested_node_id": suggested_node.suggested_node_id,
            "target_line_id": suggested_node.target_line_id,
            "relief_line_ids": list(suggested_node.relief_line_ids),
            "recommended_capacity_mw": suggested_node.capacity_mw,
            "install_cost_billion": suggested_node.install_cost_billion,
            "source": "grid_improvement_proposal",
        },
    )


def _rebuild_active_transmission_scenario_routes(
    *,
    load_scale: float,
) -> None:
    scenarios = list(st.session_state.get(TRANSMISSION_SCENARIOS_STATE_KEY, []))
    active_scenarios = [
        scenario
        for scenario in scenarios
        if isinstance(scenario, TransmissionScenario) and scenario.status == "active"
    ]
    if not active_scenarios:
        return

    created_at = datetime.now().replace(minute=0, second=0, microsecond=0)
    dataset = load_grid_dataset_or_default(
        user_installations=_landing_installations(),
        created_at=created_at,
        load_scale=load_scale,
    )
    service = TransmissionScenarioService()
    updated_scenarios: list[object] = []
    for item in scenarios:
        if not isinstance(item, TransmissionScenario) or item.status != "active":
            updated_scenarios.append(item)
            continue
        try:
            route = service.build_route_between_nodes(
                start_node_id=item.start_node_id,
                end_node_id=item.end_node_id,
                grid_dataset=dataset,
                load_scale=load_scale,
                route_id=item.route.route_id if item.route is not None else "",
            )
            updated = service.attach_route_to_scenario(
                replace(
                    item,
                    metadata={
                        **item.metadata,
                        "rebuilt_after_grid_improvement": True,
                    },
                ),
                route=route,
                grid_dataset=dataset,
            )
            updated_scenarios.append(updated)
        except Exception as exc:  # noqa: BLE001
            updated_scenarios.append(
                replace(
                    item,
                    warnings=list(item.warnings) + [
                        f"신규 송전탑 승인 후 경로 재계산 실패: {exc}"
                    ],
                )
            )
    st.session_state[TRANSMISSION_SCENARIOS_STATE_KEY] = updated_scenarios


def _invalidate_landing_analysis_caches() -> None:
    for key in [
        _STRESS_ANALYSIS_CACHE_STATE_KEY,
        _GRID_IMPROVEMENT_PROPOSAL_CACHE_STATE_KEY,
        "sgop_landing_grid_overlay",
        "sgop_landing_service_overlay",
    ]:
        st.session_state.pop(key, None)


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
        _invalidate_landing_analysis_caches()
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


def _get_landing_prediction_result(
    scenario: ScenarioContext,
    *,
    load_scale: float,
) -> tuple[PredictionResult | None, str]:
    if not bool(st.session_state.get(PREDICTION_ENABLED_STATE_KEY, False)):
        st.session_state[PREDICTION_RESULT_STATE_KEY] = None
        return None, ""

    model_source = _normalize_prediction_model_state()
    installations = _landing_installations()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    cache_key = (
        scenario.scenario_id,
        created_at.isoformat(),
        round(load_scale, 4),
        model_source,
        _installations_cache_key(installations),
    )
    cached = st.session_state.get(_PREDICTION_CACHE_STATE_KEY)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        st.session_state[PREDICTION_RESULT_STATE_KEY] = cached[1]
        return cached[1], cached[2]

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        result = _run_landing_prediction_with_fallback(
            PredictionService(),
            model_source=model_source,
            scenario=scenario,
            grid_dataset=dataset,
            load_scale=load_scale,
            created_at=created_at,
        )
        result.metadata["landing_console_enabled"] = True
        result.metadata["landing_model_source"] = model_source
        warning = _prediction_warning_for_result(model_source, result)
        st.session_state[PREDICTION_RESULT_STATE_KEY] = result
        st.session_state[_PREDICTION_CACHE_STATE_KEY] = (cache_key, result, warning)
        return result, warning
    except Exception as exc:  # noqa: BLE001
        warning = f"Prediction 결과를 만들지 못했습니다. 원인: {exc}"
        st.session_state[PREDICTION_RESULT_STATE_KEY] = None
        st.session_state[_PREDICTION_CACHE_STATE_KEY] = (cache_key, None, warning)
        return None, warning


def _run_landing_prediction_with_fallback(
    service: PredictionService,
    *,
    model_source: str,
    scenario: ScenarioContext,
    grid_dataset: GridDataset,
    load_scale: float,
    created_at: datetime,
) -> PredictionResult:
    if model_source == "Mock":
        return service.run_mock_prediction(
            load_scale=load_scale,
            created_at=created_at,
            scenario=scenario,
            grid_dataset=grid_dataset,
        )

    try:
        if model_source == "Baseline":
            return service.run_baseline_prediction(
                raw_dir=_PREDICTION_RAW_DIR,
                load_scale=load_scale,
                forecast_start=created_at,
                scenario=scenario,
                grid_dataset=grid_dataset,
            )
        if model_source == "GNN":
            return service.run_gnn_prediction(
                raw_dir=_PREDICTION_RAW_DIR,
                load_scale=load_scale,
                forecast_start=created_at,
                scenario=scenario,
                grid_dataset=grid_dataset,
            )
        if model_source == "Neural GNN(beta)":
            return service.run_neural_gnn_prediction(
                raw_dir=_PREDICTION_RAW_DIR,
                load_scale=load_scale,
                forecast_start=created_at,
                scenario=scenario,
                retrain=False,
                grid_dataset=grid_dataset,
            )
        if model_source == "LSTM+GNN":
            return service.run_hybrid_prediction(
                raw_dir=_PREDICTION_RAW_DIR,
                load_scale=load_scale,
                forecast_start=created_at,
                scenario=scenario,
                retrain=False,
                grid_dataset=grid_dataset,
            )
        if model_source == "LSTM+Neural GNN(beta)":
            return service.run_hybrid_neural_gnn_prediction(
                raw_dir=_PREDICTION_RAW_DIR,
                load_scale=load_scale,
                forecast_start=created_at,
                scenario=scenario,
                retrain=False,
                grid_dataset=grid_dataset,
            )

        return service.run_lstm_prediction(
            raw_dir=_PREDICTION_RAW_DIR,
            load_scale=load_scale,
            forecast_start=created_at,
            scenario=scenario,
            retrain=False,
            grid_dataset=grid_dataset,
        )
    except Exception as exc:  # noqa: BLE001
        fallback_result = service.run_mock_prediction(
            load_scale=load_scale,
            created_at=created_at,
            scenario=scenario,
            grid_dataset=grid_dataset,
        )
        fallback_result.summary = (
            f"{model_source} 예측 실패로 mock 결과를 사용합니다. "
            f"{fallback_result.summary}"
        )
        fallback_result.warnings.insert(
            0,
            f"{model_source} 예측 실패 -> mock fallback 전환. 원인: {exc}",
        )
        fallback_result.fallback.reason = (
            f"{model_source} 예측이 실패해 mock 패턴 예측 결과를 사용합니다. 원인: {exc}"
        )
        fallback_result.metadata["landing_prediction_fallback_error"] = str(exc)
        fallback_result.metadata["landing_requested_model_source"] = model_source
        return fallback_result


def _prediction_warning_for_result(
    model_source: str,
    result: PredictionResult,
) -> str:
    if model_source == "Mock":
        return ""
    if result.fallback.enabled:
        return f"Prediction {model_source} fallback 결과를 stress 분석에 반영합니다."

    expected_source = _PREDICTION_EXPECTED_SOURCE_BY_MODEL.get(model_source)
    if expected_source and result.source != expected_source:
        return (
            f"Prediction {model_source} 대신 {result.source} 결과를 stress 분석에 반영합니다."
        )
    return ""


def _get_landing_prediction_briefing_comparison(
    scenario: ScenarioContext,
    *,
    load_scale: float,
    monitoring_result: MonitoringResult | None,
    selected_prediction_result: PredictionResult | None,
    selected_stress_analysis: StressAnalysisResult | None,
) -> tuple[PredictionBriefingComparison | None, str]:
    if selected_prediction_result is None or selected_stress_analysis is None:
        st.session_state[_PREDICTION_BRIEFING_CACHE_STATE_KEY] = None
        return None, ""

    selected_model_label = str(
        selected_prediction_result.metadata.get(
            "landing_model_source",
            st.session_state.get(PREDICTION_MODEL_STATE_KEY, selected_prediction_result.source),
        )
    )
    installations = _landing_installations()
    transmission_scenarios = _landing_transmission_scenarios()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    cache_key = (
        scenario.scenario_id,
        created_at.isoformat(),
        round(load_scale, 4),
        selected_model_label,
        _installations_cache_key(installations),
        _transmission_scenarios_cache_key(transmission_scenarios),
        _monitoring_result_cache_key(monitoring_result),
        _prediction_result_cache_key(selected_prediction_result),
        _stress_analysis_cache_key(selected_stress_analysis),
    )
    cached = st.session_state.get(_PREDICTION_BRIEFING_CACHE_STATE_KEY)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        return cached[1], cached[2]

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        baseline_prediction: PredictionResult
        baseline_stress: StressAnalysisResult
        warning = ""
        if (
            selected_model_label == "Baseline"
            and selected_prediction_result.source == "baseline"
        ):
            baseline_prediction = selected_prediction_result
            baseline_stress = selected_stress_analysis
        else:
            baseline_prediction = _run_landing_prediction_with_fallback(
                PredictionService(),
                model_source="Baseline",
                scenario=scenario,
                grid_dataset=dataset,
                load_scale=load_scale,
                created_at=created_at,
            )
            baseline_prediction.metadata["landing_console_enabled"] = True
            baseline_prediction.metadata["landing_model_source"] = "Baseline"
            baseline_predicted_flow = _prediction_flow_by_line(
                baseline_prediction,
                grid_dataset=dataset,
                monitoring_result=monitoring_result,
                load_scale=load_scale,
            )
            baseline_stress = analyze_route_stress(
                scenario=scenario,
                grid_dataset=dataset,
                transmission_scenarios=transmission_scenarios,
                load_scale=load_scale,
                created_at=created_at,
                monitoring_result=monitoring_result,
                predicted_flow_by_line=baseline_predicted_flow,
            )
            baseline_stress.metadata["prediction_source"] = baseline_prediction.source
            baseline_stress.metadata["prediction_model_source"] = "Baseline"
            baseline_stress.metadata["prediction_risk_line_count"] = len(
                baseline_prediction.risk_lines
            )
            baseline_warning = _prediction_warning_for_result("Baseline", baseline_prediction)
            if baseline_warning:
                warning = f"Prediction 비교용 Baseline 기준값: {baseline_warning}"

        comparison = _build_prediction_briefing_comparison(
            baseline_result=baseline_prediction,
            selected_result=selected_prediction_result,
            baseline_stress=baseline_stress,
            selected_stress=selected_stress_analysis,
            selected_model_label=selected_model_label,
            warning=warning,
        )
        st.session_state[_PREDICTION_BRIEFING_CACHE_STATE_KEY] = (
            cache_key,
            comparison,
            warning,
        )
        return comparison, warning
    except Exception as exc:  # noqa: BLE001
        warning = f"Prediction 비교 기준값을 만들지 못했습니다. 원인: {exc}"
        st.session_state[_PREDICTION_BRIEFING_CACHE_STATE_KEY] = (cache_key, None, warning)
        return None, warning


def _build_prediction_briefing_comparison(
    *,
    baseline_result: PredictionResult,
    selected_result: PredictionResult,
    baseline_stress: StressAnalysisResult,
    selected_stress: StressAnalysisResult,
    selected_model_label: str,
    warning: str = "",
) -> PredictionBriefingComparison:
    return PredictionBriefingComparison(
        baseline_result=baseline_result,
        selected_result=selected_result,
        baseline_stress=baseline_stress,
        selected_stress=selected_stress,
        selected_model_label=selected_model_label,
        summary_rows=_prediction_comparison_summary_rows(
            baseline_result=baseline_result,
            selected_result=selected_result,
            baseline_stress=baseline_stress,
            selected_stress=selected_stress,
        ),
        line_delta_rows=_prediction_comparison_line_delta_rows(
            baseline_stress,
            selected_stress,
        ),
        warning=warning,
    )


def _prediction_comparison_summary_rows(
    *,
    baseline_result: PredictionResult,
    selected_result: PredictionResult,
    baseline_stress: StressAnalysisResult,
    selected_stress: StressAnalysisResult,
) -> list[dict[str, object]]:
    baseline_metrics = _prediction_briefing_metrics(baseline_result, baseline_stress)
    selected_metrics = _prediction_briefing_metrics(selected_result, selected_stress)
    return [
        _prediction_summary_count_row(
            "미래 위험 선로",
            baseline_metrics["risk_line_count"],
            selected_metrics["risk_line_count"],
            unit="개",
        ),
        _prediction_summary_float_row(
            "예측 추가 MW",
            baseline_metrics["predicted_flow_mw"],
            selected_metrics["predicted_flow_mw"],
            unit="MW",
        ),
        _prediction_summary_percent_row(
            "최대 이용률",
            baseline_metrics["max_utilization"],
            selected_metrics["max_utilization"],
        ),
        _prediction_summary_count_row(
            "병목 선로",
            baseline_metrics["bottleneck_line_count"],
            selected_metrics["bottleneck_line_count"],
            unit="개",
        ),
        _prediction_summary_count_row(
            "위험/과부하 선로",
            baseline_metrics["critical_or_overload_count"],
            selected_metrics["critical_or_overload_count"],
            unit="개",
        ),
        {
            "항목": "실제 모델 source",
            "Baseline": baseline_result.source,
            "선택 모델": selected_result.source,
            "변화": "-",
        },
        {
            "항목": "fallback",
            "Baseline": _prediction_fallback_label(baseline_result),
            "선택 모델": _prediction_fallback_label(selected_result),
            "변화": "-",
        },
    ]


def _prediction_briefing_metrics(
    prediction_result: PredictionResult,
    stress_analysis: StressAnalysisResult,
) -> dict[str, float | int]:
    counts = _stress_status_counts(stress_analysis)
    max_utilization = max(
        (float(stress.utilization) for stress in stress_analysis.line_stresses),
        default=0.0,
    )
    predicted_flow_mw = sum(
        max(0.0, float(stress.predicted_flow_mw))
        for stress in stress_analysis.line_stresses
    )
    return {
        "risk_line_count": len(prediction_result.risk_lines),
        "predicted_flow_mw": predicted_flow_mw,
        "max_utilization": max_utilization,
        "bottleneck_line_count": len(stress_analysis.bottleneck_line_ids),
        "critical_or_overload_count": counts["critical"] + counts["overload"],
    }


def _prediction_summary_count_row(
    label: str,
    baseline_value: object,
    selected_value: object,
    *,
    unit: str,
) -> dict[str, object]:
    baseline_count = int(baseline_value)
    selected_count = int(selected_value)
    delta = selected_count - baseline_count
    return {
        "항목": label,
        "Baseline": f"{baseline_count}{unit}",
        "선택 모델": f"{selected_count}{unit}",
        "변화": f"{delta:+d}{unit}",
    }


def _prediction_summary_float_row(
    label: str,
    baseline_value: object,
    selected_value: object,
    *,
    unit: str,
) -> dict[str, object]:
    baseline_number = float(baseline_value)
    selected_number = float(selected_value)
    delta = selected_number - baseline_number
    return {
        "항목": label,
        "Baseline": f"{baseline_number:.1f} {unit}",
        "선택 모델": f"{selected_number:.1f} {unit}",
        "변화": f"{delta:+.1f} {unit}",
    }


def _prediction_summary_percent_row(
    label: str,
    baseline_value: object,
    selected_value: object,
) -> dict[str, object]:
    baseline_number = float(baseline_value)
    selected_number = float(selected_value)
    delta_pp = (selected_number - baseline_number) * 100.0
    return {
        "항목": label,
        "Baseline": _format_percent(baseline_number),
        "선택 모델": _format_percent(selected_number),
        "변화": f"{delta_pp:+.1f} pp",
    }


def _prediction_fallback_label(prediction_result: PredictionResult) -> str:
    if not prediction_result.fallback.enabled:
        return "없음"
    return prediction_result.fallback.mode or "enabled"


def _prediction_comparison_line_delta_rows(
    baseline_stress: StressAnalysisResult,
    selected_stress: StressAnalysisResult,
) -> list[dict[str, object]]:
    baseline_by_line_id = _line_stress_by_id(baseline_stress)
    selected_by_line_id = _line_stress_by_id(selected_stress)
    line_ids = sorted(set(baseline_by_line_id) | set(selected_by_line_id))
    rows: list[dict[str, object]] = []
    for line_id in line_ids:
        baseline_line = baseline_by_line_id.get(line_id)
        selected_line = selected_by_line_id.get(line_id)
        baseline_utilization = float(getattr(baseline_line, "utilization", 0.0))
        selected_utilization = float(getattr(selected_line, "utilization", 0.0))
        baseline_predicted_mw = float(getattr(baseline_line, "predicted_flow_mw", 0.0))
        selected_predicted_mw = float(getattr(selected_line, "predicted_flow_mw", 0.0))
        delta_pp = (selected_utilization - baseline_utilization) * 100.0
        predicted_delta_mw = selected_predicted_mw - baseline_predicted_mw
        if (
            abs(delta_pp) < 0.05
            and abs(predicted_delta_mw) < 0.05
            and baseline_predicted_mw <= 0.0
            and selected_predicted_mw <= 0.0
        ):
            continue

        display_label = _line_stress_display_label(baseline_line or selected_line, line_id)
        rows.append(
            {
                "선로 ID": line_id,
                "구간": display_label,
                "Baseline 이용률": _format_percent(baseline_utilization),
                "선택 모델 이용률": _format_percent(selected_utilization),
                "변화 pp": round(delta_pp, 2),
                "Baseline 예측 MW": f"{baseline_predicted_mw:.1f} MW",
                "선택 예측 MW": f"{selected_predicted_mw:.1f} MW",
                "예측 MW 변화": f"{predicted_delta_mw:+.1f} MW",
                "Baseline 상태": getattr(baseline_line, "status", ""),
                "선택 상태": getattr(selected_line, "status", ""),
            }
        )
    return sorted(
        rows,
        key=lambda row: abs(float(row["변화 pp"])),
        reverse=True,
    )


def _line_stress_display_label(
    stress: Any,
    fallback_line_id: str,
) -> str:
    if stress is None:
        return fallback_line_id
    from_label = str(getattr(stress, "from_node_name", "") or getattr(stress, "from_node_id", ""))
    to_label = str(getattr(stress, "to_node_name", "") or getattr(stress, "to_node_id", ""))
    if from_label and to_label:
        return f"{from_label}->{to_label}"
    return fallback_line_id


def _get_landing_stress_analysis(
    scenario: ScenarioContext,
    *,
    load_scale: float,
    monitoring_result: MonitoringResult | None = None,
    prediction_result: PredictionResult | None = None,
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
        _prediction_result_cache_key(prediction_result),
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
        predicted_flow_by_line = _prediction_flow_by_line(
            prediction_result,
            grid_dataset=dataset,
            monitoring_result=monitoring_result,
            load_scale=load_scale,
        )
        stress_analysis = analyze_route_stress(
            scenario=scenario,
            grid_dataset=dataset,
            transmission_scenarios=transmission_scenarios,
            load_scale=load_scale,
            created_at=created_at,
            monitoring_result=monitoring_result,
            predicted_flow_by_line=predicted_flow_by_line,
        )
        if prediction_result is not None:
            stress_analysis.metadata["prediction_source"] = prediction_result.source
            stress_analysis.metadata["prediction_model_source"] = prediction_result.metadata.get(
                "landing_model_source",
                prediction_result.source,
            )
            stress_analysis.metadata["prediction_risk_line_count"] = len(
                prediction_result.risk_lines
            )
        st.session_state[STRESS_ANALYSIS_STATE_KEY] = stress_analysis
        st.session_state[_STRESS_ANALYSIS_CACHE_STATE_KEY] = (cache_key, stress_analysis, "")
        return stress_analysis, ""
    except Exception as exc:  # noqa: BLE001
        warning = f"송전 시나리오 stress 분석을 만들지 못했습니다. 원인: {exc}"
        st.session_state[_STRESS_ANALYSIS_CACHE_STATE_KEY] = (cache_key, None, warning)
        st.session_state[STRESS_ANALYSIS_STATE_KEY] = None
        return None, warning


def _get_landing_improvement_proposal(
    scenario: ScenarioContext,
    *,
    target_line_id: str | None,
    stress_analysis: StressAnalysisResult | None,
    load_scale: float,
    monitoring_result: MonitoringResult | None = None,
    prediction_result: PredictionResult | None = None,
) -> tuple[GridImprovementProposal | None, str]:
    if not target_line_id or stress_analysis is None:
        st.session_state[GRID_IMPROVEMENT_PROPOSAL_STATE_KEY] = None
        return None, ""

    installations = _landing_installations()
    transmission_scenarios = _landing_transmission_scenarios()
    created_at = scenario.created_at or datetime.now().replace(minute=0, second=0, microsecond=0)
    cache_key = (
        scenario.scenario_id,
        created_at.isoformat(),
        str(target_line_id),
        round(load_scale, 4),
        _installations_cache_key(installations),
        _transmission_scenarios_cache_key(transmission_scenarios),
        _stress_analysis_cache_key(stress_analysis),
        _monitoring_result_cache_key(monitoring_result),
        _prediction_result_cache_key(prediction_result),
    )
    cached = st.session_state.get(_GRID_IMPROVEMENT_PROPOSAL_CACHE_STATE_KEY)
    if isinstance(cached, tuple) and len(cached) == 3 and cached[0] == cache_key:
        st.session_state[GRID_IMPROVEMENT_PROPOSAL_STATE_KEY] = cached[1]
        return cached[1], cached[2]

    try:
        dataset = load_grid_dataset_or_default(
            user_installations=installations,
            created_at=created_at,
            load_scale=load_scale,
        )
        predicted_flow_by_line = _prediction_flow_by_line(
            prediction_result,
            grid_dataset=dataset,
            monitoring_result=monitoring_result,
            load_scale=load_scale,
        )
        proposal = build_grid_improvement_proposal(
            scenario=scenario,
            grid_dataset=dataset,
            stress_analysis=stress_analysis,
            target_line_id=target_line_id,
            load_scale=load_scale,
            created_at=created_at,
            monitoring_result=monitoring_result,
            predicted_flow_by_line=predicted_flow_by_line,
        )
        st.session_state[GRID_IMPROVEMENT_PROPOSAL_STATE_KEY] = proposal
        st.session_state[_GRID_IMPROVEMENT_PROPOSAL_CACHE_STATE_KEY] = (cache_key, proposal, "")
        return proposal, ""
    except Exception as exc:  # noqa: BLE001
        warning = f"선택 선로 개선안을 만들지 못했습니다. 원인: {exc}"
        st.session_state[GRID_IMPROVEMENT_PROPOSAL_STATE_KEY] = None
        st.session_state[_GRID_IMPROVEMENT_PROPOSAL_CACHE_STATE_KEY] = (cache_key, None, warning)
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


def _stress_analysis_cache_key(
    stress_analysis: StressAnalysisResult | None,
) -> tuple[object, ...]:
    if stress_analysis is None:
        return ("none",)
    return (
        stress_analysis.created_at.isoformat(),
        round(float(stress_analysis.load_scale), 4),
        tuple(stress_analysis.bottleneck_line_ids),
        tuple(stress_analysis.warning_line_ids),
        tuple(stress_analysis.critical_line_ids),
        tuple(
            (
                stress.line_id,
                round(float(stress.total_flow_mw), 4),
                round(float(stress.utilization), 6),
                stress.status,
                tuple(stress.contributing_scenario_ids),
            )
            for stress in stress_analysis.line_stresses
        ),
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


def _prediction_result_cache_key(
    prediction_result: PredictionResult | None,
) -> tuple[object, ...]:
    if prediction_result is None:
        return ("none",)
    return (
        prediction_result.source,
        prediction_result.created_at.isoformat(),
        round(float(prediction_result.load_scale), 4),
        bool(prediction_result.fallback.enabled),
        tuple(
            (
                risk_line.line_id,
                round(float(risk_line.predicted_utilization), 6),
                risk_line.risk_level,
            )
            for risk_line in prediction_result.risk_lines
        ),
    )


def _prediction_flow_by_line(
    prediction_result: PredictionResult | None,
    *,
    grid_dataset: GridDataset,
    monitoring_result: MonitoringResult | None,
    load_scale: float,
) -> dict[str, float]:
    if prediction_result is None:
        return {}

    capacity_by_line = {
        line.line_id: max(0.0, float(line.capacity_mw))
        for line in grid_dataset.lines
        if line.status != "out_of_service"
    }
    base_flow_by_line = _monitoring_base_flow_by_line(monitoring_result)
    predicted_flow_by_line: dict[str, float] = {}

    for risk_line in prediction_result.risk_lines:
        capacity_mw = capacity_by_line.get(risk_line.line_id, 0.0)
        if capacity_mw <= 0.0:
            continue

        predicted_total_flow_mw = max(
            0.0,
            float(risk_line.predicted_utilization) * capacity_mw,
        )
        base_flow_mw = base_flow_by_line.get(
            risk_line.line_id,
            capacity_mw * DEFAULT_BASE_FLOW_RATIO * max(0.0, load_scale),
        )
        incremental_flow_mw = max(0.0, predicted_total_flow_mw - base_flow_mw)
        if incremental_flow_mw <= 0.0:
            continue
        predicted_flow_by_line[risk_line.line_id] = round(incremental_flow_mw, 3)

    return predicted_flow_by_line


def _monitoring_base_flow_by_line(
    monitoring_result: MonitoringResult | None,
) -> dict[str, float]:
    if monitoring_result is None:
        return {}
    return {
        status.line_id: abs(float(status.flow_mw))
        for status in monitoring_result.line_statuses
        if isinstance(status, LineStatus)
    }


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

        xai_metadata = {}
        if _line_needs_xai(stress, bottleneck_line_ids):
            xai_metadata = xai_explanation_to_metadata(
                build_line_xai_explanation(
                    stress,
                    stress_analysis=stress_analysis,
                )
            )

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
                    **xai_metadata,
                },
            )
        )
    return enriched_lines


def _line_needs_xai(
    stress: Any,
    bottleneck_line_ids: set[str],
) -> bool:
    return (
        stress.line_id in bottleneck_line_ids
        or stress.status in {"warning", "critical", "overload"}
        or int(stress.shared_route_count) >= 2
    )


def _attach_improvement_metadata(
    lines: list[MapOverlayLine],
    proposal: GridImprovementProposal | None,
) -> list[MapOverlayLine]:
    if proposal is None:
        return list(lines)

    best_reroute = proposal.reroute_candidates[0] if proposal.reroute_candidates else None
    best_node = proposal.suggested_nodes[0] if proposal.suggested_nodes else None
    enriched_lines: list[MapOverlayLine] = []
    for line in lines:
        line_id = str(line.metadata.get("line_id", line.overlay_id))
        if line_id != proposal.target_line_id:
            enriched_lines.append(line)
            continue

        metadata = {
            **line.metadata,
            "improvement_proposal_id": proposal.proposal_id,
            "improvement_summary": proposal.summary,
            "improvement_reroute_candidate_count": len(proposal.reroute_candidates),
            "improvement_suggested_node_count": len(proposal.suggested_nodes),
        }
        if best_reroute is not None:
            metadata.update(
                {
                    "improvement_best_candidate_id": best_reroute.candidate_id,
                    "improvement_best_scenario_id": best_reroute.scenario_route_id,
                    "improvement_best_before_utilization": best_reroute.before_target_utilization,
                    "improvement_best_after_utilization": best_reroute.after_target_utilization,
                    "improvement_best_added_distance_km": best_reroute.added_distance_km,
                    "improvement_best_score": best_reroute.score,
                    "improvement_best_rationale": best_reroute.rationale,
                }
            )
        if best_node is not None:
            metadata.update(
                {
                    "improvement_suggested_node_id": best_node.suggested_node_id,
                    "improvement_suggested_node_label": best_node.label,
                    "improvement_suggested_node_capacity_mw": best_node.capacity_mw,
                    "improvement_suggested_node_cost_billion": best_node.install_cost_billion,
                    "improvement_suggested_node_reason": best_node.reason,
                }
            )
        enriched_lines.append(replace(line, metadata=metadata))
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


def _build_improvement_reroute_routes(
    proposal: GridImprovementProposal | None,
) -> list[MapOverlayRoute]:
    if proposal is None:
        return []

    routes: list[MapOverlayRoute] = []
    for rank, candidate in enumerate(proposal.reroute_candidates[:2], start=1):
        if candidate.route is None or len(candidate.route.waypoints) < 2:
            continue
        route_points = [
            MapOverlayPoint(
                overlay_id=f"improvement-route-point:{candidate.candidate_id}:{point.point_id}",
                label=point.label,
                kind="route_point",
                latitude=point.latitude,
                longitude=point.longitude,
                elevation_m=None,
                elevation_source="not_queried",
                status="normal",
                source=candidate.route.source,
                metadata={
                    "improvement_proposal_id": proposal.proposal_id,
                    "reroute_candidate_id": candidate.candidate_id,
                    "transmission_scenario_id": candidate.scenario_route_id,
                    "node_id": point.point_id,
                    "selection_role": "improvement_reroute",
                },
            )
            for point in candidate.route.waypoints
        ]
        routes.append(
            MapOverlayRoute(
                overlay_id=f"improvement-route:{candidate.candidate_id}",
                label=f"우회 후보 {rank}: {candidate.scenario_label or candidate.scenario_route_id}",
                route_id=candidate.route.route_id,
                candidate_id=candidate.candidate_id,
                rank=rank,
                points=route_points,
                total_distance_km=candidate.route.total_distance_km,
                estimated_cost=candidate.route.estimated_cost,
                source=candidate.route.source,
                metadata={
                    "display_status": "improvement_candidate",
                    "improvement_proposal_id": proposal.proposal_id,
                    "target_line_id": proposal.target_line_id,
                    "reroute_candidate_id": candidate.candidate_id,
                    "after_target_utilization": candidate.after_target_utilization,
                    "score": candidate.score,
                },
            )
        )
    return routes


def _build_improvement_suggested_points(
    proposal: GridImprovementProposal | None,
) -> list[MapOverlayPoint]:
    if proposal is None:
        return []

    return [
        MapOverlayPoint(
            overlay_id=f"improvement-node:{node.suggested_node_id}",
            label=node.label,
            kind="tower_candidate",
            latitude=node.latitude,
            longitude=node.longitude,
            elevation_m=node.elevation_m,
            coordinate_system=node.coordinate_system,
            elevation_source=node.elevation_source,
            status="normal",
            risk_level="medium",
            source="heuristic",
            metadata={
                "node_id": node.suggested_node_id,
                "node_type": "suggested_transmission_tower",
                "suggested_node_id": node.suggested_node_id,
                "target_line_id": node.target_line_id,
                "voltage_kv": node.voltage_kv,
                "capacity_mw": node.capacity_mw,
                "install_cost_billion": node.install_cost_billion,
                "expected_utilization_delta": node.expected_utilization_delta,
                "relief_line_ids": list(node.relief_line_ids),
                "reason": node.reason,
                "recommendation_type": node.metadata.get(
                    "recommendation_type",
                    "new_transmission_tower",
                ),
            },
        )
        for node in proposal.suggested_nodes
    ]


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
