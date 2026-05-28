# 새 GridDataset seed와 전력 profile을 조립한다.
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from src.data.schemas import (
    GridDataset,
    GridLine,
    GridNode,
    GridPowerProfile,
    InstallationPoint,
    PowerPlantSpec,
    TransmissionTowerSpec,
)


DEFAULT_GRID_TOTAL_LOAD_MW = 7_200.0
DEFAULT_USER_PLANT_CAPACITY_MW = 500.0
DEFAULT_USER_TOWER_BASE_LOAD_MW = 120.0
DEFAULT_USER_TOWER_HEIGHT_M = 65.0
DEFAULT_VOLTAGE_KV = 345.0
DEFAULT_TOWER_NEIGHBOR_COUNT = 2


@dataclass(frozen=True)
class _PlantSeed:
    asset_id: str
    node_id: str
    spec_id: str
    name: str
    latitude: float
    longitude: float
    voltage_kv: float
    region: str
    capacity_mw: float
    fuel_type: str
    min_output_mw: float
    max_output_mw: float
    ramp_rate_mw_per_h: float
    availability: float
    operating_cost: float
    emission_factor: float


@dataclass(frozen=True)
class _TowerSeed:
    asset_id: str
    node_id: str
    spec_id: str
    name: str
    latitude: float
    longitude: float
    voltage_kv: float
    region: str
    base_load_mw: float
    height_m: float
    terrain_slope_deg: float
    install_cost_billion: float
    land_type: str
    environment_risk: float
    policy_risk: float
    accessibility_score: float
    nearest_node_id: str


_DEFAULT_PLANTS: tuple[_PlantSeed, ...] = (
    _PlantSeed("incheon", "PLANT_INCHEON", "PLANT_SPEC_INCHEON", "인천 발전소", 37.4563, 126.7052, 345.0, "수도권", 1800.0, "LNG", 360.0, 1800.0, 300.0, 0.95, 82.0, 0.42),
    _PlantSeed("gwangju", "PLANT_GWANGJU", "PLANT_SPEC_GWANGJU", "광주 발전소", 35.1595, 126.8526, 345.0, "호남권", 1200.0, "LNG", 240.0, 1200.0, 220.0, 0.95, 84.0, 0.42),
    _PlantSeed("sokcho", "PLANT_SOKCHO", "PLANT_SPEC_SOKCHO", "속초 발전소", 38.2070, 128.5918, 345.0, "강원권", 700.0, "LNG", 140.0, 700.0, 150.0, 0.93, 86.0, 0.42),
    _PlantSeed("busan", "PLANT_BUSAN", "PLANT_SPEC_BUSAN", "부산 발전소", 35.1796, 129.0756, 345.0, "동남권", 1600.0, "LNG", 320.0, 1600.0, 280.0, 0.95, 83.0, 0.42),
    _PlantSeed("ulsan", "PLANT_ULSAN", "PLANT_SPEC_ULSAN", "울산 발전소", 35.5384, 129.3114, 345.0, "동남권", 2400.0, "LNG", 480.0, 2400.0, 400.0, 0.96, 80.0, 0.42),
    _PlantSeed("pohang", "PLANT_POHANG", "PLANT_SPEC_POHANG", "포항 발전소", 36.0190, 129.3435, 345.0, "영남권", 1100.0, "LNG", 220.0, 1100.0, 220.0, 0.94, 85.0, 0.42),
)

_DEFAULT_TOWERS: tuple[_TowerSeed, ...] = (
    _TowerSeed("geochang", "TOWER_GEOCHANG", "TOWER_SPEC_GEOCHANG", "거창 송전탑", 35.6867, 127.9095, 345.0, "경남권", 480.0, 68.0, 9.5, 14.8, "mountain", 0.32, 0.22, 0.58, "TOWER_CHANGWON"),
    _TowerSeed("seoul", "TOWER_SEOUL", "TOWER_SPEC_SEOUL", "서울 송전탑", 37.5665, 126.9780, 345.0, "수도권", 1700.0, 62.0, 3.0, 18.5, "urban", 0.42, 0.55, 0.82, "PLANT_INCHEON"),
    _TowerSeed("gangneung", "TOWER_GANGNEUNG", "TOWER_SPEC_GANGNEUNG", "강릉 송전탑", 37.7519, 128.8761, 345.0, "강원권", 520.0, 70.0, 11.0, 15.2, "mountain", 0.36, 0.24, 0.55, "PLANT_SOKCHO"),
    _TowerSeed("daejeon", "TOWER_DAEJEON", "TOWER_SPEC_DAEJEON", "대전 송전탑", 36.3504, 127.3845, 345.0, "충청권", 850.0, 65.0, 5.5, 13.0, "suburban", 0.20, 0.18, 0.78, "TOWER_SEOUL"),
    _TowerSeed("chuncheon", "TOWER_CHUNCHEON", "TOWER_SPEC_CHUNCHEON", "춘천 송전탑", 37.8813, 127.7298, 345.0, "강원권", 430.0, 66.0, 8.8, 14.2, "mountain", 0.30, 0.20, 0.62, "TOWER_SEOUL"),
    _TowerSeed("jeju", "TOWER_JEJU", "TOWER_SPEC_JEJU", "제주도 송전탑", 33.4996, 126.5312, 154.0, "제주권", 380.0, 58.0, 7.2, 16.0, "island", 0.38, 0.30, 0.50, "TOWER_HAENAM"),
    _TowerSeed("gumi", "TOWER_GUMI", "TOWER_SPEC_GUMI", "구미 송전탑", 36.1195, 128.3446, 345.0, "경북권", 620.0, 64.0, 4.5, 12.4, "industrial", 0.18, 0.16, 0.80, "TOWER_SANGJU"),
    _TowerSeed("daegu", "TOWER_DAEGU", "TOWER_SPEC_DAEGU", "대구 송전탑", 35.8714, 128.6014, 345.0, "영남권", 1050.0, 63.0, 3.8, 13.1, "urban", 0.24, 0.28, 0.84, "TOWER_GUMI"),
    _TowerSeed("changwon", "TOWER_CHANGWON", "TOWER_SPEC_CHANGWON", "창원 송전탑", 35.2279, 128.6811, 345.0, "경남권", 780.0, 64.0, 5.2, 13.7, "industrial", 0.22, 0.20, 0.76, "PLANT_BUSAN"),
    _TowerSeed("yeongcheon", "TOWER_YEONGCHEON", "TOWER_SPEC_YEONGCHEON", "영천 송전탑", 35.9733, 128.9388, 345.0, "경북권", 410.0, 66.0, 6.4, 13.4, "rural", 0.21, 0.18, 0.72, "TOWER_DAEGU"),
    _TowerSeed("sangju", "TOWER_SANGJU", "TOWER_SPEC_SANGJU", "상주 송전탑", 36.4109, 128.1591, 345.0, "경북권", 360.0, 65.0, 6.8, 13.3, "rural", 0.22, 0.17, 0.70, "TOWER_DAEJEON"),
    _TowerSeed("haenam", "TOWER_HAENAM", "TOWER_SPEC_HAENAM", "해남 송전탑", 34.5733, 126.5993, 345.0, "호남권", 340.0, 67.0, 7.5, 14.1, "coastal", 0.29, 0.21, 0.61, "PLANT_GWANGJU"),
)


def build_default_grid_dataset(
    *,
    user_installations: Iterable[InstallationPoint] | None = None,
    created_at: datetime | None = None,
    load_scale: float = 1.0,
    total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
    include_power_profiles: bool = True,
    include_grid_lines: bool = True,
) -> GridDataset:
    """기본 발전소/송전탑과 사용자 설치 지점을 새 GridDataset으로 묶는다.

    이 함수는 5~8단계의 기본 Grid seed다. 서비스 계산 연결은 후속 단계에서
    진행하지만, 지도 overlay에 필요한 양방향 GridLine은 여기서 생성한다.
    """

    resolved_at = _resolve_created_at(created_at)
    nodes, plants, towers = _build_default_assets()
    warnings: list[str] = []

    user_nodes, user_plants, user_towers, user_warnings = build_user_grid_assets(
        user_installations or []
    )
    nodes.extend(user_nodes)
    plants.extend(user_plants)
    towers.extend(user_towers)
    warnings.extend(user_warnings)
    nodes, plants, towers, duplicate_warnings = _dedupe_assets(nodes, plants, towers)
    warnings.extend(duplicate_warnings)

    lines: list[GridLine] = []
    line_warnings: list[str] = []
    if include_grid_lines:
        lines, line_warnings = build_grid_lines(nodes, tower_candidates=towers)
        warnings.extend(line_warnings)

    dataset = GridDataset(
        nodes=nodes,
        lines=lines,
        plants=plants,
        tower_candidates=towers,
        created_at=resolved_at,
        source="default_asset",
        warnings=warnings,
        metadata={
            "grid_stage": "7-8" if include_grid_lines else "5-6",
            "line_generation_status": "generated" if include_grid_lines else "pending_step_7",
            "default_total_load_mw": total_load_mw,
            "load_scale": load_scale,
            "sources": _dataset_sources(user_nodes),
            "line_count": len(lines),
        },
    )
    if include_power_profiles:
        profiles, profile_warnings = build_grid_power_profiles(
            dataset,
            created_at=resolved_at,
            load_scale=load_scale,
            total_load_mw=total_load_mw,
        )
        dataset.power_profiles = profiles
        dataset.warnings.extend(profile_warnings)
        dataset.metadata["profile_count"] = len(profiles)

    return dataset


def build_grid_lines(
    nodes: list[GridNode],
    *,
    tower_candidates: list[TransmissionTowerSpec] | None = None,
    tower_neighbor_count: int = DEFAULT_TOWER_NEIGHBOR_COUNT,
) -> tuple[list[GridLine], list[str]]:
    """GridNode 사이의 양방향 송전망 연결을 생성한다."""

    if not nodes:
        return [], ["GridLine을 생성할 GridNode가 없습니다."]

    warnings: list[str] = []
    line_by_pair: dict[tuple[str, str], GridLine] = {}
    node_by_id = {node.node_id: node for node in nodes}
    default_towers = [
        node
        for node in nodes
        if node.node_type == "transmission_tower"
    ]
    user_towers = [
        node
        for node in nodes
        if node.node_type == "user_transmission_tower"
    ]
    tower_nodes = default_towers + user_towers
    plant_nodes = [
        node
        for node in nodes
        if node.node_type in {"power_plant", "user_power_plant"}
    ]
    tower_spec_by_node_id = {
        tower.node_id: tower
        for tower in tower_candidates or []
    }

    if not tower_nodes:
        return [], ["송전탑 GridNode가 없어 GridLine을 생성하지 못했습니다."]

    backbone_towers = default_towers or tower_nodes
    for from_node, to_node in _minimum_spanning_edges(backbone_towers):
        _add_grid_line(
            line_by_pair,
            from_node,
            to_node,
            tower_spec_by_node_id=tower_spec_by_node_id,
            connection_reason="tower_backbone",
        )

    for tower in backbone_towers:
        for neighbor in _nearest_nodes(tower, backbone_towers, tower_neighbor_count):
            _add_grid_line(
                line_by_pair,
                tower,
                neighbor,
                tower_spec_by_node_id=tower_spec_by_node_id,
                connection_reason="tower_redundancy",
            )

    for plant in plant_nodes:
        connection_count = _plant_connection_count(plant)
        for tower in _nearest_nodes(plant, tower_nodes, connection_count):
            _add_grid_line(
                line_by_pair,
                plant,
                tower,
                tower_spec_by_node_id=tower_spec_by_node_id,
                connection_reason="plant_interconnection",
            )

    for user_tower in user_towers:
        target_towers = default_towers or [
            node
            for node in tower_nodes
            if node.node_id != user_tower.node_id
        ]
        for tower in _nearest_nodes(user_tower, target_towers, 2):
            _add_grid_line(
                line_by_pair,
                user_tower,
                tower,
                tower_spec_by_node_id=tower_spec_by_node_id,
                connection_reason="user_tower_interconnection",
            )

    lines = sorted(line_by_pair.values(), key=lambda line: line.line_id)
    connected_node_ids = _connected_node_ids(nodes, lines)
    missing_node_ids = set(node_by_id) - connected_node_ids
    if missing_node_ids:
        warnings.append(f"GridLine에 연결되지 않은 노드: {', '.join(sorted(missing_node_ids))}")

    return lines, warnings


def build_user_grid_assets(
    user_installations: Iterable[InstallationPoint],
) -> tuple[list[GridNode], list[PowerPlantSpec], list[TransmissionTowerSpec], list[str]]:
    """랜딩에서 저장한 InstallationPoint를 GridNode와 상세 spec으로 변환한다."""

    nodes: list[GridNode] = []
    plants: list[PowerPlantSpec] = []
    towers: list[TransmissionTowerSpec] = []
    warnings: list[str] = []

    for installation in user_installations:
        if not isinstance(installation, InstallationPoint):
            warnings.append("InstallationPoint가 아닌 사용자 설치 항목을 제외했습니다.")
            continue
        if installation.kind == "power_plant":
            node, plant = _user_power_plant_assets(installation)
            nodes.append(node)
            plants.append(plant)
            continue
        if installation.kind == "transmission_tower":
            node, tower = _user_tower_assets(installation)
            nodes.append(node)
            towers.append(tower)
            continue
        warnings.append(
            f"{installation.installation_id}는 GridNode 변환 대상이 아닌 kind={installation.kind}입니다."
        )

    return nodes, plants, towers, warnings


def build_grid_power_profiles(
    dataset: GridDataset,
    *,
    created_at: datetime | None = None,
    load_scale: float = 1.0,
    total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
) -> tuple[list[GridPowerProfile], list[str]]:
    """GridDataset 노드별 발전/부하/순주입 profile을 만든다."""

    resolved_at = _resolve_created_at(created_at or dataset.created_at)
    resolved_load_scale = _validate_positive_number(load_scale, "load_scale")
    resolved_total_load = _validate_positive_number(total_load_mw, "total_load_mw") * resolved_load_scale
    warnings: list[str] = []
    node_by_id = {node.node_id: node for node in dataset.nodes}
    load_by_node_id = _allocate_load(dataset.nodes, resolved_total_load)
    generation_by_node_id, slack_node_id, generation_warnings = _allocate_generation(
        dataset.plants,
        resolved_total_load,
    )
    warnings.extend(generation_warnings)

    if slack_node_id:
        mismatch = sum(load_by_node_id.values()) - sum(generation_by_node_id.values())
        if abs(mismatch) > 1e-6:
            generation_by_node_id[slack_node_id] = generation_by_node_id.get(slack_node_id, 0.0) + mismatch
            warnings.append(
                f"발전/부하 균형 차이 {mismatch:.3f}MW를 슬랙 후보 {slack_node_id}에 보정했습니다."
            )
    elif dataset.nodes:
        warnings.append("발전소가 없어 슬랙 후보를 선택하지 못했습니다.")

    total_generation = sum(generation_by_node_id.values())
    total_load = sum(load_by_node_id.values())
    profiles: list[GridPowerProfile] = []
    plant_by_node_id = {plant.node_id: plant for plant in dataset.plants}

    for node in dataset.nodes:
        generation_mw = generation_by_node_id.get(node.node_id, 0.0)
        load_mw = load_by_node_id.get(node.node_id, 0.0)
        plant = plant_by_node_id.get(node.node_id)
        metadata: dict[str, object] = {
            "node_type": node.node_type,
            "profile_source": "grid_builder",
            "base_load_mw": node.base_load_mw,
        }
        if plant is not None:
            available_capacity = _available_capacity(plant)
            metadata.update(
                {
                    "plant_id": plant.plant_id,
                    "available_capacity_mw": available_capacity,
                    "min_output_mw": plant.min_output_mw,
                    "max_output_mw": plant.max_output_mw,
                }
            )
            if generation_mw > plant.max_output_mw + 1e-6:
                metadata["exceeds_max_output"] = True
                warnings.append(
                    f"{plant.node_id} 발전 배분 {generation_mw:.1f}MW가 max_output_mw {plant.max_output_mw:.1f}MW를 초과합니다."
                )
            if 0.0 < generation_mw < plant.min_output_mw - 1e-6:
                metadata["below_min_output"] = True
                warnings.append(
                    f"{plant.node_id} 발전 배분 {generation_mw:.1f}MW가 min_output_mw {plant.min_output_mw:.1f}MW보다 낮습니다."
                )

        profiles.append(
            GridPowerProfile(
                node_id=node.node_id,
                timestamp=resolved_at,
                generation_mw=round(generation_mw, 6),
                load_mw=round(load_mw, 6),
                net_injection_mw=round(generation_mw - load_mw, 6),
                load_weight=round(load_mw / total_load, 8) if total_load > 0 else 0.0,
                generation_weight=round(generation_mw / total_generation, 8) if total_generation > 0 else 0.0,
                is_slack_candidate=(node.node_id == slack_node_id),
                metadata=metadata,
            )
        )

    missing_profile_node_ids = set(node_by_id) - {profile.node_id for profile in profiles}
    if missing_profile_node_ids:
        warnings.append(f"전력 profile이 생성되지 않은 노드: {', '.join(sorted(missing_profile_node_ids))}")

    return profiles, warnings


def grid_node_id_for_installation(installation: InstallationPoint) -> str:
    """사용자 설치 지점의 GridNode ID를 만든다."""

    raw_id = _sanitize_identifier(installation.installation_id)
    if installation.kind == "power_plant":
        return f"USER_PLANT_{raw_id}"
    if installation.kind == "transmission_tower":
        return f"USER_TOWER_{raw_id}"
    return f"USER_POINT_{raw_id}"


def _minimum_spanning_edges(nodes: list[GridNode]) -> list[tuple[GridNode, GridNode]]:
    if len(nodes) < 2:
        return []

    parent = {node.node_id: node.node_id for node in nodes}

    def find(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(left_id: str, right_id: str) -> bool:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root == right_root:
            return False
        parent[right_root] = left_root
        return True

    pairs = [
        (_geo_distance_km(left, right), left, right)
        for index, left in enumerate(nodes)
        for right in nodes[index + 1:]
    ]
    pairs.sort(key=lambda item: (item[0], item[1].node_id, item[2].node_id))

    edges: list[tuple[GridNode, GridNode]] = []
    for _, left, right in pairs:
        if union(left.node_id, right.node_id):
            edges.append((left, right))
        if len(edges) == len(nodes) - 1:
            break
    return edges


def _nearest_nodes(
    origin: GridNode,
    candidates: list[GridNode],
    count: int,
) -> list[GridNode]:
    if count <= 0:
        return []
    distances = [
        (_geo_distance_km(origin, candidate), candidate)
        for candidate in candidates
        if candidate.node_id != origin.node_id
    ]
    distances.sort(key=lambda item: (item[0], item[1].node_id))
    return [
        candidate
        for _, candidate in distances[:count]
    ]


def _add_grid_line(
    line_by_pair: dict[tuple[str, str], GridLine],
    from_node: GridNode,
    to_node: GridNode,
    *,
    tower_spec_by_node_id: dict[str, TransmissionTowerSpec],
    connection_reason: str,
) -> None:
    left_node, right_node = _canonical_node_pair(from_node, to_node)
    pair = (left_node.node_id, right_node.node_id)
    if pair in line_by_pair:
        existing = line_by_pair[pair]
        existing_reasons = set(existing.metadata.get("connection_reasons", []))
        existing_reasons.add(connection_reason)
        existing.metadata["connection_reasons"] = sorted(existing_reasons)
        return

    distance_km = _geo_distance_km(left_node, right_node)
    voltage_kv = min(left_node.voltage_kv, right_node.voltage_kv)
    status = _grid_line_status(left_node, right_node, distance_km)
    capacity_mw = _line_capacity_mw(voltage_kv, status=status)
    line_by_pair[pair] = GridLine(
        line_id=f"GLINE_{left_node.node_id}__{right_node.node_id}",
        from_node_id=left_node.node_id,
        to_node_id=right_node.node_id,
        voltage_kv=voltage_kv,
        capacity_mw=capacity_mw,
        reactance_pu=_reactance_from_distance(distance_km),
        distance_km=round(distance_km, 3),
        resistance_pu=_resistance_from_distance(distance_km),
        loss_factor=_loss_factor_from_distance(distance_km),
        terrain_risk=_terrain_risk_for_line(
            left_node,
            right_node,
            distance_km,
            tower_spec_by_node_id=tower_spec_by_node_id,
        ),
        is_bidirectional=True,
        status=status,
        source=(
            "user_installation"
            if "user_installation" in {left_node.source, right_node.source}
            else "default_asset"
        ),
        metadata={
            "from_node_type": left_node.node_type,
            "to_node_type": right_node.node_type,
            "connection_reasons": [connection_reason],
            "coordinate_system": "EPSG:4326",
        },
    )


def _canonical_node_pair(left: GridNode, right: GridNode) -> tuple[GridNode, GridNode]:
    if left.node_id <= right.node_id:
        return left, right
    return right, left


def _grid_line_status(
    left: GridNode,
    right: GridNode,
    distance_km: float,
) -> str:
    if "user_installation" in {left.source, right.source}:
        return "candidate"
    if "TOWER_JEJU" in {left.node_id, right.node_id}:
        return "candidate"
    if distance_km >= 180.0:
        return "planned"
    return "active"


def _plant_connection_count(plant: GridNode) -> int:
    raw_capacity = plant.metadata.get("capacity_mw")
    try:
        capacity_mw = float(raw_capacity)
    except (TypeError, ValueError):
        capacity_mw = DEFAULT_USER_PLANT_CAPACITY_MW
    return 2 if capacity_mw >= 1_500.0 else 1


def _line_capacity_mw(voltage_kv: float, *, status: str) -> float:
    if voltage_kv >= 500.0:
        base_capacity = 4000.0
    elif voltage_kv >= 345.0:
        base_capacity = 2200.0
    elif voltage_kv >= 154.0:
        base_capacity = 700.0
    else:
        base_capacity = 400.0

    if status == "candidate":
        return round(base_capacity * 0.75, 1)
    if status == "planned":
        return round(base_capacity * 0.85, 1)
    return base_capacity


def _reactance_from_distance(distance_km: float) -> float:
    return round(min(0.30, max(0.02, 0.02 + (distance_km / 2000.0))), 5)


def _resistance_from_distance(distance_km: float) -> float:
    return round(min(0.08, max(0.004, distance_km / 12000.0)), 5)


def _loss_factor_from_distance(distance_km: float) -> float:
    return round(min(0.05, max(0.004, distance_km / 9000.0)), 5)


def _terrain_risk_for_line(
    left: GridNode,
    right: GridNode,
    distance_km: float,
    *,
    tower_spec_by_node_id: dict[str, TransmissionTowerSpec],
) -> float:
    risks: list[float] = []
    for node in (left, right):
        tower_spec = tower_spec_by_node_id.get(node.node_id)
        if tower_spec is None:
            continue
        slope_risk = min(1.0, max(0.0, (tower_spec.terrain_slope_deg or 0.0) / 30.0))
        risks.append(
            min(
                1.0,
                max(
                    0.0,
                    (tower_spec.environment_risk * 0.45)
                    + (tower_spec.policy_risk * 0.35)
                    + (slope_risk * 0.20),
                ),
            )
        )

    base_risk = sum(risks) / len(risks) if risks else 0.18
    distance_penalty = min(0.20, distance_km / 1000.0)
    user_penalty = 0.05 if "user_installation" in {left.source, right.source} else 0.0
    return round(min(1.0, base_risk + distance_penalty + user_penalty), 4)


def _connected_node_ids(nodes: list[GridNode], lines: list[GridLine]) -> set[str]:
    if not nodes:
        return set()
    neighbors: dict[str, set[str]] = {
        node.node_id: set()
        for node in nodes
    }
    for line in lines:
        if line.from_node_id not in neighbors or line.to_node_id not in neighbors:
            continue
        neighbors[line.from_node_id].add(line.to_node_id)
        neighbors[line.to_node_id].add(line.from_node_id)

    start_node_id = nodes[0].node_id
    seen = {start_node_id}
    queue = [start_node_id]
    while queue:
        current = queue.pop(0)
        for next_node_id in neighbors[current]:
            if next_node_id in seen:
                continue
            seen.add(next_node_id)
            queue.append(next_node_id)
    return seen


def _geo_distance_km(left: GridNode, right: GridNode) -> float:
    radius_km = 6371.0
    lat_left = math.radians(left.latitude)
    lat_right = math.radians(right.latitude)
    delta_lat = math.radians(right.latitude - left.latitude)
    delta_lon = math.radians(right.longitude - left.longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_left) * math.cos(lat_right) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _build_default_assets() -> tuple[list[GridNode], list[PowerPlantSpec], list[TransmissionTowerSpec]]:
    nodes: list[GridNode] = []
    plants: list[PowerPlantSpec] = []
    towers: list[TransmissionTowerSpec] = []

    for seed in _DEFAULT_PLANTS:
        nodes.append(_plant_node(seed))
        plants.append(_plant_spec(seed))
    for seed in _DEFAULT_TOWERS:
        nodes.append(_tower_node(seed))
        towers.append(_tower_spec(seed))

    return nodes, plants, towers


def _plant_node(seed: _PlantSeed) -> GridNode:
    return GridNode(
        node_id=seed.node_id,
        node_name=seed.name,
        node_type="power_plant",
        latitude=seed.latitude,
        longitude=seed.longitude,
        voltage_kv=seed.voltage_kv,
        region=seed.region,
        base_load_mw=0.0,
        source="default_asset",
        source_id=seed.asset_id,
        metadata={
            "asset_type": "power_plant",
            "default_asset": True,
            "capacity_mw": seed.capacity_mw,
        },
    )


def _plant_spec(seed: _PlantSeed) -> PowerPlantSpec:
    return PowerPlantSpec(
        plant_id=seed.spec_id,
        plant_name=seed.name,
        node_id=seed.node_id,
        capacity_mw=seed.capacity_mw,
        fuel_type=seed.fuel_type,
        min_output_mw=seed.min_output_mw,
        max_output_mw=seed.max_output_mw,
        ramp_rate_mw_per_h=seed.ramp_rate_mw_per_h,
        availability=seed.availability,
        operating_cost=seed.operating_cost,
        emission_factor=seed.emission_factor,
        source="default_asset",
        metadata={"asset_id": seed.asset_id},
    )


def _tower_node(seed: _TowerSeed) -> GridNode:
    return GridNode(
        node_id=seed.node_id,
        node_name=seed.name,
        node_type="transmission_tower",
        latitude=seed.latitude,
        longitude=seed.longitude,
        voltage_kv=seed.voltage_kv,
        region=seed.region,
        base_load_mw=seed.base_load_mw,
        source="default_asset",
        source_id=seed.asset_id,
        metadata={
            "asset_type": "transmission_tower",
            "default_asset": True,
            "voltage_kv": seed.voltage_kv,
        },
    )


def _tower_spec(seed: _TowerSeed) -> TransmissionTowerSpec:
    return TransmissionTowerSpec(
        tower_id=seed.spec_id,
        tower_name=seed.name,
        node_id=seed.node_id,
        voltage_kv=seed.voltage_kv,
        height_m=seed.height_m,
        terrain_slope_deg=seed.terrain_slope_deg,
        install_cost_billion=seed.install_cost_billion,
        land_type=seed.land_type,
        environment_risk=seed.environment_risk,
        policy_risk=seed.policy_risk,
        accessibility_score=seed.accessibility_score,
        nearest_node_id=seed.nearest_node_id,
        source="default_asset",
        metadata={"asset_id": seed.asset_id},
    )


def _user_power_plant_assets(installation: InstallationPoint) -> tuple[GridNode, PowerPlantSpec]:
    node_id = grid_node_id_for_installation(installation)
    capacity_mw = _positive_or_default(installation.capacity_mw, DEFAULT_USER_PLANT_CAPACITY_MW)
    metadata = _installation_metadata(installation)
    return (
        GridNode(
            node_id=node_id,
            node_name=installation.label,
            node_type="user_power_plant",
            latitude=installation.latitude,
            longitude=installation.longitude,
            voltage_kv=installation.voltage_kv or DEFAULT_VOLTAGE_KV,
            region=_region_from_installation(installation),
            base_load_mw=0.0,
            elevation_m=installation.elevation_m,
            coordinate_system=installation.coordinate_system,
            elevation_source=installation.elevation_source,
            source="user_installation",
            source_id=installation.installation_id,
            metadata=metadata,
        ),
        PowerPlantSpec(
            plant_id=f"USER_PLANT_SPEC_{_sanitize_identifier(installation.installation_id)}",
            plant_name=installation.label,
            node_id=node_id,
            capacity_mw=capacity_mw,
            fuel_type="USER_DEFINED",
            min_output_mw=0.0,
            max_output_mw=capacity_mw,
            availability=1.0,
            source="user_installation",
            metadata=metadata,
        ),
    )


def _user_tower_assets(installation: InstallationPoint) -> tuple[GridNode, TransmissionTowerSpec]:
    node_id = grid_node_id_for_installation(installation)
    voltage_kv = installation.voltage_kv or DEFAULT_VOLTAGE_KV
    metadata = _installation_metadata(installation)
    return (
        GridNode(
            node_id=node_id,
            node_name=installation.label,
            node_type="user_transmission_tower",
            latitude=installation.latitude,
            longitude=installation.longitude,
            voltage_kv=voltage_kv,
            region=_region_from_installation(installation),
            base_load_mw=DEFAULT_USER_TOWER_BASE_LOAD_MW,
            elevation_m=installation.elevation_m,
            coordinate_system=installation.coordinate_system,
            elevation_source=installation.elevation_source,
            source="user_installation",
            source_id=installation.installation_id,
            metadata=metadata,
        ),
        TransmissionTowerSpec(
            tower_id=f"USER_TOWER_SPEC_{_sanitize_identifier(installation.installation_id)}",
            tower_name=installation.label,
            node_id=node_id,
            voltage_kv=voltage_kv,
            elevation_m=installation.elevation_m,
            height_m=DEFAULT_USER_TOWER_HEIGHT_M,
            nearest_node_id="",
            source="user_installation",
            metadata=metadata,
        ),
    )


def _allocate_load(nodes: list[GridNode], total_load_mw: float) -> dict[str, float]:
    load_nodes = [
        node
        for node in nodes
        if node.node_type in {"transmission_tower", "user_transmission_tower"}
    ]
    if not load_nodes:
        return {}

    total_weight = sum(max(0.0, node.base_load_mw) for node in load_nodes)
    if total_weight <= 0.0:
        equal_load = total_load_mw / len(load_nodes)
        return {node.node_id: equal_load for node in load_nodes}

    return {
        node.node_id: total_load_mw * (max(0.0, node.base_load_mw) / total_weight)
        for node in load_nodes
    }


def _allocate_generation(
    plants: list[PowerPlantSpec],
    total_load_mw: float,
) -> tuple[dict[str, float], str, list[str]]:
    warnings: list[str] = []
    if not plants:
        return {}, "", ["발전소 spec이 없어 발전량을 배분하지 못했습니다."]

    available_by_node_id = {
        plant.node_id: _available_capacity(plant)
        for plant in plants
    }
    available_total = sum(available_by_node_id.values())
    if available_total <= 0.0:
        return {}, "", ["가용 발전용량이 0MW라 발전량을 배분하지 못했습니다."]

    if total_load_mw > available_total + 1e-6:
        warnings.append(
            f"요구 부하 {total_load_mw:.1f}MW가 mock 가용 발전용량 {available_total:.1f}MW를 초과합니다."
        )

    slack_node_id = max(available_by_node_id, key=available_by_node_id.get)
    generation_by_node_id = {
        node_id: total_load_mw * (available_mw / available_total)
        for node_id, available_mw in available_by_node_id.items()
    }
    return generation_by_node_id, slack_node_id, warnings


def _dedupe_assets(
    nodes: list[GridNode],
    plants: list[PowerPlantSpec],
    towers: list[TransmissionTowerSpec],
) -> tuple[list[GridNode], list[PowerPlantSpec], list[TransmissionTowerSpec], list[str]]:
    warnings: list[str] = []
    deduped_nodes: list[GridNode] = []
    seen_node_ids: set[str] = set()
    for node in nodes:
        if node.node_id in seen_node_ids:
            warnings.append(f"중복 GridNode {node.node_id}를 제외했습니다.")
            continue
        deduped_nodes.append(node)
        seen_node_ids.add(node.node_id)

    deduped_plants: list[PowerPlantSpec] = []
    seen_plant_node_ids: set[str] = set()
    for plant in plants:
        if plant.node_id not in seen_node_ids:
            warnings.append(f"존재하지 않는 GridNode를 참조한 발전소 spec {plant.plant_id}를 제외했습니다.")
            continue
        if plant.node_id in seen_plant_node_ids:
            warnings.append(f"중복 발전소 spec node_id={plant.node_id}를 제외했습니다.")
            continue
        deduped_plants.append(plant)
        seen_plant_node_ids.add(plant.node_id)

    deduped_towers: list[TransmissionTowerSpec] = []
    seen_tower_node_ids: set[str] = set()
    for tower in towers:
        if tower.node_id not in seen_node_ids:
            warnings.append(f"존재하지 않는 GridNode를 참조한 송전탑 spec {tower.tower_id}를 제외했습니다.")
            continue
        if tower.node_id in seen_tower_node_ids:
            warnings.append(f"중복 송전탑 spec node_id={tower.node_id}를 제외했습니다.")
            continue
        deduped_towers.append(tower)
        seen_tower_node_ids.add(tower.node_id)
    return deduped_nodes, deduped_plants, deduped_towers, warnings


def _installation_metadata(installation: InstallationPoint) -> dict[str, object]:
    metadata = dict(installation.metadata)
    metadata.update(
        {
            "installation_id": installation.installation_id,
            "installation_mode": installation.mode,
            "notes": installation.notes,
            "source_kind": installation.kind,
        }
    )
    if installation.capacity_mw is not None:
        metadata["capacity_mw"] = installation.capacity_mw
    if installation.voltage_kv is not None:
        metadata["voltage_kv"] = installation.voltage_kv
    return metadata


def _region_from_installation(installation: InstallationPoint) -> str:
    province = installation.metadata.get("nearest_place_province")
    if isinstance(province, str) and province.strip():
        return province.strip()
    place_name = installation.metadata.get("nearest_place_name")
    if isinstance(place_name, str) and place_name.strip():
        return place_name.strip()
    return ""


def _dataset_sources(user_nodes: list[GridNode]) -> list[str]:
    sources = ["default_asset"]
    if user_nodes:
        sources.append("user_installation")
    return sources


def _available_capacity(plant: PowerPlantSpec) -> float:
    return max(0.0, min(plant.max_output_mw, plant.capacity_mw * plant.availability))


def _sanitize_identifier(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", value.strip()).strip("_")
    return normalized.upper() or "UNKNOWN"


def _positive_or_default(value: float | None, default: float) -> float:
    if value is None:
        return default
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(resolved) or resolved <= 0.0:
        return default
    return resolved


def _validate_positive_number(value: float, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}는 bool이 아닌 양수여야 합니다.")
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}는 양수여야 합니다.") from exc
    if not math.isfinite(resolved) or resolved <= 0.0:
        raise ValueError(f"{field_name}는 0보다 큰 유한한 숫자여야 합니다.")
    return resolved


def _resolve_created_at(created_at: datetime | None) -> datetime:
    if created_at is None:
        created_at = datetime.now()
    if not isinstance(created_at, datetime):
        raise TypeError("created_at는 datetime 인스턴스여야 합니다.")
    return created_at.replace(minute=0, second=0, microsecond=0)
