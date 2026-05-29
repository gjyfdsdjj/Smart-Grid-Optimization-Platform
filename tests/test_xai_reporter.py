from datetime import datetime

from src.data.schemas import LineStressSnapshot, ScenarioContext, StressAnalysisResult
from src.engine.explain.xai_reporter import (
    build_line_xai_explanation,
    xai_explanation_to_metadata,
)


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="xai-test",
        title="xAI test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )


def test_line_xai_explains_shared_route_prediction_and_capacity_margin() -> None:
    line_stress = LineStressSnapshot(
        line_id="LINE_AB",
        from_node_id="A",
        to_node_id="B",
        capacity_mw=500.0,
        base_flow_mw=260.0,
        scenario_flow_mw=180.0,
        predicted_flow_mw=35.0,
        total_flow_mw=475.0,
        utilization=0.95,
        risk_level="high",
        contributing_scenario_ids=["TX_001", "TX_002"],
        shared_route_count=2,
        status="critical",
        metadata={"capacity_margin_mw": 25.0},
    )
    stress_analysis = StressAnalysisResult(
        scenario=_scenario(),
        created_at=datetime(2026, 5, 29, 16, 0),
        load_scale=1.0,
        bottleneck_line_ids=["LINE_AB"],
    )

    explanation = build_line_xai_explanation(
        line_stress,
        stress_analysis=stress_analysis,
    )

    assert explanation.target_id == "LINE_AB"
    assert explanation.target_type == "line"
    assert "누적 이용률 95.0%" in explanation.reason_summary
    assert any("2개 송전 시나리오" in cause for cause in explanation.bottleneck_causes)
    assert any("예측 부하" in cause for cause in explanation.bottleneck_causes)
    assert any("대체 경로" in action for action in explanation.recommended_actions)
    assert any("신규 송전탑" in action for action in explanation.recommended_actions)
    assert explanation.before_metrics["capacity_margin_mw"] == 25.0
    assert explanation.after_metrics["estimated_rerouted_mw"] == 54.0
    assert explanation.after_metrics["estimated_utilization"] < explanation.before_metrics["utilization"]
    assert explanation.contributing_scenario_ids == ["TX_001", "TX_002"]
    assert explanation.confidence is not None
    assert explanation.confidence >= 0.8


def test_line_xai_metadata_is_flattened_for_map_overlay() -> None:
    line_stress = LineStressSnapshot(
        line_id="LINE_SHARED",
        from_node_id="A",
        to_node_id="B",
        capacity_mw=500.0,
        base_flow_mw=150.0,
        scenario_flow_mw=30.0,
        total_flow_mw=180.0,
        utilization=0.36,
        contributing_scenario_ids=["TX_001", "TX_002"],
        shared_route_count=2,
        status="normal",
    )

    metadata = xai_explanation_to_metadata(
        build_line_xai_explanation(line_stress)
    )

    assert metadata["xai_target_id"] == "LINE_SHARED"
    assert metadata["xai_target_type"] == "line"
    assert metadata["xai_reason_summary"]
    assert metadata["xai_bottleneck_causes"]
    assert metadata["xai_recommended_actions"]
    assert metadata["xai_before_metrics"]["shared_route_count"] == 2
    assert metadata["xai_after_metrics"]["estimated_rerouted_mw"] == 9.0
