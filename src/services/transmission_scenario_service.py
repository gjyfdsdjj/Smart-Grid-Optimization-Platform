# app 운영 콘솔의 송전 시나리오 생명주기를 관리한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import heapq
import math
from typing import Iterable

from src.data.loaders import load_grid_dataset_or_default
from src.data.schemas import (
    GridDataset,
    GridLine,
    GridNode,
    ResultSource,
    RoutePoint,
    RouteResult,
    TransmissionScenario,
)


DEFAULT_TRANSFER_MW = 300.0
ROUTE_COST_DISTANCE_FACTOR = 0.44
ROUTE_LOAD_SCALE_COST_FACTOR = 0.04


class TransmissionScenarioService:
    """지도 선택 기반 송전 시나리오를 생성하고 경로 계약에 연결한다."""

    def create_transmission_scenario(
        self,
        *,
        start_node_id: str,
        end_node_id: str,
        grid_dataset: GridDataset | None = None,
        requested_transfer_mw: float = DEFAULT_TRANSFER_MW,
        scenario_route_id: str = "",
        scenario_index: int | None = None,
        label: str = "",
        route: RouteResult | None = None,
        created_at: datetime | None = None,
        source: ResultSource = "manual",
    ) -> TransmissionScenario:
        """시작/종료 노드 선택값을 `TransmissionScenario`로 정규화한다."""

        resolved_at = _round_to_second(created_at or datetime.now())
        dataset = grid_dataset or load_grid_dataset_or_default(created_at=resolved_at)
        node_by_id = _grid_node_by_id(dataset)
        start_id = str(start_node_id or "").strip()
        end_id = str(end_node_id or "").strip()
        warnings = self._validate_selection(
            start_node_id=start_id,
            end_node_id=end_id,
            requested_transfer_mw=requested_transfer_mw,
            node_by_id=node_by_id,
        )
        status = "draft" if warnings else "active"
        resolved_id = scenario_route_id.strip() if scenario_route_id else _build_scenario_route_id(
            start_node_id=start_id,
            end_node_id=end_id,
            scenario_index=scenario_index,
            created_at=resolved_at,
        )
        start_name = _node_name(start_id, node_by_id)
        end_name = _node_name(end_id, node_by_id)

        transmission_scenario = TransmissionScenario(
            scenario_route_id=resolved_id,
            label=label or _build_label(
                start_node_id=start_id,
                end_node_id=end_id,
                start_node_name=start_name,
                end_node_name=end_name,
                requested_transfer_mw=requested_transfer_mw,
            ),
            start_node_id=start_id,
            end_node_id=end_id,
            start_node_name=start_name,
            end_node_name=end_name,
            requested_transfer_mw=float(requested_transfer_mw),
            status=status,
            created_at=resolved_at,
            source=source,
            warnings=warnings,
            metadata={
                "grid_node_count": len(dataset.nodes),
                "grid_line_count": len(dataset.lines),
            },
        )

        if route is None:
            return transmission_scenario

        return self.attach_route_to_scenario(
            transmission_scenario,
            route=route,
            grid_dataset=dataset,
        )

    def build_route_between_nodes(
        self,
        *,
        start_node_id: str,
        end_node_id: str,
        grid_dataset: GridDataset,
        load_scale: float = 1.0,
        route_id: str = "",
    ) -> RouteResult:
        """GridLine 연결망 위에서 시작/종료 노드 간 A* 경로를 만든다."""

        node_by_id = _grid_node_by_id(grid_dataset)
        start_id = str(start_node_id or "").strip()
        end_id = str(end_node_id or "").strip()
        if start_id not in node_by_id:
            raise ValueError(f"송전 시작 노드를 GridDataset에서 찾을 수 없습니다: {start_id}")
        if end_id not in node_by_id:
            raise ValueError(f"송전 종료 노드를 GridDataset에서 찾을 수 없습니다: {end_id}")
        if start_id == end_id:
            raise ValueError("송전 시작 노드와 종료 노드는 달라야 합니다.")

        adjacency = _build_route_adjacency(grid_dataset.lines, load_scale=load_scale)
        path_node_ids, total_distance_km = _astar_path(
            start_node_id=start_id,
            end_node_id=end_id,
            node_by_id=node_by_id,
            adjacency=adjacency,
        )
        if len(path_node_ids) < 2:
            raise ValueError(f"{start_id} -> {end_id} 경로를 찾을 수 없습니다.")

        used_line_ids, warnings = self.resolve_used_line_ids(
            path_node_ids,
            grid_dataset.lines,
        )
        if warnings or len(used_line_ids) != len(path_node_ids) - 1:
            raise ValueError(
                f"{start_id} -> {end_id} 경로의 GridLine 매핑이 완전하지 않습니다: {warnings}"
            )

        route_points = [
            RoutePoint(
                point_id=node.node_id,
                label=node.node_name,
                latitude=node.latitude,
                longitude=node.longitude,
            )
            for node in (node_by_id[node_id] for node_id in path_node_ids)
        ]
        resolved_route_id = route_id.strip() or f"tx-route-{start_id.lower()}-{end_id.lower()}"
        estimated_cost = _estimate_route_cost(total_distance_km, load_scale)

        return RouteResult(
            route_id=resolved_route_id,
            start_bus_id=start_id,
            end_bus_id=end_id,
            path_node_ids=path_node_ids,
            waypoints=route_points,
            total_distance_km=round(total_distance_km, 3),
            estimated_cost=estimated_cost,
            source="astar",
            summary=(
                f"{_node_name(start_id, node_by_id)}에서 {_node_name(end_id, node_by_id)}까지 "
                f"GridLine {len(used_line_ids)}개를 사용하는 A* 자동 송전 경로입니다."
            ),
        )

    def attach_route_to_scenario(
        self,
        transmission_scenario: TransmissionScenario,
        *,
        route: RouteResult,
        grid_dataset: GridDataset | None = None,
    ) -> TransmissionScenario:
        """A*/휴리스틱 `RouteResult`를 송전 시나리오에 연결한다."""

        dataset = grid_dataset or load_grid_dataset_or_default(
            created_at=transmission_scenario.created_at
        )
        path_node_ids = list(route.path_node_ids)
        if not path_node_ids and route.start_bus_id and route.end_bus_id:
            path_node_ids = [route.start_bus_id, route.end_bus_id]

        warnings = list(transmission_scenario.warnings)
        if route.start_bus_id and route.start_bus_id != transmission_scenario.start_node_id:
            warnings.append(
                f"경로 시작 노드({route.start_bus_id})가 시나리오 시작 노드({transmission_scenario.start_node_id})와 다릅니다."
            )
        if route.end_bus_id and route.end_bus_id != transmission_scenario.end_node_id:
            warnings.append(
                f"경로 종료 노드({route.end_bus_id})가 시나리오 종료 노드({transmission_scenario.end_node_id})와 다릅니다."
            )

        used_line_ids, line_warnings = self.resolve_used_line_ids(
            path_node_ids,
            dataset.lines,
        )
        warnings.extend(line_warnings)

        return replace(
            transmission_scenario,
            route=route,
            path_node_ids=path_node_ids,
            used_line_ids=used_line_ids,
            source=route.source,
            warnings=warnings,
            metadata={
                **transmission_scenario.metadata,
                "route_id": route.route_id,
                "route_source": route.source,
                "path_node_count": len(path_node_ids),
                "used_line_count": len(used_line_ids),
            },
        )

    def resolve_used_line_ids(
        self,
        path_node_ids: Iterable[str],
        grid_lines: Iterable[GridLine],
    ) -> tuple[list[str], list[str]]:
        """경로의 인접 노드쌍을 GridLine ID 목록으로 변환한다."""

        resolved_path = [str(node_id).strip() for node_id in path_node_ids if str(node_id).strip()]
        if len(resolved_path) < 2:
            return [], ["경로 노드가 2개 미만이라 사용 선로를 계산할 수 없습니다."]

        line_by_pair = _line_by_node_pair(grid_lines)
        used_line_ids: list[str] = []
        warnings: list[str] = []
        for from_node_id, to_node_id in zip(resolved_path, resolved_path[1:]):
            line = line_by_pair.get((from_node_id, to_node_id))
            if line is None:
                warnings.append(
                    f"{from_node_id} -> {to_node_id} 구간에 대응하는 GridLine을 찾을 수 없습니다."
                )
                continue
            used_line_ids.append(line.line_id)

        return used_line_ids, warnings

    def list_active_transmission_scenarios(
        self,
        scenarios: Iterable[TransmissionScenario],
    ) -> list[TransmissionScenario]:
        """stress 분석 입력으로 사용할 active 송전 시나리오만 반환한다."""

        return [
            scenario
            for scenario in scenarios
            if scenario.status == "active"
        ]

    def disable_transmission_scenario(
        self,
        scenarios: Iterable[TransmissionScenario],
        scenario_route_id: str,
    ) -> list[TransmissionScenario]:
        """시나리오를 삭제하지 않고 비활성 상태로 표시한다."""

        resolved_id = scenario_route_id.strip()
        return [
            replace(scenario, status="disabled")
            if scenario.scenario_route_id == resolved_id
            else scenario
            for scenario in scenarios
        ]

    def _validate_selection(
        self,
        *,
        start_node_id: str,
        end_node_id: str,
        requested_transfer_mw: float,
        node_by_id: dict[str, GridNode],
    ) -> list[str]:
        warnings: list[str] = []
        if not start_node_id:
            warnings.append("송전 시작 노드가 비어 있어 시나리오를 draft 상태로 유지합니다.")
        if not end_node_id:
            warnings.append("송전 종료 노드가 비어 있어 시나리오를 draft 상태로 유지합니다.")
        if start_node_id and end_node_id and start_node_id == end_node_id:
            warnings.append("송전 시작 노드와 종료 노드가 같아 시나리오를 draft 상태로 유지합니다.")
        if start_node_id and start_node_id not in node_by_id:
            warnings.append(f"송전 시작 노드를 GridDataset에서 찾을 수 없습니다: {start_node_id}")
        if end_node_id and end_node_id not in node_by_id:
            warnings.append(f"송전 종료 노드를 GridDataset에서 찾을 수 없습니다: {end_node_id}")
        if requested_transfer_mw <= 0:
            warnings.append("요청 송전량은 0MW보다 커야 하므로 시나리오를 draft 상태로 유지합니다.")
        return warnings


def _round_to_second(value: datetime) -> datetime:
    return value.replace(microsecond=0)


def _grid_node_by_id(dataset: GridDataset) -> dict[str, GridNode]:
    return {
        node.node_id: node
        for node in dataset.nodes
    }


def _node_name(node_id: str, node_by_id: dict[str, GridNode]) -> str:
    node = node_by_id.get(node_id)
    return node.node_name if node is not None else ""


def _build_scenario_route_id(
    *,
    start_node_id: str,
    end_node_id: str,
    scenario_index: int | None,
    created_at: datetime,
) -> str:
    if scenario_index is not None:
        prefix = f"{max(0, scenario_index):03d}"
    else:
        prefix = created_at.strftime("%Y%m%d%H%M%S")
    start_part = start_node_id or "START"
    end_part = end_node_id or "END"
    return f"TX_{prefix}_{start_part}_{end_part}"


def _build_label(
    *,
    start_node_id: str,
    end_node_id: str,
    start_node_name: str,
    end_node_name: str,
    requested_transfer_mw: float,
) -> str:
    start_label = start_node_name or start_node_id or "시작 노드 미지정"
    end_label = end_node_name or end_node_id or "종료 노드 미지정"
    return f"{start_label} -> {end_label} {requested_transfer_mw:.0f}MW 송전"


def _line_by_node_pair(grid_lines: Iterable[GridLine]) -> dict[tuple[str, str], GridLine]:
    line_by_pair: dict[tuple[str, str], GridLine] = {}
    for line in grid_lines:
        if line.status == "out_of_service":
            continue
        line_by_pair.setdefault((line.from_node_id, line.to_node_id), line)
        if line.is_bidirectional:
            line_by_pair.setdefault((line.to_node_id, line.from_node_id), line)
    return line_by_pair


def _build_route_adjacency(
    grid_lines: Iterable[GridLine],
    *,
    load_scale: float,
) -> dict[str, list[tuple[str, float, float, str]]]:
    adjacency: dict[str, list[tuple[str, float, float, str]]] = {}
    for line in grid_lines:
        if line.status == "out_of_service":
            continue

        distance_km = max(0.001, float(line.distance_km or 0.001))
        traversal_cost = distance_km * (1.0 + max(0.0, load_scale - 1.0) * ROUTE_LOAD_SCALE_COST_FACTOR)
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
            _heuristic_km(node_by_id[start_node_id], node_by_id[end_node_id]),
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
            next_cost = cost_so_far + traversal_cost
            if next_cost >= best_cost_by_node.get(next_node_id, float("inf")):
                continue
            best_cost_by_node[next_node_id] = next_cost
            priority = next_cost + _heuristic_km(node_by_id[next_node_id], node_by_id[end_node_id])
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

    raise ValueError(f"{start_node_id} -> {end_node_id} 연결 경로를 GridLine에서 찾을 수 없습니다.")


def _heuristic_km(start_node: GridNode, end_node: GridNode) -> float:
    radius_km = 6371.0
    lat_a = math.radians(start_node.latitude)
    lat_b = math.radians(end_node.latitude)
    delta_lat = math.radians(end_node.latitude - start_node.latitude)
    delta_lon = math.radians(end_node.longitude - start_node.longitude)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * radius_km * math.atan2(math.sqrt(haversine), math.sqrt(1.0 - haversine))


def _estimate_route_cost(total_distance_km: float, load_scale: float) -> float:
    load_penalty = 1.0 + max(0.0, load_scale - 1.0) * 0.08
    return round(total_distance_km * ROUTE_COST_DISTANCE_FACTOR * load_penalty, 3)
