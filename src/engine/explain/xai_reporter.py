# 모델 또는 시뮬레이션 결과에 대한 사람이 읽기 쉬운 설명을 생성한다.
from __future__ import annotations

from math import isfinite

from src.data.schemas import (
    LineStressSnapshot,
    StressAnalysisResult,
    XaiGridExplanation,
)


SCENARIO_REROUTE_EFFECT_RATIO = 0.30
XAI_RULE_VERSION = "line-stress-rules-v1"


def build_line_xai_explanation(
    line_stress: LineStressSnapshot,
    *,
    stress_analysis: StressAnalysisResult | None = None,
) -> XaiGridExplanation:
    """선로 stress 수치를 규칙 기반 xAI 설명으로 변환한다."""

    capacity_mw = max(0.0, float(line_stress.capacity_mw))
    capacity_margin_mw = _capacity_margin_mw(line_stress)
    estimated_rerouted_mw = _estimated_rerouted_mw(line_stress)
    after_scenario_flow_mw = max(
        0.0,
        line_stress.scenario_flow_mw - estimated_rerouted_mw,
    )
    after_total_flow_mw = (
        line_stress.base_flow_mw
        + after_scenario_flow_mw
        + line_stress.predicted_flow_mw
    )
    after_utilization = _utilization(after_total_flow_mw, capacity_mw)
    after_capacity_margin_mw = capacity_mw - after_total_flow_mw
    bottleneck = _is_bottleneck(line_stress, stress_analysis)

    before_metrics = {
        "capacity_mw": round(capacity_mw, 3),
        "base_flow_mw": round(line_stress.base_flow_mw, 3),
        "scenario_flow_mw": round(line_stress.scenario_flow_mw, 3),
        "predicted_flow_mw": round(line_stress.predicted_flow_mw, 3),
        "total_flow_mw": round(line_stress.total_flow_mw, 3),
        "utilization": round(line_stress.utilization, 6),
        "capacity_margin_mw": round(capacity_margin_mw, 3),
        "shared_route_count": line_stress.shared_route_count,
        "status": line_stress.status,
        "risk_level": line_stress.risk_level,
        "is_bottleneck": bottleneck,
    }
    after_metrics = {
        "assumption": "시나리오 추가 흐름의 30%를 우회 경로로 분산",
        "estimated_rerouted_mw": round(estimated_rerouted_mw, 3),
        "estimated_scenario_flow_mw": round(after_scenario_flow_mw, 3),
        "estimated_total_flow_mw": round(after_total_flow_mw, 3),
        "estimated_utilization": round(after_utilization, 6),
        "estimated_capacity_margin_mw": round(after_capacity_margin_mw, 3),
        "estimated_utilization_delta": round(
            after_utilization - line_stress.utilization,
            6,
        ),
    }

    causes = _bottleneck_causes(
        line_stress,
        bottleneck=bottleneck,
        capacity_margin_mw=capacity_margin_mw,
    )
    actions = _recommended_actions(
        line_stress,
        after_utilization=after_utilization,
        capacity_margin_mw=capacity_margin_mw,
        bottleneck=bottleneck,
    )
    reason_summary = _reason_summary(
        line_stress,
        capacity_mw=capacity_mw,
        capacity_margin_mw=capacity_margin_mw,
    )

    return XaiGridExplanation(
        target_id=line_stress.line_id,
        target_type="line",
        title=f"{line_stress.line_id} xAI 설명",
        reason_summary=reason_summary,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        bottleneck_causes=causes,
        recommended_actions=actions,
        contributing_scenario_ids=list(line_stress.contributing_scenario_ids),
        confidence=_confidence(line_stress, bottleneck=bottleneck),
        metadata={
            "rule_version": XAI_RULE_VERSION,
            "from_node_id": line_stress.from_node_id,
            "to_node_id": line_stress.to_node_id,
            "from_node_name": line_stress.from_node_name,
            "to_node_name": line_stress.to_node_name,
            "bottleneck": bottleneck,
        },
    )


def xai_explanation_to_metadata(
    explanation: XaiGridExplanation,
) -> dict[str, object]:
    """MapOverlayLine metadata에 붙일 수 있는 평탄화된 xAI 결과."""

    return {
        "xai_target_id": explanation.target_id,
        "xai_target_type": explanation.target_type,
        "xai_title": explanation.title,
        "xai_reason_summary": explanation.reason_summary,
        "xai_before_metrics": dict(explanation.before_metrics),
        "xai_after_metrics": dict(explanation.after_metrics),
        "xai_bottleneck_causes": list(explanation.bottleneck_causes),
        "xai_recommended_actions": list(explanation.recommended_actions),
        "xai_contributing_scenario_ids": list(explanation.contributing_scenario_ids),
        "xai_confidence": explanation.confidence,
        "xai_rule_version": explanation.metadata.get("rule_version", ""),
    }


def _reason_summary(
    line_stress: LineStressSnapshot,
    *,
    capacity_mw: float,
    capacity_margin_mw: float,
) -> str:
    status_label = _status_label(line_stress.status)
    return (
        f"{line_stress.line_id} 선로는 누적 이용률 {line_stress.utilization:.1%}로 "
        f"{status_label} 상태입니다. 기본 흐름 {line_stress.base_flow_mw:.1f}MW, "
        f"시나리오 추가 {line_stress.scenario_flow_mw:.1f}MW, 예측 추가 "
        f"{line_stress.predicted_flow_mw:.1f}MW가 합산되어 용량 {capacity_mw:.1f}MW 대비 "
        f"총 {line_stress.total_flow_mw:.1f}MW를 사용하고 있으며, "
        f"현재 용량 여유는 {capacity_margin_mw:.1f}MW입니다."
    )


def _bottleneck_causes(
    line_stress: LineStressSnapshot,
    *,
    bottleneck: bool,
    capacity_margin_mw: float,
) -> list[str]:
    causes: list[str] = []
    if line_stress.status == "overload":
        causes.append("누적 흐름이 선로 용량을 초과해 과부하 상태입니다.")
    elif line_stress.status == "critical":
        causes.append("누적 이용률이 90% 이상으로 위험 구간에 진입했습니다.")
    elif line_stress.status == "warning":
        causes.append("누적 이용률이 70% 이상으로 경고 구간에 진입했습니다.")

    if line_stress.shared_route_count >= 2:
        causes.append(
            f"{line_stress.shared_route_count}개 송전 시나리오가 같은 선로를 공유합니다."
        )
    if line_stress.scenario_flow_mw > 0.0:
        causes.append(
            f"송전 시나리오가 {line_stress.scenario_flow_mw:.1f}MW를 추가로 사용합니다."
        )
    if line_stress.predicted_flow_mw > 0.0:
        causes.append(
            f"예측 부하가 향후 피크 기준 {line_stress.predicted_flow_mw:.1f}MW를 추가합니다."
        )
    if capacity_margin_mw < 0.0:
        causes.append(
            f"용량 여유가 {capacity_margin_mw:.1f}MW로 음수여서 구조적 완화가 필요합니다."
        )
    elif 0.0 <= capacity_margin_mw <= line_stress.capacity_mw * 0.1:
        causes.append(
            f"용량 여유가 {capacity_margin_mw:.1f}MW로 전체 용량의 10% 이하입니다."
        )
    if bottleneck and not causes:
        causes.append("공유 경로 또는 상위 이용률 기준으로 병목 후보에 포함됐습니다.")
    if not causes:
        causes.append("현재 수치상 즉시 조치가 필요한 병목 원인은 크지 않습니다.")
    return causes


def _recommended_actions(
    line_stress: LineStressSnapshot,
    *,
    after_utilization: float,
    capacity_margin_mw: float,
    bottleneck: bool,
) -> list[str]:
    actions: list[str] = []
    if line_stress.shared_route_count >= 2:
        actions.append("기여 송전 시나리오 중 하나를 대체 경로로 분산하는 방안을 우선 검토하세요.")
    if line_stress.status in {"critical", "overload"}:
        actions.append("해당 선로를 통과하는 신규 송전 시나리오는 제한하고 우회 경로를 먼저 탐색하세요.")
    if line_stress.predicted_flow_mw > 0.0:
        actions.append("예측 피크 시간대에는 해당 선로의 추가 송전을 보수적으로 제한하세요.")
    if after_utilization >= 0.70 or capacity_margin_mw <= 0.0:
        actions.append("우회 분산만으로 이용률이 충분히 내려가지 않으면 신규 송전탑/우회 선로 후보를 검토하세요.")
    if bottleneck and not actions:
        actions.append("현재 병목 후보이므로 인접 선로와 경로 분산 가능성을 확인하세요.")
    if not actions:
        actions.append("현재는 모니터링을 유지하고 추가 시나리오 생성 시 재평가하세요.")
    return actions


def _estimated_rerouted_mw(line_stress: LineStressSnapshot) -> float:
    if line_stress.shared_route_count < 2 and line_stress.status == "normal":
        return 0.0
    return max(0.0, line_stress.scenario_flow_mw * SCENARIO_REROUTE_EFFECT_RATIO)


def _capacity_margin_mw(line_stress: LineStressSnapshot) -> float:
    raw_margin = line_stress.metadata.get("capacity_margin_mw")
    if isinstance(raw_margin, (float, int)) and isfinite(float(raw_margin)):
        return float(raw_margin)
    return line_stress.capacity_mw - line_stress.total_flow_mw


def _is_bottleneck(
    line_stress: LineStressSnapshot,
    stress_analysis: StressAnalysisResult | None,
) -> bool:
    if stress_analysis is None:
        return line_stress.status in {"warning", "critical", "overload"} or line_stress.shared_route_count >= 2
    return line_stress.line_id in set(stress_analysis.bottleneck_line_ids)


def _utilization(total_flow_mw: float, capacity_mw: float) -> float:
    if capacity_mw <= 0.0:
        return float("inf") if total_flow_mw > 0.0 else 0.0
    return max(0.0, total_flow_mw) / capacity_mw


def _status_label(status: str) -> str:
    labels = {
        "normal": "정상",
        "warning": "경고",
        "critical": "위험",
        "overload": "과부하",
    }
    return labels.get(status, status)


def _confidence(
    line_stress: LineStressSnapshot,
    *,
    bottleneck: bool,
) -> float:
    confidence = 0.64
    if line_stress.base_flow_mw > 0.0:
        confidence += 0.08
    if line_stress.scenario_flow_mw > 0.0:
        confidence += 0.08
    if line_stress.predicted_flow_mw > 0.0:
        confidence += 0.06
    if bottleneck:
        confidence += 0.06
    return round(min(confidence, 0.92), 2)
