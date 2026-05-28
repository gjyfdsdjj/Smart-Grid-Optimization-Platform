# GridDataset을 DC Power Flow 엔진 입력으로 변환한다.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.data.schemas import GridDataset, GridLine, GridPowerProfile
from src.engine.powerflow.dc_power_flow import BusInput, LineInput


GridLinePolicy = Literal["non_outage", "active_only"]


@dataclass(frozen=True)
class GridPowerFlowInputs:
    """DC Power Flow 계산에 필요한 Grid 기반 입력 묶음."""

    buses: list[BusInput]
    lines: list[LineInput]
    bus_names: dict[str, str]
    slack_bus_id: str
    included_line_ids: list[str] = field(default_factory=list)
    excluded_line_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_powerflow_inputs_from_grid(
    dataset: GridDataset,
    *,
    line_policy: GridLinePolicy = "non_outage",
) -> GridPowerFlowInputs:
    """GridDataset을 dc_power_flow.solve() 입력으로 변환한다."""

    if not isinstance(dataset, GridDataset):
        raise TypeError("dataset은 GridDataset이어야 합니다.")
    if not dataset.nodes:
        raise ValueError("DC Power Flow 입력으로 변환할 GridNode가 없습니다.")
    if not dataset.lines:
        raise ValueError("DC Power Flow 입력으로 변환할 GridLine이 없습니다.")

    warnings: list[str] = []
    node_by_id = {node.node_id: node for node in dataset.nodes}
    profile_by_node_id = _latest_profile_by_node_id(dataset.power_profiles)
    slack_bus_id, slack_warnings = _select_slack_bus_id(dataset, profile_by_node_id)
    warnings.extend(slack_warnings)

    buses = [
        BusInput(
            bus_id=node.node_id,
            p_gen_mw=profile_by_node_id.get(node.node_id, GridPowerProfile(node.node_id)).generation_mw,
            p_load_mw=profile_by_node_id.get(node.node_id, GridPowerProfile(node.node_id)).load_mw,
            is_slack=(node.node_id == slack_bus_id),
        )
        for node in dataset.nodes
    ]
    bus_names = {
        node.node_id: node.node_name
        for node in dataset.nodes
    }

    lines: list[LineInput] = []
    included_line_ids: list[str] = []
    excluded_line_ids: list[str] = []
    for grid_line in dataset.lines:
        converted_line, exclude_reason = _convert_grid_line(
            grid_line,
            node_by_id=node_by_id,
            line_policy=line_policy,
        )
        if converted_line is None:
            excluded_line_ids.append(grid_line.line_id)
            if exclude_reason:
                warnings.append(exclude_reason)
            continue
        lines.append(converted_line)
        included_line_ids.append(grid_line.line_id)

    if not lines:
        raise ValueError("DC Power Flow에 사용할 유효 GridLine이 없습니다.")

    return GridPowerFlowInputs(
        buses=buses,
        lines=lines,
        bus_names=bus_names,
        slack_bus_id=slack_bus_id,
        included_line_ids=included_line_ids,
        excluded_line_ids=excluded_line_ids,
        warnings=warnings,
    )


def _latest_profile_by_node_id(
    profiles: list[GridPowerProfile],
) -> dict[str, GridPowerProfile]:
    profile_by_node_id: dict[str, GridPowerProfile] = {}
    for profile in profiles:
        existing = profile_by_node_id.get(profile.node_id)
        if existing is None:
            profile_by_node_id[profile.node_id] = profile
            continue
        if profile.timestamp is not None and (
            existing.timestamp is None or profile.timestamp >= existing.timestamp
        ):
            profile_by_node_id[profile.node_id] = profile
    return profile_by_node_id


def _select_slack_bus_id(
    dataset: GridDataset,
    profile_by_node_id: dict[str, GridPowerProfile],
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    node_ids = {node.node_id for node in dataset.nodes}
    slack_profiles = [
        profile
        for profile in profile_by_node_id.values()
        if profile.is_slack_candidate and profile.node_id in node_ids
    ]

    if len(slack_profiles) == 1:
        return slack_profiles[0].node_id, warnings

    if len(slack_profiles) > 1:
        selected = max(
            slack_profiles,
            key=lambda profile: (profile.generation_mw, profile.node_id),
        )
        warnings.append(
            "GridPowerProfile 슬랙 후보가 여러 개라 "
            f"{selected.node_id}만 DC Power Flow 슬랙으로 사용합니다."
        )
        return selected.node_id, warnings

    generating_profiles = [
        profile
        for profile in profile_by_node_id.values()
        if profile.node_id in node_ids and profile.generation_mw > 0.0
    ]
    if generating_profiles:
        selected = max(
            generating_profiles,
            key=lambda profile: (profile.generation_mw, profile.node_id),
        )
        warnings.append(
            "GridPowerProfile에 슬랙 후보가 없어 "
            f"발전량이 가장 큰 {selected.node_id}를 슬랙으로 사용합니다."
        )
        return selected.node_id, warnings

    selected_node = dataset.nodes[0]
    warnings.append(
        "GridPowerProfile에 발전 노드가 없어 첫 번째 GridNode "
        f"{selected_node.node_id}를 슬랙으로 사용합니다."
    )
    return selected_node.node_id, warnings


def _convert_grid_line(
    line: GridLine,
    *,
    node_by_id: dict[str, object],
    line_policy: GridLinePolicy,
) -> tuple[LineInput | None, str]:
    if line.status == "out_of_service":
        return None, f"{line.line_id}는 out_of_service 상태라 DC Power Flow 입력에서 제외했습니다."
    if line_policy == "active_only" and line.status != "active":
        return None, f"{line.line_id}는 active 상태가 아니라 DC Power Flow 입력에서 제외했습니다."
    if line.from_node_id not in node_by_id or line.to_node_id not in node_by_id:
        return None, f"{line.line_id}는 존재하지 않는 GridNode를 참조해 DC Power Flow 입력에서 제외했습니다."
    if line.reactance_pu <= 0.0:
        return None, f"{line.line_id}는 reactance_pu가 0 이하라 DC Power Flow 입력에서 제외했습니다."
    if line.capacity_mw <= 0.0:
        return None, f"{line.line_id}는 capacity_mw가 0 이하라 DC Power Flow 입력에서 제외했습니다."

    return (
        LineInput(
            line_id=line.line_id,
            from_bus=line.from_node_id,
            to_bus=line.to_node_id,
            reactance_pu=line.reactance_pu,
            capacity_mw=line.capacity_mw,
        ),
        "",
    )
