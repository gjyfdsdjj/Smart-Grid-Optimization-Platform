# 송전망 혼잡 상태를 보여주는 모니터링 페이지를 구성한다.
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.adapters.vworld_adapter import get_map_capability
from src.data.schemas import MonitoringKpi, MonitoringResult, ScenarioContext
from src.services.map_overlay_service import MapOverlayService
from src.services.monitoring_service import MonitoringService
from src.ui.map_overlay_renderer import render_map_overlay
from src.ui.scenario_controls import render_scenario_sidebar
from src.ui.table_selection import selected_value_from_dataframe_event

# ── 상수 ──────────────────────────────────────────────────────────────────────

_STATUS_COLOR: dict[str, str] = {
    "normal":   "#2ecc71",
    "warning":  "#f39c12",
    "critical": "#e74c3c",
    "overload": "#8e44ad",
}

_STATUS_LABEL: dict[str, str] = {
    "normal":   "정상",
    "warning":  "경고",
    "critical": "위험",
    "overload": "과부하",
}


# ── 페이지 설정 ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="모니터링 | SGOP", layout="wide")


def _fmt_kpi_value(kpi: MonitoringKpi) -> str:
    if kpi.unit == "lines":
        return f"{int(kpi.value)}개"
    if kpi.unit == "%":
        return f"{kpi.value:.1f}%"
    return f"{kpi.value:,.1f} {kpi.unit}"


def _fmt_kpi_delta(kpi: MonitoringKpi) -> str | None:
    if kpi.delta is None:
        return None
    sign = "+" if kpi.delta >= 0 else ""
    if kpi.unit == "lines":
        return f"경고 {int(kpi.delta)}개"
    if kpi.unit == "MW":
        return f"{sign}{kpi.delta:,.1f} MW"
    return f"{sign}{kpi.delta:.1f}%"

# ── 사이드바 ───────────────────────────────────────────────────────────────────

service = MonitoringService()
overlay_service = MapOverlayService()
shared_scenario = render_scenario_sidebar()


def _load_monitoring_result(
    *,
    service: MonitoringService,
    data_source: str,
    scenario: ScenarioContext,
    load_scale: float,
) -> MonitoringResult:
    try:
        if data_source == "DC Power Flow":
            return service.run_dc_power_flow(
                scenario=scenario,
                load_scale=load_scale,
            )
        return service.run_mock_monitoring(
            scenario=scenario,
            load_scale=load_scale,
        )
    except (TypeError, ValueError) as exc:
        st.error(f"모니터링 입력 검증 실패: {exc}")
        st.stop()
    except Exception as exc:  # noqa: BLE001
        st.error(f"모니터링 결과 생성 실패: {exc}")
        st.stop()


def _overlay_warnings_for_display(result: MonitoringResult, overlay_warnings: list[str]) -> list[str]:
    source_warnings = set(result.warnings)
    return [
        warning
        for warning in overlay_warnings
        if warning not in source_warnings
    ]


def _resolve_selected_line_id(selection_event: object, rows: list[dict]) -> str | None:
    selected_line_id = selected_value_from_dataframe_event(
        selection_event,
        rows,
        "선로 ID",
    )
    if isinstance(selected_line_id, str) and selected_line_id.strip():
        return selected_line_id.strip()
    return None

with st.sidebar:
    st.header("모니터링 설정")
    load_scale = st.slider(
        "부하 배율",
        min_value=0.5,
        max_value=1.5,
        value=1.0,
        step=0.05,
        help="전체 부하의 배율. 1.3 이상이면 위험·과부하 선로가 늘어납니다.",
    )
    st.divider()
    data_source = st.radio(
        "데이터 소스",
        options=["mock", "DC Power Flow"],
        index=1,
        help="mock: 고정 합성 데이터 (빠름) / DC Power Flow: 선형 조류 계산 (실제 물리 모델)",
    )
    st.divider()
    if st.button("새로고침", width="stretch"):
        st.cache_data.clear()
    st.caption(f"데이터 소스: {data_source}")

# ── 입력 검증 ──────────────────────────────────────────────────────────────────

if load_scale >= 1.4:
    st.warning(f"부하 배율 {load_scale:.2f}×: 과부하 상태가 예상됩니다. 실제 운영 상황을 확인하세요.")
elif load_scale <= 0.6:
    st.info(f"부하 배율 {load_scale:.2f}×: 경부하 상태입니다.")

# ── 데이터 로드 ────────────────────────────────────────────────────────────────

with st.spinner("모니터링 결과를 생성하는 중입니다..."):
    result: MonitoringResult = _load_monitoring_result(
        service=service,
        data_source=data_source,
        scenario=shared_scenario,
        load_scale=load_scale,
    )

st.session_state.sgop_shared_scenario = result.scenario
st.session_state.sgop_monitoring_result = result
map_capability = get_map_capability(prefer_webgl=False)
map_overlay = overlay_service.build_monitoring_overlay(
    result,
    map_capability=map_capability,
)
st.session_state.sgop_monitoring_overlay = map_overlay
cs = result.congestion_summary
lines = result.line_statuses

# ── 헤더 + fallback 알림 ───────────────────────────────────────────────────────

st.title("송전망 혼잡도 모니터링")
st.caption(
    f"기준 시각: {result.created_at:%Y-%m-%d %H:%M}  |  "
    f"소스: {result.source.upper()}  |  "
    f"시나리오: {result.scenario.scenario_id}"
)
st.info(result.summary)

if result.fallback.enabled:
    st.warning(f"Fallback 사용 중: `{result.fallback.mode}`  |  {result.fallback.reason}")

for w in result.warnings:
    st.caption(f"- {w}")

# ── KPI 카드 ───────────────────────────────────────────────────────────────────

st.subheader("KPI")
kpi_cols = st.columns(len(result.kpis)) if result.kpis else []
for col, kpi in zip(kpi_cols, result.kpis):
    col.metric(kpi.label, _fmt_kpi_value(kpi), delta=_fmt_kpi_delta(kpi))

st.divider()

# ── 상태 요약 배지 ─────────────────────────────────────────────────────────────

st.subheader("상태 요약")
b1, b2, b3, b4 = st.columns(4)
b1.metric("정상", f"{cs.normal_count}개")
b2.metric("경고", f"{cs.warning_count}개")
b3.metric("위험", f"{cs.critical_count}개")
b4.metric("과부하", f"{cs.overload_count}개")

st.divider()

# ── 총부하 추세 차트 ───────────────────────────────────────────────────────────

st.subheader("총부하 추세 (12h)")
trend_df = pd.DataFrame(
    [{"timestamp": p.timestamp, "total_load_mw": p.value} for p in result.trend_points]
)
if not trend_df.empty:
    trend_fig = go.Figure(go.Scatter(
        x=trend_df["timestamp"],
        y=trend_df["total_load_mw"],
        mode="lines+markers",
        line={"width": 3, "color": "#1f77b4"},
        marker={"size": 6},
        hovertemplate="%{x|%H:%M}<br>%{y:,.0f} MW<extra></extra>",
    ))
    trend_fig.update_layout(
        height=280,
        margin={"t": 10, "b": 30, "l": 10, "r": 10},
        xaxis_title="시각", yaxis_title="총부하 (MW)",
        hovermode="x unified", plot_bgcolor="white",
    )
    st.plotly_chart(trend_fig, width="stretch")

st.divider()

# ── 선로별 이용률 차트 + 위험 선로 패널 ────────────────────────────────────────

col_chart, col_danger = st.columns([3, 2])

with col_chart:
    st.subheader("선로별 이용률")
    bar_x = [f"{l.from_bus_name}→{l.to_bus_name}" for l in lines]
    bar_y = [l.utilization * 100 for l in lines]
    bar_colors = [_STATUS_COLOR[l.status] for l in lines]

    fig = go.Figure(go.Bar(
        x=bar_x, y=bar_y, marker_color=bar_colors,
        text=[f"{v:.1f}%" for v in bar_y], textposition="outside",
        hovertemplate="%{x}<br>이용률: %{y:.1f}%<extra></extra>",
    ))
    fig.add_hline(y=70, line_dash="dash", line_color=_STATUS_COLOR["warning"],
                  annotation_text="경고 70%", annotation_position="top right")
    fig.add_hline(y=90, line_dash="dash", line_color=_STATUS_COLOR["critical"],
                  annotation_text="위험 90%", annotation_position="top right")
    fig.update_layout(
        yaxis_title="이용률 (%)", yaxis_range=[0, max(bar_y) * 1.2 + 5],
        xaxis_tickangle=-30, height=400,
        margin=dict(t=30, b=10, l=10, r=10), plot_bgcolor="white",
    )
    st.plotly_chart(fig, width="stretch")

with col_danger:
    st.subheader("위험·경고 선로")
    danger_lines = sorted(
        [l for l in lines if l.status in ("overload", "critical", "warning")],
        key=lambda l: l.utilization, reverse=True,
    )
    if danger_lines:
        for l in danger_lines:
            color = {"warning": "orange", "critical": "red", "overload": "violet"}[l.status]
            st.markdown(
                f":{color}[**[{l.line_id}] {l.from_bus_name} → {l.to_bus_name}**]  \n"
                f"이용률 **{l.utilization * 100:.1f}%** &nbsp;|&nbsp; "
                f"{l.flow_mw} MW / {l.capacity_mw:.0f} MW &nbsp;|&nbsp; "
                f":{color}[{_STATUS_LABEL[l.status]}]"
            )
            st.divider()
    else:
        st.success("위험·경고 선로가 없습니다.")

# ── 전체 선로 상태표 ───────────────────────────────────────────────────────────

st.subheader("전체 선로 상태표")
rows = [
    {
        "선로 ID": l.line_id,
        "구간": f"{l.from_bus_name} → {l.to_bus_name}",
        "흐름 (MW)": l.flow_mw,
        "용량 (MW)": l.capacity_mw,
        "이용률 (%)": round(l.utilization * 100, 1),
        "손실 (MW)": l.loss_mw,
        "위험도": l.risk_level,
        "상태": _STATUS_LABEL[l.status],
    }
    for l in sorted(lines, key=lambda l: l.utilization, reverse=True)
]
df = pd.DataFrame(rows)

selected_line_event = st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="monitoring_line_status_table",
)

selected_line_id = _resolve_selected_line_id(selected_line_event, rows)
valid_line_ids = {row["선로 ID"] for row in rows}
if selected_line_id is not None:
    st.session_state.monitoring_selected_line_id = selected_line_id
else:
    selected_line_id = st.session_state.get("monitoring_selected_line_id")
    if selected_line_id not in valid_line_ids:
        selected_line_id = None
        st.session_state.monitoring_selected_line_id = None

if selected_line_id is not None:
    st.caption(f"선택 선로: `{selected_line_id}`")

st.divider()

# ── 지도 overlay ──────────────────────────────────────────────────────────────

st.subheader("선로 지도")
render_map_overlay(
    map_overlay,
    map_capability=map_capability,
    selected_line_id=selected_line_id,
)
st.caption(map_overlay.summary)
st.caption(
    f"지도 모드: {map_overlay.metadata.get('rendering_mode')}  |  "
    f"좌표계: {map_overlay.metadata.get('coordinate_system')}  |  "
    f"고도: {map_overlay.metadata.get('elevation_source')}"
)

overlay_extra_warnings = _overlay_warnings_for_display(result, map_overlay.warnings)
if overlay_extra_warnings:
    with st.expander("지도 fallback 및 좌표 메타데이터", expanded=False):
        if map_overlay.fallback.enabled:
            st.caption(
                f"Fallback: `{map_overlay.fallback.mode}`  |  "
                f"{map_overlay.fallback.reason}"
            )
        for warning in overlay_extra_warnings:
            st.caption(f"- {warning}")

st.caption(
    f"기준 시각: {result.created_at:%Y-%m-%d %H:%M:%S}  |  "
    f"소스: {result.source}  |  부하 배율: {result.load_scale:.2f}×"
)
