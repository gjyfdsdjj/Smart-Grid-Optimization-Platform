from __future__ import annotations

from datetime import datetime

from src.data.schemas import InstallationPoint
from src.data.schemas import RouteResult, ScoreBreakdown
from src.engine.search.score_function import (
    CandidateImpactInput,
    CandidateScoreInput,
    build_recommendation,
    calculate_score,
    rank_recommendations,
)
from src.services.simulation_service import SimulationService


def _route(
    route_id: str,
    *,
    distance_km: float,
    source: str = "astar",
) -> RouteResult:
    return RouteResult(
        route_id=route_id,
        start_bus_id="NODE_START",
        end_bus_id="NODE_END",
        total_distance_km=distance_km,
        estimated_cost=distance_km * 0.5,
        source=source,
        summary="test route",
    )


def test_calculate_score_reflects_route_and_counterfactual_impact():
    score_input = CandidateScoreInput(
        candidate_id="TOWER_TEST",
        candidate_label="테스트 후보",
        distance_km=40.0,
        construction_cost=12.0,
        congestion_relief=20.0,
        environmental_risk=2.0,
        policy_risk=1.0,
        load_scale=1.0,
    )
    route = _route("route-test", distance_km=52.0)

    without_impact = calculate_score(score_input, route=route)
    with_impact = calculate_score(
        score_input,
        route=route,
        impact=CandidateImpactInput(
            peak_utilization_improvement=8.0,
            risk_line_reduction=2.0,
            loss_reduction_mw=1.5,
            operating_margin_gain=8.0,
        ),
    )

    assert with_impact.congestion_relief > without_impact.congestion_relief
    assert with_impact.total_score > without_impact.total_score
    assert any("counterfactual 개선 근거" in note for note in with_impact.notes)
    assert any("혼잡 보상" in note for note in with_impact.notes)
    assert any("경로 입력: 52.0km" in note for note in with_impact.notes)


def test_load_scale_increases_congestion_relief_bonus():
    base_input = CandidateScoreInput(
        candidate_id="TOWER_LOAD",
        candidate_label="부하 보정 후보",
        distance_km=40.0,
        construction_cost=12.0,
        congestion_relief=20.0,
        environmental_risk=2.0,
        policy_risk=1.0,
        load_scale=1.0,
    )
    high_load_input = CandidateScoreInput(
        candidate_id="TOWER_LOAD",
        candidate_label="부하 보정 후보",
        distance_km=40.0,
        construction_cost=12.0,
        congestion_relief=20.0,
        environmental_risk=2.0,
        policy_risk=1.0,
        load_scale=1.2,
    )

    base_score = calculate_score(base_input, route=_route("base", distance_km=40.0))
    high_load_score = calculate_score(
        high_load_input,
        route=_route("high", distance_km=40.0),
    )

    assert high_load_score.congestion_relief > base_score.congestion_relief
    assert any("부하 보정 3.6점" in note for note in high_load_score.notes)


def test_rank_recommendations_uses_stable_tie_breaks():
    same_score = ScoreBreakdown(total_score=80.0)
    ranked = rank_recommendations([
        build_recommendation(
            "TOWER_LONG",
            "긴 경로",
            _route("long", distance_km=60.0),
            same_score,
            "long",
        ),
        build_recommendation(
            "TOWER_SHORT",
            "짧은 경로",
            _route("short", distance_km=30.0),
            same_score,
            "short",
        ),
        build_recommendation(
            "TOWER_ALPHA",
            "알파 경로",
            _route("alpha", distance_km=30.0),
            same_score,
            "alpha",
        ),
    ])

    assert [(item.rank, item.candidate_id) for item in ranked] == [
        (1, "TOWER_ALPHA"),
        (2, "TOWER_SHORT"),
        (3, "TOWER_LONG"),
    ]


def test_simulation_options_are_grid_nodes_not_legacy_sites():
    service = SimulationService()

    bus_options = service.list_bus_options()
    candidate_options = service.list_candidate_options()

    assert bus_options
    assert candidate_options
    assert any(bus_id.startswith("PLANT_") for bus_id, _ in bus_options)
    assert any(bus_id.startswith("TOWER_") for bus_id, _ in bus_options)
    assert all(candidate_id.startswith("TOWER_") for candidate_id, _ in candidate_options)


def test_run_simulation_recommendations_have_explainable_score_notes():
    service = SimulationService()
    result = service.run_simulation(service.build_default_input(load_scale=1.0))

    assert result.source == "astar"
    assert result.fallback.mode == "none"
    assert [recommendation.rank for recommendation in result.recommendations] == list(
        range(1, len(result.recommendations) + 1)
    )
    assert len(result.recommendations) >= 12
    assert all(recommendation.candidate_id.startswith("TOWER_") for recommendation in result.recommendations)

    for recommendation in result.recommendations:
        assert recommendation.route is not None
        assert recommendation.score is not None
        assert recommendation.route.source == "astar"
        assert "거리 보정" in recommendation.route.summary
        assert any("총점 산식" in note for note in recommendation.score.notes)
        assert any("비용 반영" in note for note in recommendation.score.notes)
        assert any("혼잡 보상" in note for note in recommendation.score.notes)
        assert "A* 경로 길이" in recommendation.rationale
        assert "환경·정책 리스크" in recommendation.rationale


def test_top_recommendation_notes_reference_counterfactual_delta():
    service = SimulationService()
    result = service.run_simulation(service.build_default_input(load_scale=1.0))
    top_recommendation = result.recommendations[0]
    peak_delta = next(
        delta
        for delta in result.deltas
        if delta.metric_id == "peak_utilization"
    )

    assert top_recommendation.candidate_id.startswith("TOWER_")
    assert any("counterfactual 개선 근거" in note for note in top_recommendation.score.notes)
    assert any("counterfactual bonus" in note for note in top_recommendation.score.notes)
    assert f"최대 이용률을 {peak_delta.improvement:.1f}%p" in top_recommendation.rationale


def test_candidate_impact_failure_does_not_force_global_simulation_fallback(monkeypatch):
    service = SimulationService()

    def fail_counterfactual(**kwargs):
        raise RuntimeError("forced candidate impact failure")

    monkeypatch.setattr(service, "_build_counterfactual_monitoring", fail_counterfactual)

    result = service.run_simulation(service.build_default_input(load_scale=1.0))

    assert result.source == "astar"
    assert result.fallback.mode == "none"
    assert result.recommendations
    assert any("heuristic impact 사용" in warning for warning in result.warnings)
    assert any(
        "heuristic impact 사용" in note
        for recommendation in result.recommendations
        for note in recommendation.score.notes
    )


def test_empty_candidate_selection_uses_service_warning_once():
    service = SimulationService()
    simulation_input = service.build_default_input(candidate_site_ids=[])

    result = service.run_simulation(simulation_input)

    assert len(result.simulation_input.candidate_site_ids) >= 12
    assert all(candidate_id.startswith("TOWER_") for candidate_id in result.simulation_input.candidate_site_ids)
    assert sum("후보지가 비어" in warning for warning in result.warnings) == 1
    assert result.recommendations


def test_user_installation_candidate_generates_recommendation_and_route():
    service = SimulationService()
    installation = InstallationPoint(
        installation_id="tower-manual-001",
        label="수동 송전탑 후보",
        kind="transmission_tower",
        latitude=36.42,
        longitude=127.72,
        voltage_kv=345.0,
        created_at=datetime(2026, 5, 17, 22, 0),
    )
    simulation_input = service.build_default_input(
        candidate_site_ids=[],
        user_candidate_points=[installation],
        load_scale=1.0,
    )

    result = service.run_simulation(simulation_input)
    recommendation = result.recommendations[0]

    assert result.simulation_input.candidate_site_ids == []
    assert result.simulation_input.user_candidate_points == [installation]
    assert [item.candidate_id for item in result.recommendations] == ["USER_TOWER_TOWER_MANUAL_001"]
    assert recommendation.candidate_label == "사용자 추가 송전탑: 수동 송전탑 후보"
    assert recommendation.route is not None
    assert "USER_TOWER_TOWER_MANUAL_001" in recommendation.route.path_node_ids
    assert any(
        point.point_id == "USER_TOWER_TOWER_MANUAL_001"
        and point.latitude == installation.latitude
        and point.longitude == installation.longitude
        for point in recommendation.route.waypoints
    )


def test_simulation_loss_delta_unit_is_mw_for_mock_and_actual():
    service = SimulationService()

    mock_result = service.run_mock_simulation(service.build_default_input())
    actual_result = service.run_simulation(service.build_default_input())

    mock_loss_delta = next(delta for delta in mock_result.deltas if delta.metric_id == "losses")
    actual_loss_delta = next(delta for delta in actual_result.deltas if delta.metric_id == "losses")

    assert mock_loss_delta.unit == "MW"
    assert actual_loss_delta.unit == "MW"


def test_counterfactual_deltas_improve_core_metrics_and_vary_by_candidate():
    service = SimulationService()
    results = [
        service.run_simulation(
            service.build_default_input(
                load_scale=1.2,
                candidate_site_ids=[candidate_id],
            )
        )
        for candidate_id in ["TOWER_GUMI", "TOWER_DAEJEON", "TOWER_JEJU"]
    ]

    loss_after_values = set()
    for result in results:
        deltas = {
            delta.metric_id: delta
            for delta in result.deltas
        }

        assert deltas["peak_utilization"].improvement > 0
        assert deltas["peak_utilization"].status == "improved"
        assert deltas["risk_lines"].improvement > 0
        assert deltas["risk_lines"].status == "improved"
        assert deltas["losses"].improvement > 0
        assert deltas["losses"].status == "improved"
        loss_after_values.add(deltas["losses"].after_value)

    assert len(loss_after_values) > 1
