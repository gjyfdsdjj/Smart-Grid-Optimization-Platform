from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import get_args

from src.data.schemas import (
    GridDataset,
    GridDataSource,
    GridLine,
    GridLineStatus,
    GridNode,
    GridNodeType,
    GridPowerProfile,
    PowerPlantSpec,
    TransmissionTowerSpec,
)


def test_grid_contract_supports_default_and_user_grid_nodes():
    plant = GridNode(
        node_id="PLANT_INCHEON",
        node_name="인천 발전소",
        node_type="power_plant",
        latitude=37.4563,
        longitude=126.7052,
        voltage_kv=345.0,
        region="수도권",
        source="default_asset",
    )
    user_tower = GridNode(
        node_id="USER_TOWER_transmission_tower-20260529120000-1",
        node_name="구미 송전탑",
        node_type="user_transmission_tower",
        latitude=36.1195,
        longitude=128.3446,
        voltage_kv=345.0,
        region="경상북도",
        source="user_installation",
        source_id="transmission_tower-20260529120000-1",
    )

    assert plant.coordinate_system == "EPSG:4326"
    assert plant.elevation_source == "not_queried"
    assert plant.node_type == "power_plant"
    assert user_tower.source == "user_installation"
    assert user_tower.source_id == "transmission_tower-20260529120000-1"


def test_grid_dataset_groups_nodes_lines_specs_and_power_profiles():
    created_at = datetime(2026, 5, 29, 9, 0)
    plant = GridNode(
        node_id="PLANT_ULSAN",
        node_name="울산 발전소",
        node_type="power_plant",
        latitude=35.5384,
        longitude=129.3114,
        voltage_kv=345.0,
        source="default_asset",
    )
    tower = GridNode(
        node_id="TOWER_DAEGU",
        node_name="대구 송전탑",
        node_type="transmission_tower",
        latitude=35.8714,
        longitude=128.6014,
        voltage_kv=345.0,
        source="default_asset",
    )
    line = GridLine(
        line_id="GLINE_ULSAN_DAEGU",
        from_node_id=plant.node_id,
        to_node_id=tower.node_id,
        voltage_kv=345.0,
        capacity_mw=3000.0,
        reactance_pu=0.08,
        distance_km=85.0,
    )
    plant_spec = PowerPlantSpec(
        plant_id="P_ULSAN",
        plant_name="울산 발전소",
        node_id=plant.node_id,
        capacity_mw=2400.0,
        fuel_type="LNG",
        min_output_mw=500.0,
        max_output_mw=2400.0,
    )
    tower_spec = TransmissionTowerSpec(
        tower_id="T_DAEGU",
        tower_name="대구 송전탑",
        node_id=tower.node_id,
        voltage_kv=345.0,
        height_m=65.0,
    )
    profile = GridPowerProfile(
        node_id=plant.node_id,
        timestamp=created_at,
        generation_mw=1800.0,
        load_mw=200.0,
        net_injection_mw=1600.0,
        is_slack_candidate=True,
    )

    dataset = GridDataset(
        nodes=[plant, tower],
        lines=[line],
        plants=[plant_spec],
        tower_candidates=[tower_spec],
        power_profiles=[profile],
        created_at=created_at,
        source="default_asset",
    )

    assert dataset.nodes[0].node_id == "PLANT_ULSAN"
    assert dataset.lines[0].is_bidirectional is True
    assert dataset.lines[0].status == "active"
    assert dataset.plants[0].node_id == "PLANT_ULSAN"
    assert dataset.tower_candidates[0].node_id == "TOWER_DAEGU"
    assert dataset.power_profiles[0].net_injection_mw == 1600.0
    assert dataset.fallback.enabled is False


def test_grid_contract_literal_values_are_fixed_for_csv_schema_step():
    assert set(get_args(GridNodeType)) == {
        "power_plant",
        "transmission_tower",
        "user_power_plant",
        "user_transmission_tower",
    }
    assert set(get_args(GridDataSource)) == {
        "default_asset",
        "user_installation",
        "csv",
        "fallback_mock",
        "legacy",
    }
    assert set(get_args(GridLineStatus)) == {
        "active",
        "planned",
        "candidate",
        "out_of_service",
    }


def test_grid_migration_baseline_documents_legacy_removal_and_new_sources():
    document = Path("docs/GRID_MIGRATION_BASELINE_2026-05-29.md").read_text(
        encoding="utf-8"
    )

    for status_text in [
        "실행 코드 기준으로 제거",
        "KPX는 전국 시계열로 읽고 GridNode 가중치로 재분배",
        "DC Power Flow 입력은 GridDataset 변환기에서 생성",
        "후보지는 `tower_candidates.csv`와 사용자 송전탑에서 생성",
        "GNN edge는 고정 목록이 아니라 GridLine에서 생성",
    ]:
        assert status_text in document

    for new_node_id in [
        "PLANT_INCHEON",
        "PLANT_ULSAN",
        "TOWER_GUMI",
        "TOWER_SANGJU",
        "USER_PLANT_<installation_id>",
        "USER_TOWER_<installation_id>",
    ]:
        assert new_node_id in document
