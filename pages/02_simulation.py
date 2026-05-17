from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.schemas import (
    MapOverlayResult,
    ScoreBreakdown,
    SimulationResult,
)
from src.services.map_overlay_service import MapOverlayService
from src.services.monitoring_service import MonitoringService
from src.services.simulation_service import SimulationService
from src.ui.map_overlay_renderer import overlay_warnings_for_display, render_map_overlay
from src.ui.scenario_controls import render_scenario_sidebar

st.set_page_config(page_title="시뮬레이션 | SGOP", layout="wide")

# --- 1. 서비스 초기화 및 색상 로직 ---
@st.cache_resource
def get_service():
    return SimulationService()

sim_service = get_service()
overlay_service = MapOverlayService()
monitoring_service = MonitoringService()
shared_scenario = render_scenario_sidebar()

bus_options = sim_service.list_bus_options()
candidate_options = sim_service.list_candidate_options()

# --- 세션 상태(Session State) 초기화 ---
if 'sim_run' not in st.session_state:
    st.session_state.sim_run = False

def _build_recommendation_rows(sim_result: SimulationResult) -> list[dict]:
    rows: list[dict] = []
    for recommendation in sim_result.recommendations:
        route = recommendation.route
        score = recommendation.score
        rows.append({
            "순위": recommendation.rank,
            "후보지": f"{recommendation.candidate_label} ({recommendation.candidate_id})",
            "총점": round(score.total_score, 1) if score else None,
            "경로 길이 (km)": round(route.total_distance_km, 1) if route else None,
            "예상 비용": round(route.estimated_cost, 1) if route else None,
            "혼잡 완화": round(score.congestion_relief, 1) if score else None,
            "거리 비용": round(score.distance_cost, 1) if score else None,
            "공사 비용": round(score.construction_cost, 1) if score else None,
            "환경 리스크": round(score.environmental_risk, 1) if score else None,
            "정책 리스크": round(score.policy_risk, 1) if score else None,
            "경로 소스": route.source if route else "-",
        })
    return rows

def _score_progress_value(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(0.0, min(value / maximum, 1.0))

def _format_score_impact(value: float) -> str:
    return f"+{value:.1f}" if value >= 0 else f"{value:.1f}"

def _build_score_detail_rows(score: ScoreBreakdown) -> list[dict]:
    base_score = 100.0
    return [
        {
            "구분": "기준",
            "세부 항목": "기본 점수",
            "원점수": round(base_score, 1),
            "총점 반영": _format_score_impact(base_score),
            "설명": "모든 후보에 동일하게 적용되는 기준점",
        },
        {
            "구분": "보상",
            "세부 항목": "혼잡 완화 보상",
            "원점수": round(score.congestion_relief, 1),
            "총점 반영": _format_score_impact(score.congestion_relief),
            "설명": "부하 보정, 경로 안정성, counterfactual 개선 효과",
        },
        {
            "구분": "비용",
            "세부 항목": "거리 비용",
            "원점수": round(score.distance_cost, 1),
            "총점 반영": f"-{score.distance_cost:.1f}",
            "설명": "A* 경로 길이와 기준거리 초과분",
        },
        {
            "구분": "비용",
            "세부 항목": "공사비 비용",
            "원점수": round(score.construction_cost, 1),
            "총점 반영": f"-{score.construction_cost:.1f}",
            "설명": "거리 기반 예상 공사비와 후보지 보정 비용",
        },
        {
            "구분": "비용",
            "세부 항목": "환경 리스크",
            "원점수": round(score.environmental_risk, 1),
            "총점 반영": f"-{score.environmental_risk:.1f}",
            "설명": "산지, 보호구역, 민감 지역 등 환경 부담",
        },
        {
            "구분": "비용",
            "세부 항목": "정책 리스크",
            "원점수": round(score.policy_risk, 1),
            "총점 반영": f"-{score.policy_risk:.1f}",
            "설명": "인허가, 수용성, 정책 제약 부담",
        },
        {
            "구분": "결과",
            "세부 항목": "최종 총점",
            "원점수": round(score.total_score, 1),
            "총점 반영": f"{score.total_score:.1f}",
            "설명": "기본 점수 + 보상 - 비용 합계",
        },
    ]

def _format_route_nodes(sim_result: SimulationResult) -> str:
    route = sim_result.selected_route
    if route is None or not route.path_node_ids:
        return "-"
    return " -> ".join(route.path_node_ids)

def _build_map_overlay(
    sim_result: SimulationResult,
    *,
    map_capability: MapCapability,
) -> MapOverlayResult:
    baseline_monitoring = monitoring_service.run_dc_power_flow(
        scenario=sim_result.scenario,
        load_scale=sim_result.simulation_input.load_scale,
        created_at=sim_result.created_at,
    )
    return overlay_service.build_simulation_overlay(
        sim_result,
        baseline_monitoring=baseline_monitoring,
        map_capability=map_capability,
    )

# --- 2. 사이드바 입력창 (Form으로 묶어서 한 번에 실행!) ---
with st.sidebar:
    st.header("⚡ 시뮬레이션 제어")
    
    with st.form("simulation_form"):
        start_bus = st.selectbox("시작 버스", options=[b[0] for b in bus_options], format_func=lambda x: dict(bus_options)[x], index=0)
        end_bus = st.selectbox("종료 버스", options=[b[0] for b in bus_options], format_func=lambda x: dict(bus_options)[x], index=10)
        
        selected_candidates = st.multiselect(
            "경유 후보지 선택", 
            options=[c[0] for c in candidate_options],
            default=[c[0] for c in candidate_options],
            format_func=lambda x: dict(candidate_options)[x]
        )
        
        load_scale = st.slider("시스템 전체 부하 배율", 0.5, 1.5, 1.0, 0.05)
        
        submitted = st.form_submit_button("🚀 시뮬레이션 실행", type="primary", use_container_width=True)

st.title("🗺️ 송전망 혼잡도 및 A* 최적 경로 시뮬레이션")

# --- 3. 엔진 가동 (버튼을 눌렀을 때만 작동) ---
if submitted:
    with st.spinner("AI가 최적 경로 및 혼잡도를 계산 중입니다... 🔄"):
        shared_created_at = shared_scenario.created_at

        sim_input = sim_service.build_default_input(
            scenario=shared_scenario,
            created_at=shared_created_at,
            start_bus_id=start_bus, 
            end_bus_id=end_bus, 
            candidate_site_ids=selected_candidates, 
            load_scale=load_scale
        )
        sim_result = sim_service.run_simulation(
            sim_input,
            created_at=shared_created_at,
        )
        map_capability = get_map_capability(prefer_webgl=False)
        map_overlay = _build_map_overlay(
            sim_result,
            map_capability=map_capability,
        )
        
        st.session_state.sim_result = sim_result
        st.session_state.sim_map_capability = map_capability
        st.session_state.sim_map_overlay = map_overlay
        st.session_state.sgop_shared_scenario = sim_result.scenario
        st.session_state.selected_candidates = selected_candidates
        st.session_state.sim_run = True

# --- 4. 화면 레이아웃 (계산 완료 상태일 때만 화면 렌더링) ---
if st.session_state.sim_run:
    sim_result = st.session_state.sim_result
    map_capability = st.session_state.get("sim_map_capability") or get_map_capability(prefer_webgl=False)
    map_overlay = st.session_state.get("sim_map_overlay")
    if not isinstance(map_overlay, MapOverlayResult):
        map_overlay = _build_map_overlay(
            sim_result,
            map_capability=map_capability,
        )
        st.session_state.sim_map_capability = map_capability
        st.session_state.sim_map_overlay = map_overlay
    selected_candidates = st.session_state.selected_candidates

    # 팀원들이 추가한 안내 메시지 및 시나리오 캡션
    st.caption(
        f"시나리오: {sim_result.scenario.scenario_id}  |  "
        f"입력: {sim_result.simulation_input.start_bus_id} -> "
        f"{sim_result.simulation_input.end_bus_id}  |  "
        f"후보지 {len(sim_result.simulation_input.candidate_site_ids)}개  |  "
        f"부하 배율 {sim_result.simulation_input.load_scale:.2f}x  |  "
        f"소스: {sim_result.source.upper()}"
    )

    if sim_result.fallback.enabled:
        st.warning(f"Fallback 사용 중: `{sim_result.fallback.mode}` | {sim_result.fallback.reason}")

    for warning in sim_result.warnings:
        st.caption(f"- {warning}")

    col_map, col_info = st.columns([2, 1])

    with col_map:
        st.subheader("📍 A* 최적 경로 및 계통 혼잡 지도")
        render_map_overlay(
            map_overlay,
            map_capability=map_capability,
            height=650,
            show_point_table=True,
        )
        st.caption(map_overlay.summary)
        st.caption(
            f"지도 모드: {map_overlay.metadata.get('rendering_mode')}  |  "
            f"좌표계: {map_overlay.metadata.get('coordinate_system')}  |  "
            f"고도: {map_overlay.metadata.get('elevation_source')}"
        )

        overlay_extra_warnings = overlay_warnings_for_display(
            sim_result.warnings,
            map_overlay.warnings,
        )
        if overlay_extra_warnings:
            with st.expander("지도 fallback 및 좌표 메타데이터", expanded=False):
                if map_overlay.fallback.enabled:
                    st.caption(
                        f"Fallback: `{map_overlay.fallback.mode}`  |  "
                        f"{map_overlay.fallback.reason}"
                    )
                for warning in overlay_extra_warnings:
                    st.caption(f"- {warning}")

    with col_info:
        # --- 설치 전/후 비교 카드 ---
        st.subheader("📊 설치 전/후 비교")
        if sim_result.deltas:
            for delta in sim_result.deltas:
                delta_color = "normal" if delta.status != "worsened" else "inverse"
                st.metric(
                    label=delta.label,
                    value=f"{delta.after_value} {delta.unit}",
                    delta=f"{delta.improvement} {delta.unit} ({'개선' if delta.improvement > 0 else '증가'})",
                    delta_color=delta_color
                )
        
        st.divider()

        # --- 🏆 AI 1순위 추천 사유 및 세부 점수표 ---
        if sim_result.recommendations:
            top_rec = sim_result.recommendations[0]
            st.subheader("🏆 AI 1순위 추천 분석")
            
            st.success(f"**추천 사유:**\n{top_rec.rationale}")
            
            with st.expander(f"세부 평가 지표 보기 (총점: {top_rec.score.total_score:.1f}점)", expanded=True):
                sc = top_rec.score
                cost_total = (
                    sc.distance_cost
                    + sc.construction_cost
                    + sc.environmental_risk
                    + sc.policy_risk
                )
                score_cols = st.columns(4)
                score_cols[0].metric("기본 점수", "100.0점")
                score_cols[1].metric("혼잡 완화 보상", f"+{sc.congestion_relief:.1f}점")
                score_cols[2].metric("비용 합계", f"-{cost_total:.1f}점")
                score_cols[3].metric("최종 총점", f"{sc.total_score:.1f}점")

                st.dataframe(
                    pd.DataFrame(_build_score_detail_rows(sc)),
                    width="stretch",
                    hide_index=True,
                )

                st.caption(f"혼잡 완화 보상 (+{sc.congestion_relief:.1f}점)")
                st.progress(_score_progress_value(sc.congestion_relief, 60.0))

                st.caption(f"거리 비용 (-{sc.distance_cost:.1f}점)")
                st.progress(_score_progress_value(sc.distance_cost, 35.0))

                st.caption(f"공사비 비용 (-{sc.construction_cost:.1f}점)")
                st.progress(_score_progress_value(sc.construction_cost, 35.0))

                st.caption(f"환경 리스크 (-{sc.environmental_risk:.1f}점)")
                st.progress(_score_progress_value(sc.environmental_risk, 15.0))

                st.caption(f"정책 리스크 (-{sc.policy_risk:.1f}점)")
                st.progress(_score_progress_value(sc.policy_risk, 15.0))

                if top_rec.route and top_rec.route.summary:
                    st.caption(f"A* 경로 요약: {top_rec.route.summary}")

                if sc.notes:
                    st.markdown("**점수 산정 근거**")
                    for note in sc.notes:
                        st.caption(f"- {note}")

    # --- 팀원들이 만든 하단 데이터 표 영역 ---
    st.divider()
    st.subheader("📋 전체 후보지별 추천 결과 데이터")

    recommendation_rows = _build_recommendation_rows(sim_result)
    if recommendation_rows:
        st.dataframe(
            pd.DataFrame(recommendation_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("표시할 추천 결과가 없습니다.")

else:
    # 초기 안내 화면
    st.info("👈 좌측 사이드바에서 조건을 설정하고 **[🚀 시뮬레이션 실행]** 버튼을 눌러주세요.")
