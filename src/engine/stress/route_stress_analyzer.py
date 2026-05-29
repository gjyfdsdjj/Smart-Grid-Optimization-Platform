# 송전 시나리오가 기존 GridLine에 누적하는 부하를 계산한다.
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from typing import Iterable

from src.data.schemas import (
    CongestionStatus,
    FallbackInfo,
    GridDataset,
    GridLine,
    GridNode,
    GridPowerProfile,
    LineStatus,
    LineStressSnapshot,
    MonitoringResult,
    NodeStressSnapshot,
    RiskLevel,
    ScenarioContext,
    StressAnalysisResult,
    TransmissionScenario,
)


DEFAULT_BASE_FLOW_RATIO = 0.35
SHARED_ROUTE_BOTTLENECK_MIN = 2
TOP_UTILIZATION_LIMIT = 5
RISK_ORDER: dict[RiskLevel, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def analyze_route_stress(
    *,
    scenario: ScenarioContext,
    grid_dataset: GridDataset,
    transmission_scenarios: list[TransmissionScenario],
    load_scale: float = 1.0,
    created_at: datetime | None = None,
    monitoring_result: MonitoringResult | None = None,
    predicted_flow_by_line: dict[str, float] | None = None,
) -> StressAnalysisResult:
    """active 송전 시나리오를 선로별 누적 이용률로 변환한다."""

    resolved_at = (created_at or grid_dataset.created_at or datetime.now()).replace(microsecond=0)
    active_scenarios = [
        transmission_scenario
        for transmission_scenario in transmission_scenarios
        if transmission_scenario.status == "active"
    ]
    warnings = list(grid_dataset.warnings)
    line_by_id = _grid_line_by_id(grid_dataset.lines)
    line_by_pair = _line_by_node_pair(grid_dataset.lines)
    base_flow_by_line, base_flow_source_by_line, base_flow_warnings = _base_flow_context(
        grid_dataset.lines,
        load_scale=load_scale,
        monitoring_result=monitoring_result,
    )
    raw_predicted_flow_by_line = _normalize_predicted_flow_by_line(
        predicted_flow_by_line
    )
    active_line_ids = {
        line.line_id
        for line in grid_dataset.lines
        if line.status != "out_of_service"
    }
    resolved_predicted_flow_by_line = {
        line_id: flow_mw
        for line_id, flow_mw in raw_predicted_flow_by_line.items()
        if line_id in active_line_ids
    }
    ignored_predicted_line_ids = sorted(
        set(raw_predicted_flow_by_line) - set(resolved_predicted_flow_by_line)
    )
    warnings.extend(base_flow_warnings)
    if ignored_predicted_line_ids:
        warnings.append(
            "RouteStressAnalyzer는 GridDataset의 active 선로가 아닌 예측 선로 "
            f"{', '.join(ignored_predicted_line_ids)}를 stress 누적에서 제외했습니다."
        )

    scenario_flow_by_line: dict[str, float] = defaultdict(float)
    contributing_scenarios_by_line: dict[str, list[str]] = defaultdict(list)
    scenarios_for_node: dict[str, list[str]] = defaultdict(list)

    for transmission_scenario in active_scenarios:
        used_line_ids, line_warnings = _scenario_used_line_ids(
            transmission_scenario,
            line_by_pair=line_by_pair,
        )
        warnings.extend(line_warnings)
        if not used_line_ids:
            warnings.append(
                f"{transmission_scenario.scenario_route_id} 시나리오는 사용 선로가 없어 stress 누적에서 제외했습니다."
            )
            continue

        transfer_mw = max(0.0, float(transmission_scenario.requested_transfer_mw))
        scenario_nodes = set(transmission_scenario.path_node_ids)
        scenario_nodes.update(
            node_id
            for node_id in [transmission_scenario.start_node_id, transmission_scenario.end_node_id]
            if node_id
        )
        for node_id in scenario_nodes:
            scenarios_for_node[node_id].append(transmission_scenario.scenario_route_id)

        for line_id in used_line_ids:
            if line_id not in line_by_id:
                warnings.append(
                    f"{transmission_scenario.scenario_route_id} 시나리오의 {line_id} 선로를 GridDataset에서 찾을 수 없습니다."
                )
                continue
            scenario_flow_by_line[line_id] += transfer_mw
            contributing_scenarios_by_line[line_id].append(transmission_scenario.scenario_route_id)

    line_stresses = _build_line_stresses(
        grid_dataset.lines,
        grid_dataset.nodes,
        base_flow_by_line=base_flow_by_line,
        base_flow_source_by_line=base_flow_source_by_line,
        scenario_flow_by_line=scenario_flow_by_line,
        predicted_flow_by_line=resolved_predicted_flow_by_line,
        contributing_scenarios_by_line=contributing_scenarios_by_line,
    )
    node_stresses = _build_node_stresses(
        grid_dataset,
        line_stresses=line_stresses,
        scenarios_for_node=scenarios_for_node,
        load_scale=load_scale,
    )
    warning_line_ids = [
        line.line_id
        for line in line_stresses
        if line.status == "warning"
    ]
    critical_line_ids = [
        line.line_id
        for line in line_stresses
        if line.status in {"critical", "overload"}
    ]
    shared_route_line_ids = [
        line.line_id
        for line in line_stresses
        if line.shared_route_count >= SHARED_ROUTE_BOTTLENECK_MIN
    ]
    bottleneck_line_ids = _bottleneck_line_ids(
        line_stresses,
        warning_line_ids=warning_line_ids,
        critical_line_ids=critical_line_ids,
        shared_route_line_ids=shared_route_line_ids,
    )
    top_utilization_line_ids = _top_utilization_line_ids(line_stresses)
    max_utilization_line = _max_utilization_line(line_stresses)
    predicted_flow_line_ids = sorted(resolved_predicted_flow_by_line)

    return StressAnalysisResult(
        scenario=scenario,
        created_at=resolved_at,
        load_scale=load_scale,
        transmission_scenarios=active_scenarios,
        line_stresses=line_stresses,
        node_stresses=node_stresses,
        bottleneck_line_ids=bottleneck_line_ids,
        warning_line_ids=warning_line_ids,
        critical_line_ids=critical_line_ids,
        summary=_build_summary(
            active_scenario_count=len(active_scenarios),
            bottleneck_line_count=len(bottleneck_line_ids),
            critical_line_count=len(critical_line_ids),
            line_stresses=line_stresses,
        ),
        warnings=warnings,
        fallback=FallbackInfo(enabled=False),
        metadata={
            "active_scenario_count": len(active_scenarios),
            "input_scenario_count": len(transmission_scenarios),
            "line_count": len(line_stresses),
            "node_count": len(node_stresses),
            "load_scale": load_scale,
            "base_flow_source": _overall_base_flow_source(base_flow_source_by_line),
            "base_flow_source_by_line": dict(base_flow_source_by_line),
            "capacity_ratio_base_flow_line_ids": [
                line_id
                for line_id, source in base_flow_source_by_line.items()
                if source == "capacity_ratio"
            ],
            "shared_route_line_ids": shared_route_line_ids,
            "top_utilization_line_ids": top_utilization_line_ids,
            "max_utilization_line_id": max_utilization_line.line_id if max_utilization_line else "",
            "max_utilization": max_utilization_line.utilization if max_utilization_line else 0.0,
            "bottleneck_rule": "status>=warning or shared_route_count>=2",
            "predicted_flow_source": "prediction_result" if predicted_flow_line_ids else "not_connected",
            "predicted_flow_line_ids": predicted_flow_line_ids,
            "predicted_flow_total_mw": round(sum(resolved_predicted_flow_by_line.values()), 3),
        },
    )


def _base_flow_context(
    lines: Iterable[GridLine],
    *,
    load_scale: float,
    monitoring_result: MonitoringResult | None,
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    monitoring_flow_by_line = _monitoring_flow_by_line(monitoring_result)
    flow_by_line: dict[str, float] = {}
    source_by_line: dict[str, str] = {}
    fallback_line_ids: list[str] = []

    for line in lines:
        if line.status == "out_of_service":
            continue
        if line.line_id in monitoring_flow_by_line:
            flow_by_line[line.line_id] = monitoring_flow_by_line[line.line_id]
            source_by_line[line.line_id] = "monitoring_result"
            continue
        flow_by_line[line.line_id] = (
            max(0.0, line.capacity_mw) * DEFAULT_BASE_FLOW_RATIO * max(0.0, load_scale)
        )
        source_by_line[line.line_id] = "capacity_ratio"
        fallback_line_ids.append(line.line_id)

    warnings: list[str] = []
    if monitoring_result is None and fallback_line_ids:
        warnings.append(
            "RouteStressAnalyzer는 DC Power Flow 결과가 없어 capacity_ratio 기준 기본 선로 흐름을 사용합니다."
        )
    elif fallback_line_ids:
        warnings.append(
            "RouteStressAnalyzer는 DC Power Flow 결과에 없는 선로 "
            f"{', '.join(fallback_line_ids)}에 capacity_ratio 기본 흐름을 적용했습니다."
        )
    return flow_by_line, source_by_line, warnings


def _monitoring_flow_by_line(
    monitoring_result: MonitoringResult | None,
) -> dict[str, float]:
    if monitoring_result is None:
        return {}
    return {
        line_status.line_id: abs(float(line_status.flow_mw))
        for line_status in monitoring_result.line_statuses
        if isinstance(line_status, LineStatus)
    }


def _normalize_predicted_flow_by_line(
    predicted_flow_by_line: dict[str, float] | None,
) -> dict[str, float]:
    if not predicted_flow_by_line:
        return {}

    normalized: dict[str, float] = {}
    for line_id, value in predicted_flow_by_line.items():
        if not line_id:
            continue
        try:
            flow_mw = float(value)
        except (TypeError, ValueError):
            continue
        if not isfinite(flow_mw) or flow_mw <= 0.0:
            continue
        normalized[str(line_id)] = flow_mw
    return normalized


def _scenario_used_line_ids(
    transmission_scenario: TransmissionScenario,
    *,
    line_by_pair: dict[tuple[str, str], GridLine],
) -> tuple[list[str], list[str]]:
    if transmission_scenario.used_line_ids:
        return list(transmission_scenario.used_line_ids), []

    path_node_ids = list(transmission_scenario.path_node_ids)
    if not path_node_ids and transmission_scenario.route is not None:
        path_node_ids = list(transmission_scenario.route.path_node_ids)
    if len(path_node_ids) < 2:
        return [], [
            f"{transmission_scenario.scenario_route_id} 시나리오는 경로 노드가 부족해 사용 선로를 복구할 수 없습니다."
        ]

    used_line_ids: list[str] = []
    warnings: list[str] = []
    for from_node_id, to_node_id in zip(path_node_ids, path_node_ids[1:]):
        line = line_by_pair.get((from_node_id, to_node_id))
        if line is None:
            warnings.append(
                f"{transmission_scenario.scenario_route_id}: {from_node_id} -> {to_node_id} 구간의 GridLine을 찾을 수 없습니다."
            )
            continue
        used_line_ids.append(line.line_id)
    return used_line_ids, warnings


def _build_line_stresses(
    lines: Iterable[GridLine],
    nodes: Iterable[GridNode],
    *,
    base_flow_by_line: dict[str, float],
    base_flow_source_by_line: dict[str, str],
    scenario_flow_by_line: dict[str, float],
    predicted_flow_by_line: dict[str, float],
    contributing_scenarios_by_line: dict[str, list[str]],
) -> list[LineStressSnapshot]:
    node_by_id = _grid_node_by_id(nodes)
    line_stresses: list[LineStressSnapshot] = []
    for line in lines:
        if line.status == "out_of_service":
            continue

        base_flow_mw = base_flow_by_line.get(line.line_id, 0.0)
        scenario_flow_mw = scenario_flow_by_line.get(line.line_id, 0.0)
        predicted_flow_mw = predicted_flow_by_line.get(line.line_id, 0.0)
        total_flow_mw = base_flow_mw + scenario_flow_mw + predicted_flow_mw
        utilization = _utilization(total_flow_mw, line.capacity_mw)
        status = _status_for_utilization(utilization)
        risk_level = _risk_for_utilization(utilization)
        contributing_scenario_ids = contributing_scenarios_by_line.get(line.line_id, [])

        line_stresses.append(
            LineStressSnapshot(
                line_id=line.line_id,
                from_node_id=line.from_node_id,
                to_node_id=line.to_node_id,
                from_node_name=_node_name(line.from_node_id, node_by_id),
                to_node_name=_node_name(line.to_node_id, node_by_id),
                capacity_mw=line.capacity_mw,
                base_flow_mw=round(base_flow_mw, 3),
                scenario_flow_mw=round(scenario_flow_mw, 3),
                predicted_flow_mw=round(predicted_flow_mw, 3),
                total_flow_mw=round(total_flow_mw, 3),
                utilization=round(utilization, 6) if isfinite(utilization) else utilization,
                risk_level=risk_level,
                contributing_scenario_ids=list(contributing_scenario_ids),
                shared_route_count=len(set(contributing_scenario_ids)),
                status=status,
                metadata={
                    "line_status": line.status,
                    "voltage_kv": line.voltage_kv,
                    "distance_km": line.distance_km,
                    "base_flow_source": base_flow_source_by_line.get(
                        line.line_id,
                        "capacity_ratio",
                    ),
                    "capacity_margin_mw": round(line.capacity_mw - total_flow_mw, 3),
                    "scenario_count": len(set(contributing_scenario_ids)),
                    "predicted_flow_source": (
                        "prediction_result"
                        if line.line_id in predicted_flow_by_line
                        else "not_connected"
                    ),
                },
            )
        )
    return line_stresses


def _build_node_stresses(
    grid_dataset: GridDataset,
    *,
    line_stresses: list[LineStressSnapshot],
    scenarios_for_node: dict[str, list[str]],
    load_scale: float,
) -> list[NodeStressSnapshot]:
    profile_by_node_id = {
        profile.node_id: profile
        for profile in grid_dataset.power_profiles
    }
    line_ids_by_node = _line_ids_by_node(grid_dataset.lines)
    line_stresses_by_node = _line_stresses_by_node(line_stresses)

    return [
        _build_node_stress(
            node,
            profile=profile_by_node_id.get(node.node_id),
            connected_line_ids=line_ids_by_node.get(node.node_id, []),
            connected_line_stresses=line_stresses_by_node.get(node.node_id, []),
            connected_scenario_ids=scenarios_for_node.get(node.node_id, []),
            load_scale=load_scale,
        )
        for node in grid_dataset.nodes
    ]


def _build_node_stress(
    node: GridNode,
    *,
    profile: GridPowerProfile | None,
    connected_line_ids: list[str],
    connected_line_stresses: list[LineStressSnapshot],
    connected_scenario_ids: list[str],
    load_scale: float,
) -> NodeStressSnapshot:
    if profile is not None:
        generation_mw = profile.generation_mw
        load_mw = profile.load_mw
        net_injection_mw = profile.net_injection_mw
    else:
        generation_mw = 0.0
        load_mw = node.base_load_mw * max(0.0, load_scale)
        net_injection_mw = generation_mw - load_mw

    return NodeStressSnapshot(
        node_id=node.node_id,
        node_name=node.node_name,
        node_type=node.node_type,
        generation_mw=round(generation_mw, 3),
        load_mw=round(load_mw, 3),
        net_injection_mw=round(net_injection_mw, 3),
        connected_line_ids=list(connected_line_ids),
        connected_scenario_ids=list(dict.fromkeys(connected_scenario_ids)),
        risk_level=_max_risk_level(connected_line_stresses),
        metadata={
            "coordinate_system": node.coordinate_system,
            "elevation_source": node.elevation_source,
            "voltage_kv": node.voltage_kv,
            "connected_line_count": len(connected_line_ids),
            "connected_scenario_count": len(set(connected_scenario_ids)),
            "max_connected_utilization": _max_connected_utilization(
                connected_line_stresses
            ),
            "max_connected_line_id": _max_connected_line_id(
                connected_line_stresses
            ),
        },
    )


def _grid_line_by_id(lines: Iterable[GridLine]) -> dict[str, GridLine]:
    return {
        line.line_id: line
        for line in lines
    }


def _grid_node_by_id(nodes: Iterable[GridNode]) -> dict[str, GridNode]:
    return {
        node.node_id: node
        for node in nodes
    }


def _line_by_node_pair(lines: Iterable[GridLine]) -> dict[tuple[str, str], GridLine]:
    line_by_pair: dict[tuple[str, str], GridLine] = {}
    for line in lines:
        if line.status == "out_of_service":
            continue
        line_by_pair.setdefault((line.from_node_id, line.to_node_id), line)
        if line.is_bidirectional:
            line_by_pair.setdefault((line.to_node_id, line.from_node_id), line)
    return line_by_pair


def _line_ids_by_node(lines: Iterable[GridLine]) -> dict[str, list[str]]:
    line_ids_by_node: dict[str, list[str]] = defaultdict(list)
    for line in lines:
        if line.status == "out_of_service":
            continue
        line_ids_by_node[line.from_node_id].append(line.line_id)
        line_ids_by_node[line.to_node_id].append(line.line_id)
    return line_ids_by_node


def _line_stresses_by_node(
    line_stresses: Iterable[LineStressSnapshot],
) -> dict[str, list[LineStressSnapshot]]:
    line_stresses_by_node: dict[str, list[LineStressSnapshot]] = defaultdict(list)
    for line_stress in line_stresses:
        line_stresses_by_node[line_stress.from_node_id].append(line_stress)
        line_stresses_by_node[line_stress.to_node_id].append(line_stress)
    return line_stresses_by_node


def _node_name(node_id: str, node_by_id: dict[str, GridNode]) -> str:
    node = node_by_id.get(node_id)
    return node.node_name if node is not None else ""


def _utilization(total_flow_mw: float, capacity_mw: float) -> float:
    if capacity_mw > 0:
        return max(0.0, total_flow_mw) / capacity_mw
    return float("inf") if total_flow_mw > 0 else 0.0


def _status_for_utilization(utilization: float) -> CongestionStatus:
    if utilization >= 1.0:
        return "overload"
    if utilization >= 0.90:
        return "critical"
    if utilization >= 0.70:
        return "warning"
    return "normal"


def _risk_for_utilization(utilization: float) -> RiskLevel:
    if utilization >= 1.0:
        return "critical"
    if utilization >= 0.90:
        return "high"
    if utilization >= 0.70:
        return "medium"
    return "low"


def _max_risk_level(line_stresses: list[LineStressSnapshot]) -> RiskLevel:
    if not line_stresses:
        return "low"
    return max(
        (line.risk_level for line in line_stresses),
        key=lambda risk: RISK_ORDER[risk],
    )


def _max_connected_utilization(line_stresses: list[LineStressSnapshot]) -> float:
    return max(
        (line.utilization for line in line_stresses if isfinite(line.utilization)),
        default=0.0,
    )


def _max_connected_line_id(line_stresses: list[LineStressSnapshot]) -> str:
    max_line = _max_utilization_line(line_stresses)
    return max_line.line_id if max_line is not None else ""


def _max_utilization_line(
    line_stresses: list[LineStressSnapshot],
) -> LineStressSnapshot | None:
    finite_lines = [
        line
        for line in line_stresses
        if isfinite(line.utilization)
    ]
    if not finite_lines:
        return None
    return max(finite_lines, key=lambda line: line.utilization)


def _top_utilization_line_ids(
    line_stresses: list[LineStressSnapshot],
    *,
    limit: int = TOP_UTILIZATION_LIMIT,
) -> list[str]:
    sorted_lines = sorted(
        (line for line in line_stresses if isfinite(line.utilization)),
        key=lambda line: line.utilization,
        reverse=True,
    )
    return [
        line.line_id
        for line in sorted_lines[:limit]
    ]


def _bottleneck_line_ids(
    line_stresses: list[LineStressSnapshot],
    *,
    warning_line_ids: list[str],
    critical_line_ids: list[str],
    shared_route_line_ids: list[str],
) -> list[str]:
    bottleneck_ids = set(warning_line_ids)
    bottleneck_ids.update(critical_line_ids)
    bottleneck_ids.update(shared_route_line_ids)
    return [
        line.line_id
        for line in sorted(
            (line for line in line_stresses if line.line_id in bottleneck_ids),
            key=lambda line: (
                line.status not in {"critical", "overload"},
                -(line.utilization if isfinite(line.utilization) else float("inf")),
                line.line_id,
            ),
        )
    ]


def _overall_base_flow_source(base_flow_source_by_line: dict[str, str]) -> str:
    unique_sources = set(base_flow_source_by_line.values())
    if not unique_sources:
        return "none"
    if unique_sources == {"monitoring_result"}:
        return "monitoring_result"
    if unique_sources == {"capacity_ratio"}:
        return "capacity_ratio"
    return "mixed"


def _build_summary(
    *,
    active_scenario_count: int,
    bottleneck_line_count: int,
    critical_line_count: int,
    line_stresses: list[LineStressSnapshot],
) -> str:
    max_utilization = max(
        (line.utilization for line in line_stresses if isfinite(line.utilization)),
        default=0.0,
    )
    if active_scenario_count == 0:
        return (
            "활성 송전 시나리오 없음. "
            f"기본 부하 기준 최대 선로 이용률은 {max_utilization:.1%}입니다."
        )
    return (
        f"활성 송전 시나리오 {active_scenario_count}개 기준으로 "
        f"병목 선로 {bottleneck_line_count}개, 고위험 선로 {critical_line_count}개를 계산했습니다. "
        f"최대 선로 이용률은 {max_utilization:.1%}입니다."
    )
