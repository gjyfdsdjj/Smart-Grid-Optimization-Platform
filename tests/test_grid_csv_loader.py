from __future__ import annotations

from datetime import datetime

import pytest

from src.data.loaders import load_grid_dataset_from_csv, load_grid_dataset_or_default
from src.data.schemas import InstallationPoint


def test_grid_csv_loader_builds_grid_dataset_and_profiles():
    dataset = load_grid_dataset_from_csv(
        "data/grid/mock",
        created_at=datetime(2026, 5, 29, 9, 0),
    )

    assert dataset.source == "csv"
    assert dataset.fallback.enabled is False
    assert len(dataset.nodes) == 18
    assert len(dataset.lines) == 19
    assert len(dataset.plants) == 6
    assert len(dataset.tower_candidates) == 12
    assert len(dataset.power_profiles) == len(dataset.nodes)
    assert dataset.metadata["line_generation_status"] == "csv"
    assert not any(node.node_id.startswith(("BUS_", "B0", "SITE_")) for node in dataset.nodes)
    assert not any(line.line_id.startswith(("BUS_", "B0", "SITE_")) for line in dataset.lines)
    assert all(line.from_node_id in {node.node_id for node in dataset.nodes} for line in dataset.lines)
    assert all(line.to_node_id in {node.node_id for node in dataset.nodes} for line in dataset.lines)


def test_default_grid_csv_loader_uses_enhanced_dataset():
    dataset = load_grid_dataset_or_default(
        created_at=datetime(2026, 5, 29, 9, 0),
    )

    assert dataset.source == "csv"
    assert dataset.fallback.enabled is False
    assert dataset.metadata["grid_stage"] == "12"
    assert len(dataset.nodes) == 36
    assert len(dataset.lines) == 44
    assert len(dataset.plants) == 12
    assert len(dataset.tower_candidates) == 24
    assert "PLANT_DANGJIN" in {node.node_id for node in dataset.nodes}
    assert "TOWER_SUWON" in {tower.node_id for tower in dataset.tower_candidates}


def test_grid_csv_loader_adds_user_installations_and_regenerates_lines():
    installation = InstallationPoint(
        installation_id="tower-manual-001",
        label="수동 송전탑",
        kind="transmission_tower",
        latitude=36.42,
        longitude=127.72,
        voltage_kv=345.0,
        created_at=datetime(2026, 5, 29, 9, 0),
    )

    dataset = load_grid_dataset_from_csv(
        "data/grid/mock",
        user_installations=[installation],
        created_at=installation.created_at,
    )

    node_ids = {node.node_id for node in dataset.nodes}
    assert "USER_TOWER_TOWER_MANUAL_001" in node_ids
    assert dataset.source == "csv"
    assert dataset.metadata["line_generation_status"] == "generated_for_user_installations"
    assert any(
        line.from_node_id == "USER_TOWER_TOWER_MANUAL_001"
        or line.to_node_id == "USER_TOWER_TOWER_MANUAL_001"
        for line in dataset.lines
    )


def test_grid_csv_loader_falls_back_to_default_grid_when_missing(tmp_path):
    dataset = load_grid_dataset_or_default(
        tmp_path / "missing-grid",
        created_at=datetime(2026, 5, 29, 9, 0),
    )

    assert dataset.source == "fallback_mock"
    assert dataset.fallback.enabled is True
    assert dataset.fallback.mode == "mock_data"
    assert len(dataset.nodes) == 18
    assert len(dataset.lines) == 26
    assert dataset.warnings[0] == "Grid CSV 로더는 현재 `mock_data` fallback 결과를 반환합니다."


def test_grid_csv_loader_rejects_invalid_line_reference(tmp_path):
    source_dir = tmp_path / "grid"
    source_dir.mkdir()
    for name in ("nodes.csv", "plants.csv", "tower_candidates.csv"):
        (source_dir / name).write_text(
            (open(f"data/grid/mock/{name}", encoding="utf-8").read()),
            encoding="utf-8",
        )
    line_rows = open("data/grid/mock/lines.csv", encoding="utf-8").read().splitlines()
    broken_row = line_rows[1].split(",")
    broken_row[2] = "MISSING_NODE"
    line_rows[1] = ",".join(broken_row)
    (source_dir / "lines.csv").write_text("\n".join(line_rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="존재하지 않는 GridNode"):
        load_grid_dataset_from_csv(source_dir)
