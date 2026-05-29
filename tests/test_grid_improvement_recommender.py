from datetime import datetime

from src.data.schemas import (
    GridDataset,
    GridLine,
    GridNode,
    RoutePoint,
    RouteResult,
    ScenarioContext,
    TransmissionScenario,
)
from src.engine.recommend.grid_improvement_recommender import (
    build_grid_improvement_proposal,
)
from src.engine.stress.route_stress_analyzer import analyze_route_stress


def _node(node_id: str, latitude: float, longitude: float) -> GridNode:
    return GridNode(
        node_id=node_id,
        node_name=f"{node_id} 노드",
        node_type="transmission_tower",
        latitude=latitude,
        longitude=longitude,
        voltage_kv=345.0,
    )


def _line(
    line_id: str,
    from_node_id: str,
    to_node_id: str,
    distance_km: float,
) -> GridLine:
    return GridLine(
        line_id=line_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        voltage_kv=345.0,
        capacity_mw=500.0,
        reactance_pu=0.04,
        distance_km=distance_km,
    )


def _dataset() -> GridDataset:
    return GridDataset(
        nodes=[
            _node("A", 36.0, 127.0),
            _node("B", 36.0, 127.2),
            _node("C", 36.2, 127.0),
            _node("D", 36.2, 127.2),
        ],
        lines=[
            _line("LINE_AB", "A", "B", 20.0),
            _line("LINE_BD", "B", "D", 20.0),
            _line("LINE_AC", "A", "C", 25.0),
            _line("LINE_CD", "C", "D", 25.0),
        ],
    )


def _scenario_context() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="improvement-test",
        title="개선안 테스트",
        created_at=datetime(2026, 5, 29, 17, 0),
    )


def _transmission_scenario() -> TransmissionScenario:
    route = RouteResult(
        route_id="tx-route-001",
        start_bus_id="A",
        end_bus_id="D",
        path_node_ids=["A", "B", "D"],
        waypoints=[
            RoutePoint("A", "A 노드", 36.0, 127.0),
            RoutePoint("B", "B 노드", 36.0, 127.2),
            RoutePoint("D", "D 노드", 36.2, 127.2),
        ],
        total_distance_km=40.0,
        estimated_cost=17.6,
        source="astar",
    )
    return TransmissionScenario(
        scenario_route_id="TX_001",
        label="A -> D 300MW 송전",
        start_node_id="A",
        end_node_id="D",
        requested_transfer_mw=300.0,
        route=route,
        path_node_ids=list(route.path_node_ids),
        used_line_ids=["LINE_AB", "LINE_BD"],
        status="active",
        source="astar",
    )


def test_grid_improvement_proposal_builds_reroute_and_tower_suggestion() -> None:
    scenario = _scenario_context()
    dataset = _dataset()
    transmission = _transmission_scenario()
    stress = analyze_route_stress(
        scenario=scenario,
        grid_dataset=dataset,
        transmission_scenarios=[transmission],
        created_at=scenario.created_at,
    )

    proposal = build_grid_improvement_proposal(
        scenario=scenario,
        grid_dataset=dataset,
        stress_analysis=stress,
        target_line_id="LINE_BD",
        created_at=scenario.created_at,
    )

    assert proposal.target_line_id == "LINE_BD"
    assert proposal.reroute_candidates
    candidate = proposal.reroute_candidates[0]
    assert candidate.scenario_route_id == "TX_001"
    assert candidate.avoided_line_ids == ["LINE_BD"]
    assert "LINE_BD" not in candidate.rerouted_line_ids
    assert candidate.rerouted_path_node_ids == ["A", "C", "D"]
    assert candidate.before_target_utilization == 0.95
    assert candidate.after_target_utilization < candidate.before_target_utilization
    assert candidate.route is not None
    assert candidate.route.source == "astar"
    assert "목표 선로 이용률" in candidate.rationale

    assert proposal.suggested_nodes
    suggested_node = proposal.suggested_nodes[0]
    assert suggested_node.target_line_id == "LINE_BD"
    assert suggested_node.coordinate_system == "EPSG:4326"
    assert suggested_node.elevation_source == "not_queried"
    assert suggested_node.capacity_mw >= 500.0
    assert suggested_node.expected_utilization_delta < 0.0
    assert suggested_node.metadata["connected_node_ids"] == ["B", "D"]


def test_grid_improvement_proposal_falls_back_for_unknown_line() -> None:
    scenario = _scenario_context()
    dataset = _dataset()
    stress = analyze_route_stress(
        scenario=scenario,
        grid_dataset=dataset,
        transmission_scenarios=[_transmission_scenario()],
        created_at=scenario.created_at,
    )

    proposal = build_grid_improvement_proposal(
        scenario=scenario,
        grid_dataset=dataset,
        stress_analysis=stress,
        target_line_id="UNKNOWN_LINE",
        created_at=scenario.created_at,
    )

    assert proposal.fallback.enabled is True
    assert proposal.reroute_candidates == []
    assert proposal.suggested_nodes == []
