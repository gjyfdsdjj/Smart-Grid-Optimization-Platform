# 병목 선로를 완화할 우회 경로와 신규 송전탑 후보를 제안한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import heapq
import math
import re
from typing import Iterable

from src.data.schemas import (
    FallbackInfo,
    GridDataset,
    GridImprovementProposal,
    GridLine,
    GridNode,
    LineStressSnapshot,
    MonitoringResult,
    RerouteCandidate,
    RoutePoint,
    RouteResult,
    ScenarioContext,
    StressAnalysisResult,
    SuggestedGridNode,
    TransmissionScenario,
)
from src.engine.stress.route_stress_analyzer import analyze_route_stress


MAX_REROUTE_CANDIDATES = 3
NEW_TOWER_RELIEF_RATIO = 0.30
REROUTE_DISTANCE_PENALTY = 0.10
BOTTLENECK_RELIEF_WEIGHT = 18.0
CRITICAL_RELIEF_WEIGHT = 24.0
TARGET_UTILIZATION_WEIGHT = 120.0
MAX_UTILIZATION_WEIGHT = 35.0


def build_grid_improvement_proposal(
    *,
    scenario: ScenarioContext,
    grid_dataset: GridDataset,
    stress_analysis: StressAnalysisResult,
    target_line_id: str,
    load_scale: float = 1.0,
    created_at: datetime | None = None,
    monitoring_result: MonitoringResult | None = None,
    predicted_flow_by_line: dict[str, float] | None = None,
    max_candidates: int = MAX_REROUTE_CANDIDATES,
) -> GridImprovementProposal:
    """선택 선로의 병목을 완화할 경로/노드 개선안을 계산한다."""

    resolved_line_id = str(target_line_id or "").strip()
    resolved_at = (created_at or stress_analysis.created_at or datetime.now()).replace(
        microsecond=0
    )
    proposal_id = _proposal_id(resolved_line_id, resolved_at)
    line_by_id = _line_by_id(grid_dataset.lines)
    node_by_id = _node_by_id(grid_dataset.nodes)
    stress_by_line_id = _stress_by_line_id(stress_analysis.line_stresses)
    target_line = line_by_id.get(resolved_line_id)
    target_stress = stress_by_line_id.get(resolved_line_id)
    warnings = list(stress_analysis.warnings)

    if target_line is None or target_stress is None:
        missing = "GridLine" if target_line is None else "LineStressSnapshot"
        warnings.append(f"{resolved_line_id}의 {missing}을 찾지 못해 개선안을 만들 수 없습니다.")
        return GridImprovementProposal(
            proposal_id=proposal_id,
            target_line_id=resolved_line_id,
            created_at=resolved_at,
            warnings=warnings,
            fallback=FallbackInfo(
                enabled=True,
                mode="manual_override",
                reason="선택 선로의 GridLine 또는 stress 결과가 없어 개선안 생성을 건너뜁니다.",
            ),
        )

    contributing_scenario_ids = _target_contributing_scenario_ids(
        target_line_id=resolved_line_id,
        target_stress=target_stress,
        transmission_scenarios=stress_analysis.transmission_scenarios,
    )
    reroute_candidates: list[RerouteCandidate] = []
    for transmission_scenario in stress_analysis.transmission_scenarios:
        if transmission_scenario.status != "active":
            continue
        if transmission_scenario.scenario_route_id not in contributing_scenario_ids:
            continue
        candidate = _build_reroute_candidate(
            scenario=scenario,
            grid_dataset=grid_dataset,
            stress_analysis=stress_analysis,
            target_line=target_line,
            target_stress=target_stress,
            transmission_scenario=transmission_scenario,
            load_scale=load_scale,
            created_at=resolved_at,
            monitoring_result=monitoring_result,
            predicted_flow_by_line=predicted_flow_by_line,
        )
        if candidate is None:
            warnings.append(
                f"{transmission_scenario.scenario_route_id}는 {resolved_line_id}를 피하는 대체 경로를 찾지 못했습니다."
            )
            continue
        reroute_candidates.append(candidate)

    reroute_candidates = sorted(
        reroute_candidates,
        key=lambda candidate: candidate.score,
        reverse=True,
    )[: max(0, max_candidates)]
    suggested_nodes = _suggested_nodes_for_target_line(
        target_line=target_line,
        target_stress=target_stress,
        node_by_id=node_by_id,
        reroute_candidates=reroute_candidates,
        created_at=resolved_at,
    )
    before_summary = _summary_from_stress(stress_analysis)
    after_summary = _after_summary_from_candidates(
        before_summary=before_summary,
        reroute_candidates=reroute_candidates,
        target_stress=target_stress,
    )
    summary = _proposal_summary(
        target_line_id=resolved_line_id,
        reroute_candidates=reroute_candidates,
        suggested_nodes=suggested_nodes,
    )

    return GridImprovementProposal(
        proposal_id=proposal_id,
        target_line_id=resolved_line_id,
        target_line_label=_line_label(target_line, node_by_id),
        created_at=resolved_at,
        reroute_candidates=reroute_candidates,
        suggested_nodes=suggested_nodes,
        before_summary=before_summary,
        after_summary=after_summary,
        summary=summary,
        warnings=warnings,
        fallback=FallbackInfo(enabled=False),
        metadata={
            "target_status": target_stress.status,
            "target_utilization": target_stress.utilization,
            "target_shared_route_count": target_stress.shared_route_count,
            "contributing_scenario_ids": contributing_scenario_ids,
            "rule_version": "grid-improvement-v1",
        },
    )


def _build_reroute_candidate(
    *,
    scenario: ScenarioContext,
    grid_dataset: GridDataset,
    stress_analysis: StressAnalysisResult,
    target_line: GridLine,
    target_stress: LineStressSnapshot,
    transmission_scenario: TransmissionScenario,
    load_scale: float,
    created_at: datetime,
    monitoring_result: MonitoringResult | None,
    predicted_flow_by_line: dict[str, float] | None,
) -> RerouteCandidate | None:
    node_by_id = _node_by_id(grid_dataset.nodes)
    route = _build_avoiding_route(
        transmission_scenario=transmission_scenario,
        grid_dataset=grid_dataset,
        node_by_id=node_by_id,
        blocked_line_ids={target_line.line_id},
        load_scale=load_scale,
    )
    if route is None:
        return None
    rerouted_line_ids = _used_line_ids(route.path_node_ids, grid_dataset.lines)
    if target_line.line_id in rerouted_line_ids:
        return None

    original_line_ids = list(transmission_scenario.used_line_ids)
    if not original_line_ids:
        original_line_ids = _used_line_ids(
            transmission_scenario.path_node_ids,
            grid_dataset.lines,
        )
    if rerouted_line_ids == original_line_ids:
        return None

    after_scenario = replace(
        transmission_scenario,
        route=route,
        path_node_ids=list(route.path_node_ids),
        used_line_ids=rerouted_line_ids,
        source=route.source,
        metadata={
            **transmission_scenario.metadata,
            "reroute_candidate_target_line_id": target_line.line_id,
            "reroute_candidate_route_id": route.route_id,
        },
    )
    after_scenarios = [
        after_scenario
        if item.scenario_route_id == transmission_scenario.scenario_route_id
        else item
        for item in stress_analysis.transmission_scenarios
    ]
    after_stress = analyze_route_stress(
        scenario=scenario,
        grid_dataset=grid_dataset,
        transmission_scenarios=after_scenarios,
        load_scale=load_scale,
        created_at=created_at,
        monitoring_result=monitoring_result,
        predicted_flow_by_line=predicted_flow_by_line,
    )
    after_target_stress = _stress_by_line_id(after_stress.line_stresses).get(
        target_line.line_id
    )
    before_max_utilization = _max_utilization(stress_analysis.line_stresses)
    after_max_utilization = _max_utilization(after_stress.line_stresses)
    before_target_utilization = float(target_stress.utilization)
    after_target_utilization = (
        float(after_target_stress.utilization)
        if after_target_stress is not None
        else 0.0
    )
    original_distance_km = _scenario_distance_km(transmission_scenario)
    added_distance_km = max(0.0, route.total_distance_km - original_distance_km)
    score = _reroute_score(
        before_target_utilization=before_target_utilization,
        after_target_utilization=after_target_utilization,
        before_max_utilization=before_max_utilization,
        after_max_utilization=after_max_utilization,
        before_bottleneck_count=len(stress_analysis.bottleneck_line_ids),
        after_bottleneck_count=len(after_stress.bottleneck_line_ids),
        before_critical_count=len(stress_analysis.critical_line_ids),
        after_critical_count=len(after_stress.critical_line_ids),
        added_distance_km=added_distance_km,
    )
    candidate_id = (
        f"REROUTE_{_safe_id(transmission_scenario.scenario_route_id)}__"
        f"AVOID_{_safe_id(target_line.line_id)}"
    )

    return RerouteCandidate(
        candidate_id=candidate_id,
        target_line_id=target_line.line_id,
        scenario_route_id=transmission_scenario.scenario_route_id,
        scenario_label=transmission_scenario.label,
        original_path_node_ids=list(transmission_scenario.path_node_ids),
        rerouted_path_node_ids=list(route.path_node_ids),
        original_line_ids=original_line_ids,
        rerouted_line_ids=rerouted_line_ids,
        avoided_line_ids=[target_line.line_id],
        route=route,
        added_distance_km=round(added_distance_km, 3),
        estimated_cost_delta=round(max(0.0, route.estimated_cost - _scenario_cost(transmission_scenario)), 3),
        before_target_utilization=round(before_target_utilization, 6),
        after_target_utilization=round(after_target_utilization, 6),
        before_max_utilization=round(before_max_utilization, 6),
        after_max_utilization=round(after_max_utilization, 6),
        before_bottleneck_line_count=len(stress_analysis.bottleneck_line_ids),
        after_bottleneck_line_count=len(after_stress.bottleneck_line_ids),
        before_critical_line_count=len(stress_analysis.critical_line_ids),
        after_critical_line_count=len(after_stress.critical_line_ids),
        score=round(score, 3),
        rationale=_reroute_rationale(
            scenario_label=transmission_scenario.label,
            target_line_id=target_line.line_id,
            before_utilization=before_target_utilization,
            after_utilization=after_target_utilization,
            added_distance_km=added_distance_km,
        ),
        metadata={
            "after_warning_line_ids": list(after_stress.warning_line_ids),
            "after_critical_line_ids": list(after_stress.critical_line_ids),
            "after_bottleneck_line_ids": list(after_stress.bottleneck_line_ids),
            "new_warning_line_ids": _new_warning_line_ids(
                before=stress_analysis,
                after=after_stress,
            ),
            "route_source": route.source,
        },
    )


def _build_avoiding_route(
    *,
    transmission_scenario: TransmissionScenario,
    grid_dataset: GridDataset,
    node_by_id: dict[str, GridNode],
    blocked_line_ids: set[str],
    load_scale: float,
) -> RouteResult | None:
    start_node_id = transmission_scenario.start_node_id
    end_node_id = transmission_scenario.end_node_id
    if start_node_id not in node_by_id or end_node_id not in node_by_id:
        return None

    adjacency = _route_adjacency(
        grid_dataset.lines,
        blocked_line_ids=blocked_line_ids,
        stress_penalty_line_ids=set(),
        load_scale=load_scale,
    )
    try:
        path_node_ids, distance_km = _astar_path(
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            node_by_id=node_by_id,
            adjacency=adjacency,
        )
    except ValueError:
        return None

    route_points = [
        RoutePoint(
            point_id=node.node_id,
            label=node.node_name,
            latitude=node.latitude,
            longitude=node.longitude,
        )
        for node in (node_by_id[node_id] for node_id in path_node_ids)
    ]
    target_part = "_".join(_safe_id(line_id) for line_id in sorted(blocked_line_ids))
    route_id = f"reroute-{_safe_id(transmission_scenario.scenario_route_id).lower()}-{target_part.lower()}"
    return RouteResult(
        route_id=route_id,
        start_bus_id=start_node_id,
        end_bus_id=end_node_id,
        path_node_ids=path_node_ids,
        waypoints=route_points,
        total_distance_km=round(distance_km, 3),
        estimated_cost=round(distance_km * 0.44 * (1.0 + max(0.0, load_scale - 1.0) * 0.08), 3),
        source="astar",
        summary=(
            f"{transmission_scenario.label}의 병목 선로 {', '.join(sorted(blocked_line_ids))}를 "
            "회피하는 A* 우회 경로입니다."
        ),
    )


def _suggested_nodes_for_target_line(
    *,
    target_line: GridLine,
    target_stress: LineStressSnapshot,
    node_by_id: dict[str, GridNode],
    reroute_candidates: list[RerouteCandidate],
    created_at: datetime,
) -> list[SuggestedGridNode]:
    if not _needs_suggested_node(target_stress, reroute_candidates):
        return []
    from_node = node_by_id.get(target_line.from_node_id)
    to_node = node_by_id.get(target_line.to_node_id)
    if from_node is None or to_node is None:
        return []

    latitude, longitude = _offset_midpoint(from_node, to_node, target_line.distance_km)
    utilization_delta = _suggested_node_utilization_delta(target_stress, reroute_candidates)
    expected_after_utilization = max(0.0, target_stress.utilization + utilization_delta)
    capacity_mw = _recommended_capacity_mw(target_line, target_stress)
    install_cost_billion = _estimated_install_cost_billion(
        distance_km=max(0.0, float(target_line.distance_km)),
        capacity_mw=capacity_mw,
        voltage_kv=target_line.voltage_kv,
    )
    suggested_node_id = f"SUGGESTED_TOWER_{_safe_id(target_line.line_id)}"

    return [
        SuggestedGridNode(
            suggested_node_id=suggested_node_id,
            label=f"{target_stress.from_node_name or target_line.from_node_id} 우회 송전탑 후보",
            latitude=latitude,
            longitude=longitude,
            elevation_m=None,
            coordinate_system="EPSG:4326",
            elevation_source="not_queried",
            voltage_kv=target_line.voltage_kv,
            capacity_mw=capacity_mw,
            height_m=65.0,
            install_cost_billion=install_cost_billion,
            target_line_id=target_line.line_id,
            relief_line_ids=[target_line.line_id],
            expected_utilization_delta=round(utilization_delta, 6),
            reason=(
                f"{target_line.line_id} 병목 구간의 중간 우회점을 만들어 "
                f"예상 이용률을 {target_stress.utilization:.1%}에서 "
                f"{expected_after_utilization:.1%} 수준으로 낮추는 후보입니다."
            ),
            status="proposed",
            created_at=created_at,
            metadata={
                "recommendation_type": "new_transmission_tower",
                "target_from_node_id": target_line.from_node_id,
                "target_to_node_id": target_line.to_node_id,
                "connected_node_ids": [target_line.from_node_id, target_line.to_node_id],
                "expected_after_utilization": round(expected_after_utilization, 6),
                "coordinate_generation": "offset_midpoint",
                "relief_ratio": NEW_TOWER_RELIEF_RATIO,
            },
        )
    ]


def _route_adjacency(
    lines: Iterable[GridLine],
    *,
    blocked_line_ids: set[str],
    stress_penalty_line_ids: set[str],
    load_scale: float,
) -> dict[str, list[tuple[str, float, float, str]]]:
    adjacency: dict[str, list[tuple[str, float, float, str]]] = {}
    for line in lines:
        if line.status == "out_of_service" or line.line_id in blocked_line_ids:
            continue
        distance_km = max(0.001, float(line.distance_km or 0.001))
        status_penalty = 1.0
        if line.status == "planned":
            status_penalty = 1.12
        elif line.status == "candidate":
            status_penalty = 1.08
        stress_penalty = 1.65 if line.line_id in stress_penalty_line_ids else 1.0
        load_penalty = 1.0 + max(0.0, load_scale - 1.0) * 0.04
        traversal_cost = distance_km * status_penalty * stress_penalty * load_penalty
        adjacency.setdefault(line.from_node_id, []).append(
            (line.to_node_id, traversal_cost, distance_km, line.line_id)
        )
        if line.is_bidirectional:
            adjacency.setdefault(line.to_node_id, []).append(
                (line.from_node_id, traversal_cost, distance_km, line.line_id)
            )
    return adjacency


def _astar_path(
    *,
    start_node_id: str,
    end_node_id: str,
    node_by_id: dict[str, GridNode],
    adjacency: dict[str, list[tuple[str, float, float, str]]],
) -> tuple[list[str], float]:
    queue: list[tuple[float, float, str, list[str], float]] = [
        (
            _distance_km(node_by_id[start_node_id], node_by_id[end_node_id]),
            0.0,
            start_node_id,
            [start_node_id],
            0.0,
        )
    ]
    best_cost_by_node: dict[str, float] = {start_node_id: 0.0}

    while queue:
        _, cost_so_far, node_id, path, distance_so_far = heapq.heappop(queue)
        if node_id == end_node_id:
            return path, distance_so_far
        if cost_so_far > best_cost_by_node.get(node_id, float("inf")) + 1e-9:
            continue

        for next_node_id, traversal_cost, distance_km, _ in adjacency.get(node_id, []):
            if next_node_id not in node_by_id:
                continue
            next_cost = cost_so_far + traversal_cost
            if next_cost >= best_cost_by_node.get(next_node_id, float("inf")):
                continue
            best_cost_by_node[next_node_id] = next_cost
            priority = next_cost + _distance_km(node_by_id[next_node_id], node_by_id[end_node_id])
            heapq.heappush(
                queue,
                (
                    priority,
                    next_cost,
                    next_node_id,
                    path + [next_node_id],
                    distance_so_far + distance_km,
                ),
            )

    raise ValueError(f"{start_node_id} -> {end_node_id} 우회 경로를 찾을 수 없습니다.")


def _target_contributing_scenario_ids(
    *,
    target_line_id: str,
    target_stress: LineStressSnapshot,
    transmission_scenarios: list[TransmissionScenario],
) -> list[str]:
    scenario_ids = list(target_stress.contributing_scenario_ids)
    if scenario_ids:
        return list(dict.fromkeys(scenario_ids))
    return [
        scenario.scenario_route_id
        for scenario in transmission_scenarios
        if target_line_id in scenario.used_line_ids
    ]


def _line_by_id(lines: Iterable[GridLine]) -> dict[str, GridLine]:
    return {line.line_id: line for line in lines}


def _node_by_id(nodes: Iterable[GridNode]) -> dict[str, GridNode]:
    return {node.node_id: node for node in nodes}


def _stress_by_line_id(
    line_stresses: Iterable[LineStressSnapshot],
) -> dict[str, LineStressSnapshot]:
    return {stress.line_id: stress for stress in line_stresses}


def _used_line_ids(path_node_ids: list[str], lines: Iterable[GridLine]) -> list[str]:
    line_by_pair: dict[tuple[str, str], GridLine] = {}
    for line in lines:
        if line.status == "out_of_service":
            continue
        line_by_pair.setdefault((line.from_node_id, line.to_node_id), line)
        if line.is_bidirectional:
            line_by_pair.setdefault((line.to_node_id, line.from_node_id), line)

    line_ids: list[str] = []
    for from_node_id, to_node_id in zip(path_node_ids, path_node_ids[1:]):
        line = line_by_pair.get((from_node_id, to_node_id))
        if line is not None:
            line_ids.append(line.line_id)
    return line_ids


def _summary_from_stress(stress_analysis: StressAnalysisResult) -> dict[str, object]:
    return {
        "bottleneck_line_count": len(stress_analysis.bottleneck_line_ids),
        "critical_line_count": len(stress_analysis.critical_line_ids),
        "warning_line_count": len(stress_analysis.warning_line_ids),
        "max_utilization": round(_max_utilization(stress_analysis.line_stresses), 6),
        "max_utilization_line_id": stress_analysis.metadata.get("max_utilization_line_id", ""),
    }


def _after_summary_from_candidates(
    *,
    before_summary: dict[str, object],
    reroute_candidates: list[RerouteCandidate],
    target_stress: LineStressSnapshot,
) -> dict[str, object]:
    if not reroute_candidates:
        return dict(before_summary)
    best = reroute_candidates[0]
    return {
        "target_line_id": target_stress.line_id,
        "best_candidate_id": best.candidate_id,
        "target_utilization": best.after_target_utilization,
        "max_utilization": best.after_max_utilization,
        "bottleneck_line_count": best.after_bottleneck_line_count,
        "critical_line_count": best.after_critical_line_count,
    }


def _proposal_summary(
    *,
    target_line_id: str,
    reroute_candidates: list[RerouteCandidate],
    suggested_nodes: list[SuggestedGridNode],
) -> str:
    parts = [f"{target_line_id} 개선안"]
    if reroute_candidates:
        best = reroute_candidates[0]
        parts.append(
            f"최우선 우회 후보는 {best.scenario_route_id}이며 "
            f"목표 선로 이용률을 {best.before_target_utilization:.1%}에서 "
            f"{best.after_target_utilization:.1%}로 낮춥니다."
        )
    else:
        parts.append("적용 가능한 우회 경로 후보를 찾지 못했습니다.")
    if suggested_nodes:
        parts.append(f"신규 송전탑 후보 {len(suggested_nodes)}개를 함께 제안합니다.")
    return " ".join(parts)


def _line_label(line: GridLine, node_by_id: dict[str, GridNode]) -> str:
    from_node = node_by_id.get(line.from_node_id)
    to_node = node_by_id.get(line.to_node_id)
    from_label = from_node.node_name if from_node is not None else line.from_node_id
    to_label = to_node.node_name if to_node is not None else line.to_node_id
    return f"{from_label} -> {to_label}"


def _max_utilization(line_stresses: list[LineStressSnapshot]) -> float:
    finite_values = [
        float(stress.utilization)
        for stress in line_stresses
        if math.isfinite(float(stress.utilization))
    ]
    return max(finite_values, default=0.0)


def _scenario_distance_km(transmission_scenario: TransmissionScenario) -> float:
    if transmission_scenario.route is not None:
        return max(0.0, float(transmission_scenario.route.total_distance_km))
    raw_value = transmission_scenario.metadata.get("total_distance_km", 0.0)
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return 0.0


def _scenario_cost(transmission_scenario: TransmissionScenario) -> float:
    if transmission_scenario.route is not None:
        return max(0.0, float(transmission_scenario.route.estimated_cost))
    return 0.0


def _reroute_score(
    *,
    before_target_utilization: float,
    after_target_utilization: float,
    before_max_utilization: float,
    after_max_utilization: float,
    before_bottleneck_count: int,
    after_bottleneck_count: int,
    before_critical_count: int,
    after_critical_count: int,
    added_distance_km: float,
) -> float:
    target_drop = before_target_utilization - after_target_utilization
    max_drop = before_max_utilization - after_max_utilization
    bottleneck_drop = before_bottleneck_count - after_bottleneck_count
    critical_drop = before_critical_count - after_critical_count
    return (
        (target_drop * TARGET_UTILIZATION_WEIGHT)
        + (max_drop * MAX_UTILIZATION_WEIGHT)
        + (bottleneck_drop * BOTTLENECK_RELIEF_WEIGHT)
        + (critical_drop * CRITICAL_RELIEF_WEIGHT)
        - (added_distance_km * REROUTE_DISTANCE_PENALTY)
    )


def _reroute_rationale(
    *,
    scenario_label: str,
    target_line_id: str,
    before_utilization: float,
    after_utilization: float,
    added_distance_km: float,
) -> str:
    return (
        f"{scenario_label} 시나리오를 {target_line_id} 밖으로 분산하면 "
        f"목표 선로 이용률이 {before_utilization:.1%}에서 {after_utilization:.1%}로 낮아집니다. "
        f"대신 경로 거리는 약 {added_distance_km:.1f}km 증가합니다."
    )


def _new_warning_line_ids(
    *,
    before: StressAnalysisResult,
    after: StressAnalysisResult,
) -> list[str]:
    before_target_ids = set(before.warning_line_ids) | set(before.critical_line_ids)
    after_target_ids = set(after.warning_line_ids) | set(after.critical_line_ids)
    return sorted(after_target_ids - before_target_ids)


def _needs_suggested_node(
    target_stress: LineStressSnapshot,
    reroute_candidates: list[RerouteCandidate],
) -> bool:
    if target_stress.status in {"warning", "critical", "overload"}:
        return True
    if target_stress.shared_route_count >= 2:
        return True
    if not reroute_candidates:
        return False
    return reroute_candidates[0].after_target_utilization >= 0.70


def _suggested_node_utilization_delta(
    target_stress: LineStressSnapshot,
    reroute_candidates: list[RerouteCandidate],
) -> float:
    if reroute_candidates:
        best_drop = (
            reroute_candidates[0].after_target_utilization
            - reroute_candidates[0].before_target_utilization
        )
        if best_drop < 0.0:
            return round(max(-0.35, best_drop), 6)

    scenario_ratio = 0.0
    if target_stress.capacity_mw > 0:
        scenario_ratio = target_stress.scenario_flow_mw / target_stress.capacity_mw
    return -round(min(0.35, max(0.08, scenario_ratio * NEW_TOWER_RELIEF_RATIO)), 6)


def _recommended_capacity_mw(
    target_line: GridLine,
    target_stress: LineStressSnapshot,
) -> float:
    shortage_mw = max(0.0, target_stress.total_flow_mw - target_line.capacity_mw)
    scenario_flow_mw = max(0.0, target_stress.scenario_flow_mw)
    capacity = max(
        target_line.capacity_mw,
        scenario_flow_mw * 1.25,
        target_line.capacity_mw + shortage_mw * 1.3,
    )
    return round(capacity, 1)


def _estimated_install_cost_billion(
    *,
    distance_km: float,
    capacity_mw: float,
    voltage_kv: float,
) -> float:
    voltage_factor = 1.25 if voltage_kv >= 500.0 else 1.0
    cost = (distance_km * 0.075 * voltage_factor) + (capacity_mw / 1000.0 * 5.8)
    return round(max(1.0, cost), 2)


def _offset_midpoint(
    from_node: GridNode,
    to_node: GridNode,
    distance_km: float,
) -> tuple[float, float]:
    mid_latitude = (from_node.latitude + to_node.latitude) / 2.0
    mid_longitude = (from_node.longitude + to_node.longitude) / 2.0
    delta_latitude = to_node.latitude - from_node.latitude
    delta_longitude = to_node.longitude - from_node.longitude
    norm = math.hypot(delta_latitude, delta_longitude)
    if norm <= 1e-9:
        return round(mid_latitude + 0.04, 6), round(mid_longitude + 0.04, 6)

    offset_degrees = min(0.18, max(0.035, distance_km / 900.0))
    latitude = mid_latitude - (delta_longitude / norm) * offset_degrees
    longitude = mid_longitude + (delta_latitude / norm) * offset_degrees
    return round(latitude, 6), round(longitude, 6)


def _distance_km(left: GridNode, right: GridNode) -> float:
    radius_km = 6371.0
    lat_left = math.radians(left.latitude)
    lat_right = math.radians(right.latitude)
    delta_lat = math.radians(right.latitude - left.latitude)
    delta_lon = math.radians(right.longitude - left.longitude)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_left) * math.cos(lat_right) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * radius_km * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))


def _proposal_id(target_line_id: str, created_at: datetime) -> str:
    line_part = _safe_id(target_line_id or "LINE")
    return f"IMPROVE_{line_part}_{created_at:%Y%m%d%H%M%S}"


def _safe_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return sanitized.upper() or "UNKNOWN"
