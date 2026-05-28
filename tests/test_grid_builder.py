from __future__ import annotations

from collections import deque
from datetime import datetime

import pytest

from src.data.grid_builder import (
    DEFAULT_GRID_TOTAL_LOAD_MW,
    build_default_grid_dataset,
    build_grid_power_profiles,
    grid_node_id_for_installation,
)
from src.data.schemas import GridDataset, GridNode, InstallationPoint, PowerPlantSpec


def test_build_default_grid_dataset_contains_default_nodes_specs_and_profiles():
    created_at = datetime(2026, 5, 29, 10, 15)

    dataset = build_default_grid_dataset(created_at=created_at)
    node_ids = {node.node_id for node in dataset.nodes}
    profile_node_ids = {profile.node_id for profile in dataset.power_profiles}

    assert dataset.created_at == datetime(2026, 5, 29, 10, 0)
    assert dataset.source == "default_asset"
    assert len(dataset.nodes) == 18
    assert len(dataset.plants) == 6
    assert len(dataset.tower_candidates) == 12
    assert len(dataset.lines) >= 18
    assert profile_node_ids == node_ids
    assert dataset.metadata["line_generation_status"] == "generated"
    assert dataset.metadata["line_count"] == len(dataset.lines)

    assert "PLANT_INCHEON" in node_ids
    assert "PLANT_ULSAN" in node_ids
    assert "TOWER_GEOCHANG" in node_ids
    assert "TOWER_JEJU" in node_ids
    assert not any(node_id.startswith("BUS_") for node_id in node_ids)
    assert not any(node_id.startswith("B0") for node_id in node_ids)
    assert not any(node_id.startswith("SITE_") for node_id in node_ids)


def test_build_default_grid_dataset_maps_user_installations_to_grid_assets():
    created_at = datetime(2026, 5, 29, 11, 0)
    user_plant = InstallationPoint(
        installation_id="power_plant-20260529110000-1",
        label="구미 발전소",
        kind="power_plant",
        latitude=36.1195,
        longitude=128.3446,
        capacity_mw=650.0,
        metadata={
            "nearest_place_name": "구미",
            "nearest_place_province": "경상북도",
        },
    )
    user_tower = InstallationPoint(
        installation_id="transmission_tower-20260529110000-2",
        label="상주 송전탑",
        kind="transmission_tower",
        latitude=36.4109,
        longitude=128.1591,
        voltage_kv=154.0,
        notes="사용자 테스트 후보",
        metadata={
            "nearest_place_name": "상주",
            "nearest_place_province": "경상북도",
        },
    )

    dataset = build_default_grid_dataset(
        user_installations=[user_plant, user_tower],
        created_at=created_at,
    )
    node_by_id = {node.node_id: node for node in dataset.nodes}
    plant_by_node_id = {plant.node_id: plant for plant in dataset.plants}
    tower_by_node_id = {tower.node_id: tower for tower in dataset.tower_candidates}
    user_plant_node_id = "USER_PLANT_POWER_PLANT_20260529110000_1"
    user_tower_node_id = "USER_TOWER_TRANSMISSION_TOWER_20260529110000_2"

    assert grid_node_id_for_installation(user_plant) == user_plant_node_id
    assert grid_node_id_for_installation(user_tower) == user_tower_node_id
    assert node_by_id[user_plant_node_id].node_type == "user_power_plant"
    assert node_by_id[user_plant_node_id].source_id == user_plant.installation_id
    assert node_by_id[user_plant_node_id].region == "경상북도"
    assert node_by_id[user_tower_node_id].node_type == "user_transmission_tower"
    assert node_by_id[user_tower_node_id].base_load_mw > 0.0
    assert node_by_id[user_tower_node_id].source_id == user_tower.installation_id
    assert plant_by_node_id[user_plant_node_id].capacity_mw == 650.0
    assert tower_by_node_id[user_tower_node_id].voltage_kv == 154.0
    assert tower_by_node_id[user_tower_node_id].metadata["notes"] == "사용자 테스트 후보"
    assert "user_installation" in dataset.metadata["sources"]


def test_grid_lines_reference_nodes_and_connect_default_graph():
    dataset = build_default_grid_dataset(
        created_at=datetime(2026, 5, 29, 11, 30),
    )
    node_ids = {node.node_id for node in dataset.nodes}
    line_ids = {line.line_id for line in dataset.lines}
    neighbors = {node_id: set() for node_id in node_ids}

    assert len(line_ids) == len(dataset.lines)

    for line in dataset.lines:
        assert line.from_node_id in node_ids
        assert line.to_node_id in node_ids
        assert line.from_node_id != line.to_node_id
        assert line.is_bidirectional is True
        assert line.capacity_mw > 0.0
        assert line.reactance_pu > 0.0
        assert line.distance_km > 0.0
        assert 0.0 <= line.terrain_risk <= 1.0
        assert line.source in {"default_asset", "user_installation"}
        assert not line.from_node_id.startswith(("BUS_", "B0", "SITE_"))
        assert not line.to_node_id.startswith(("BUS_", "B0", "SITE_"))
        neighbors[line.from_node_id].add(line.to_node_id)
        neighbors[line.to_node_id].add(line.from_node_id)

    seen = {dataset.nodes[0].node_id}
    queue: deque[str] = deque([dataset.nodes[0].node_id])
    while queue:
        node_id = queue.popleft()
        for next_node_id in neighbors[node_id]:
            if next_node_id not in seen:
                seen.add(next_node_id)
                queue.append(next_node_id)

    assert seen == node_ids
    assert any(
        {"TOWER_JEJU", "TOWER_HAENAM"} == {line.from_node_id, line.to_node_id}
        and line.status == "candidate"
        for line in dataset.lines
    )
    for plant_id in {
        "PLANT_INCHEON",
        "PLANT_GWANGJU",
        "PLANT_SOKCHO",
        "PLANT_BUSAN",
        "PLANT_ULSAN",
        "PLANT_POHANG",
    }:
        assert neighbors[plant_id]


def test_grid_power_profiles_balance_generation_load_and_select_slack():
    dataset = build_default_grid_dataset(
        created_at=datetime(2026, 5, 29, 12, 0),
        load_scale=1.0,
    )
    profile_by_node_id = {
        profile.node_id: profile
        for profile in dataset.power_profiles
    }
    slack_profiles = [
        profile
        for profile in dataset.power_profiles
        if profile.is_slack_candidate
    ]
    total_generation = sum(profile.generation_mw for profile in dataset.power_profiles)
    total_load = sum(profile.load_mw for profile in dataset.power_profiles)
    total_net_injection = sum(profile.net_injection_mw for profile in dataset.power_profiles)

    assert len(slack_profiles) == 1
    assert slack_profiles[0].node_id == "PLANT_ULSAN"
    assert total_generation == pytest.approx(DEFAULT_GRID_TOTAL_LOAD_MW)
    assert total_load == pytest.approx(DEFAULT_GRID_TOTAL_LOAD_MW)
    assert total_net_injection == pytest.approx(0.0)
    assert profile_by_node_id["PLANT_ULSAN"].generation_mw > profile_by_node_id["PLANT_SOKCHO"].generation_mw
    assert profile_by_node_id["TOWER_SEOUL"].load_mw > profile_by_node_id["TOWER_HAENAM"].load_mw
    assert profile_by_node_id["PLANT_INCHEON"].load_mw == 0.0
    assert profile_by_node_id["TOWER_DAEGU"].generation_mw == 0.0


def test_grid_lines_connect_user_nodes_as_candidates():
    user_tower = InstallationPoint(
        installation_id="transmission_tower-20260529123000-1",
        label="상주 사용자 송전탑",
        kind="transmission_tower",
        latitude=36.4109,
        longitude=128.1591,
        voltage_kv=345.0,
    )
    user_plant = InstallationPoint(
        installation_id="power_plant-20260529123000-2",
        label="구미 사용자 발전소",
        kind="power_plant",
        latitude=36.1195,
        longitude=128.3446,
        capacity_mw=500.0,
    )
    dataset = build_default_grid_dataset(
        user_installations=[user_tower, user_plant],
        created_at=datetime(2026, 5, 29, 12, 30),
    )
    user_node_ids = {
        "USER_TOWER_TRANSMISSION_TOWER_20260529123000_1",
        "USER_PLANT_POWER_PLANT_20260529123000_2",
    }

    for user_node_id in user_node_ids:
        user_lines = [
            line
            for line in dataset.lines
            if user_node_id in {line.from_node_id, line.to_node_id}
        ]

        assert user_lines
        assert all(line.status == "candidate" for line in user_lines)
        assert all(line.source == "user_installation" for line in user_lines)


def test_build_grid_power_profiles_works_without_mutating_input_dataset():
    created_at = datetime(2026, 5, 29, 13, 0)
    node = GridNode(
        node_id="PLANT_TEST",
        node_name="테스트 발전소",
        node_type="power_plant",
        latitude=36.0,
        longitude=127.0,
        voltage_kv=345.0,
    )
    tower = GridNode(
        node_id="TOWER_TEST",
        node_name="테스트 송전탑",
        node_type="transmission_tower",
        latitude=36.1,
        longitude=127.1,
        voltage_kv=345.0,
        base_load_mw=100.0,
    )
    plant = PowerPlantSpec(
        plant_id="PLANT_SPEC_TEST",
        plant_name="테스트 발전소",
        node_id=node.node_id,
        capacity_mw=1000.0,
        fuel_type="LNG",
        min_output_mw=0.0,
        max_output_mw=1000.0,
    )
    dataset = GridDataset(nodes=[node, tower], plants=[plant], created_at=created_at)

    profiles, warnings = build_grid_power_profiles(
        dataset,
        total_load_mw=500.0,
        created_at=created_at,
    )

    assert dataset.power_profiles == []
    profile_by_node_id = {
        profile.node_id: profile
        for profile in profiles
    }

    assert len(profiles) == 2
    assert profile_by_node_id["PLANT_TEST"].is_slack_candidate is True
    assert profile_by_node_id["PLANT_TEST"].generation_mw == pytest.approx(500.0)
    assert profile_by_node_id["PLANT_TEST"].load_mw == 0.0
    assert profile_by_node_id["TOWER_TEST"].load_mw == pytest.approx(500.0)
    assert warnings == []


def test_build_default_grid_dataset_warns_for_non_grid_installation_kind():
    start_point = InstallationPoint(
        installation_id="start-20260529130000-1",
        label="시작점",
        kind="start_point",
        latitude=36.0,
        longitude=127.0,
    )

    dataset = build_default_grid_dataset(
        user_installations=[start_point],
        created_at=datetime(2026, 5, 29, 13, 0),
    )

    assert any("GridNode 변환 대상이 아닌 kind=start_point" in warning for warning in dataset.warnings)
    assert not any(node.node_id.startswith("USER_POINT_") for node in dataset.nodes)


def test_build_default_grid_dataset_deduplicates_user_installation_ids():
    user_plant = InstallationPoint(
        installation_id="power_plant-20260529140000-1",
        label="중복 발전소",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        capacity_mw=500.0,
    )

    dataset = build_default_grid_dataset(
        user_installations=[user_plant, user_plant],
        created_at=datetime(2026, 5, 29, 14, 0),
    )
    user_node_id = "USER_PLANT_POWER_PLANT_20260529140000_1"

    assert sum(1 for node in dataset.nodes if node.node_id == user_node_id) == 1
    assert sum(1 for plant in dataset.plants if plant.node_id == user_node_id) == 1
    assert any(f"중복 GridNode {user_node_id}" in warning for warning in dataset.warnings)
    assert any(f"중복 발전소 spec node_id={user_node_id}" in warning for warning in dataset.warnings)
