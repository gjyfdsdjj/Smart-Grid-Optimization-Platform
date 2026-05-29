from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.data.loaders import (
    load_grid_dataset_from_csv,
    load_grid_dataset_or_default,
    load_model_evaluation_summary,
    load_processed_grid_line_flow_history,
    load_processed_grid_node_history,
    summarize_processed_grid_line_flow_history,
)
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


def test_processed_grid_node_history_loader_validates_prediction_input(tmp_path):
    path = tmp_path / "grid_node_load_history.csv"
    rows = []
    for hour in range(24):
        rows.append(
            {
                "timestamp": f"2026-05-14 {hour:02d}:00:00",
                "node_id": "TOWER_A",
                "node_name": "A 송전탑",
                "node_type": "transmission_tower",
                "region": "테스트권",
                "load_mw": 100.0 + hour,
                "generation_mw": 0.0,
                "net_injection_mw": -(100.0 + hour),
                "load_weight": 1.0,
                "generation_weight": 0.0,
                "national_demand_mw": 1000.0,
                "national_supply_mw": 1200.0,
                "grid_total_load_mw": 100.0 + hour,
                "grid_total_generation_mw": 120.0,
                "scale_to_grid": 0.1,
                "source": "unit-test",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)

    result = load_processed_grid_node_history(path)

    assert len(result) == 24
    assert result["timestamp"].nunique() == 24
    assert result.attrs["source_path"].endswith("grid_node_load_history.csv")


def test_processed_grid_line_flow_history_loader_and_summary(tmp_path):
    path = tmp_path / "grid_line_flow_history.csv"
    pd.DataFrame(
        [
            {
                "timestamp": "2026-05-14 00:00:00",
                "line_id": "GLINE_A_B",
                "from_node_id": "TOWER_A",
                "to_node_id": "TOWER_B",
                "from_node_name": "A 송전탑",
                "to_node_name": "B 송전탑",
                "flow_mw": 50.0,
                "abs_flow_mw": 50.0,
                "capacity_mw": 100.0,
                "utilization": 0.5,
                "status": "normal",
                "risk_level": "low",
                "loss_mw": 0.1,
                "from_angle_deg": 1.0,
                "to_angle_deg": 0.0,
                "angle_delta_deg": 1.0,
                "slack_bus_id": "PLANT_A",
                "reactance_pu": 0.1,
                "line_status_source": "dc_power_flow_balanced_dispatch",
                "source": "unit-line-history",
            }
        ]
    ).to_csv(path, index=False)

    result = load_processed_grid_line_flow_history(path)
    summary = summarize_processed_grid_line_flow_history(path)

    assert len(result) == 1
    assert result.attrs["source_path"].endswith("grid_line_flow_history.csv")
    assert summary["processed_line_history_used"] is True
    assert summary["line_flow_history_rows"] == 1
    assert summary["line_flow_history_max_utilization"] == 0.5


def test_model_evaluation_summary_loader_validates_core_metrics(tmp_path):
    path = tmp_path / "model_evaluation_summary.csv"
    pd.DataFrame(
        [
            {
                "model": "baseline",
                "mae_mw": 22.0,
                "rmse_mw": 31.0,
                "mape_pct": 8.5,
                "line_utilization_mae_pp": 3.4,
                "sample_count": 48,
            },
            {
                "model": "neural_gnn",
                "mae_mw": 16.0,
                "rmse_mw": 25.0,
                "mape_pct": 6.0,
                "line_utilization_mae_pp": 2.1,
                "sample_count": 48,
            },
        ]
    ).to_csv(path, index=False)

    result = load_model_evaluation_summary(path)

    assert result.attrs["source_path"].endswith("model_evaluation_summary.csv")
    assert result["model"].tolist() == ["baseline", "neural_gnn"]
    assert result["mape_pct"].tolist() == [8.5, 6.0]
