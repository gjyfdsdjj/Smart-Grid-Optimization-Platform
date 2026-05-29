from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.preprocess import (
    GRID_LINE_FLOW_HISTORY_COLUMNS,
    GRID_NODE_LOAD_HISTORY_COLUMNS,
    GRID_NODE_WEIGHT_COLUMNS,
    NATIONAL_LOAD_HOURLY_COLUMNS,
    build_grid_line_flow_history,
    build_grid_node_load_history,
    build_grid_node_weights,
    build_national_load_hourly,
    normalize_grid_line_flow_history,
    normalize_grid_node_load_history,
    normalize_national_load_hourly,
)
from src.data.schemas import GridDataset, GridLine, GridNode, InstallationPoint


def _write_sukub_csv(path: Path) -> None:
    rows = [
        ["202605140000", 100000.0, 60000.0, 0, 0, 0, 0, 0],
        ["202605140030", 100200.0, 60200.0, 0, 0, 0, 0, 0],
        ["202605140100", 101000.0, 61000.0, 0, 0, 0, 0, 0],
        ["202605140130", 101200.0, 61200.0, 0, 0, 0, 0, 0],
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "기준일시",
            "공급능력(MW)",
            "현재수요(MW)",
            "최대예측수요(MW)",
            "공급예비력(MW)",
            "공급예비율(%)",
            "운영예비력(MW)",
            "운영예비율(%)",
        ],
    )
    df.to_csv(path, index=False, encoding="euc-kr")


def test_build_national_load_hourly_creates_fixed_processed_csv(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_sukub_csv(raw_dir / "sukub.csv")
    output_path = tmp_path / "processed" / "national_load_hourly.csv"

    result = build_national_load_hourly(
        raw_dir=raw_dir,
        output_path=output_path,
        source_file="test_sukub_csv",
    )

    assert output_path.exists()
    saved = pd.read_csv(output_path)
    assert list(result.columns) == list(NATIONAL_LOAD_HOURLY_COLUMNS)
    assert list(saved.columns) == list(NATIONAL_LOAD_HOURLY_COLUMNS)
    assert len(saved) == 2
    assert saved["timestamp"].tolist() == [
        "2026-05-14 00:00:00",
        "2026-05-14 01:00:00",
    ]
    assert saved["demand_mw"].tolist() == [60100.0, 61100.0]
    assert saved["supply_mw"].tolist() == [100100.0, 101100.0]
    assert saved["source_file"].unique().tolist() == ["test_sukub_csv"]


def test_normalize_national_load_hourly_sorts_and_deduplicates() -> None:
    source = pd.DataFrame(
        [
            {"timestamp": "2026-05-14 01:00:00", "demand_mw": 61000, "supply_mw": 101000},
            {"timestamp": "2026-05-14 00:00:00", "demand_mw": 60000, "supply_mw": 100000},
            {"timestamp": "2026-05-14 00:00:00", "demand_mw": 60200, "supply_mw": 100200},
        ]
    )

    result = normalize_national_load_hourly(source, source_file="unit-test")

    assert result["timestamp"].is_monotonic_increasing
    assert not result["timestamp"].duplicated().any()
    assert result["demand_mw"].tolist() == [60100.0, 61000.0]
    assert result["supply_mw"].tolist() == [100100.0, 101000.0]
    assert result["source_file"].tolist() == ["unit-test", "unit-test"]


def test_build_national_load_hourly_raises_when_raw_dir_has_no_sukub_csv(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_national_load_hourly(
            raw_dir=tmp_path,
            output_path=tmp_path / "national_load_hourly.csv",
        )


def test_normalize_national_load_hourly_rejects_invalid_values() -> None:
    source = pd.DataFrame(
        [
            {"timestamp": "2026-05-14 00:00:00", "demand_mw": 0, "supply_mw": 100000},
        ]
    )

    with pytest.raises(ValueError, match="demand_mw"):
        normalize_national_load_hourly(source)


def test_build_grid_node_weights_creates_fixed_enhanced_grid_weights(tmp_path: Path) -> None:
    output_path = tmp_path / "grid_node_weights.csv"

    result = build_grid_node_weights(
        grid_dir="data/grid/enhanced",
        output_path=output_path,
    )

    assert output_path.exists()
    assert list(result.columns) == list(GRID_NODE_WEIGHT_COLUMNS)
    assert len(result) == 36
    assert result["node_id"].is_unique
    assert result["is_load_node"].sum() == 24
    assert result["is_generation_node"].sum() == 12
    assert result["load_weight"].sum() == pytest.approx(1.0)
    assert result["generation_weight"].sum() == pytest.approx(1.0)
    assert (result[result["node_type"] == "power_plant"]["load_weight"] == 0.0).all()
    assert (
        result[result["node_type"] == "transmission_tower"]["generation_weight"] == 0.0
    ).all()


def test_build_grid_node_weights_handles_user_and_xai_nodes_as_dynamic_assets(
    tmp_path: Path,
) -> None:
    user_tower = InstallationPoint(
        installation_id="xai-tower-001",
        label="xAI 우회 송전탑 후보",
        kind="transmission_tower",
        latitude=36.5,
        longitude=127.4,
        capacity_mw=900.0,
        voltage_kv=345.0,
    )
    user_plant = InstallationPoint(
        installation_id="user-plant-001",
        label="사용자 발전소",
        kind="power_plant",
        latitude=36.6,
        longitude=127.5,
        capacity_mw=500.0,
        voltage_kv=345.0,
    )

    result = build_grid_node_weights(
        grid_dir="data/grid/enhanced",
        output_path=tmp_path / "dynamic_grid_node_weights.csv",
        user_installations=[user_tower, user_plant],
    )

    assert len(result) == 38
    assert result["load_weight"].sum() == pytest.approx(1.0)
    assert result["generation_weight"].sum() == pytest.approx(1.0)

    tower_row = result[result["source_id"] == "xai-tower-001"].iloc[0]
    assert tower_row["node_type"] == "user_transmission_tower"
    assert tower_row["load_weight"] == 0.0
    assert tower_row["generation_weight"] == 0.0
    assert "경로 보강" in tower_row["calibration_reason"]

    plant_row = result[result["source_id"] == "user-plant-001"].iloc[0]
    assert plant_row["node_type"] == "user_power_plant"
    assert plant_row["load_weight"] == 0.0
    assert plant_row["generation_weight"] > 0.0
    assert plant_row["generation_capacity_mw"] == 500.0


def _sample_node_weights() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "node_id": "PLANT_A",
                "node_name": "A 발전소",
                "node_type": "power_plant",
                "region": "테스트권",
                "source": "csv",
                "source_id": "plant-a",
                "base_load_mw": 0.0,
                "load_weight": 0.0,
                "generation_capacity_mw": 100.0,
                "generation_weight": 1.0,
                "is_load_node": False,
                "is_generation_node": True,
                "calibration_reason": "test generation",
            },
            {
                "node_id": "TOWER_A",
                "node_name": "A 송전탑",
                "node_type": "transmission_tower",
                "region": "테스트권",
                "source": "csv",
                "source_id": "tower-a",
                "base_load_mw": 70.0,
                "load_weight": 0.7,
                "generation_capacity_mw": 0.0,
                "generation_weight": 0.0,
                "is_load_node": True,
                "is_generation_node": False,
                "calibration_reason": "test load",
            },
            {
                "node_id": "TOWER_B",
                "node_name": "B 송전탑",
                "node_type": "transmission_tower",
                "region": "테스트권",
                "source": "csv",
                "source_id": "tower-b",
                "base_load_mw": 30.0,
                "load_weight": 0.3,
                "generation_capacity_mw": 0.0,
                "generation_weight": 0.0,
                "is_load_node": True,
                "is_generation_node": False,
                "calibration_reason": "test load",
            },
        ],
        columns=list(GRID_NODE_WEIGHT_COLUMNS),
    )


def test_normalize_grid_node_load_history_distributes_load_and_generation() -> None:
    national = pd.DataFrame(
        [
            {
                "timestamp": "2026-05-14 00:00:00",
                "demand_mw": 1000.0,
                "supply_mw": 1200.0,
                "source_file": "unit-test",
            },
            {
                "timestamp": "2026-05-14 01:00:00",
                "demand_mw": 1000.0,
                "supply_mw": 1300.0,
                "source_file": "unit-test",
            },
        ]
    )

    result = normalize_grid_node_load_history(
        national_load_df=national,
        node_weights_df=_sample_node_weights(),
        default_grid_total_load_mw=100.0,
        source="unit-history",
    )

    assert list(result.columns) == list(GRID_NODE_LOAD_HISTORY_COLUMNS)
    assert len(result) == 6
    assert result["node_id"].nunique() == 3
    assert result["timestamp"].nunique() == 2
    assert result["source"].unique().tolist() == ["unit-history"]

    grouped = result.groupby("timestamp").agg(
        load_sum=("load_mw", "sum"),
        generation_sum=("generation_mw", "sum"),
        net_sum=("net_injection_mw", "sum"),
        grid_total_load_mw=("grid_total_load_mw", "first"),
        grid_total_generation_mw=("grid_total_generation_mw", "first"),
    )
    assert grouped["load_sum"].tolist() == pytest.approx(
        grouped["grid_total_load_mw"].tolist()
    )
    assert grouped["generation_sum"].tolist() == pytest.approx(
        grouped["grid_total_generation_mw"].tolist()
    )
    assert grouped["net_sum"].tolist() == pytest.approx(
        (grouped["grid_total_generation_mw"] - grouped["grid_total_load_mw"]).tolist()
    )

    plant_rows = result[result["node_type"] == "power_plant"]
    tower_rows = result[result["node_type"] == "transmission_tower"]
    assert (plant_rows["load_mw"] == 0.0).all()
    assert (tower_rows["generation_mw"] == 0.0).all()
    assert result.loc[result["node_id"] == "TOWER_A", "load_mw"].tolist() == [70.0, 70.0]
    assert result.loc[result["node_id"] == "TOWER_B", "load_mw"].tolist() == [30.0, 30.0]


def test_build_grid_node_load_history_creates_fixed_processed_csv(tmp_path: Path) -> None:
    national_path = tmp_path / "national_load_hourly.csv"
    weights_path = tmp_path / "grid_node_weights.csv"
    output_path = tmp_path / "grid_node_load_history.csv"
    pd.DataFrame(
        [
            {
                "timestamp": "2026-05-14 00:00:00",
                "demand_mw": 1000.0,
                "supply_mw": 1200.0,
                "source_file": "unit-test",
            },
        ]
    ).to_csv(national_path, index=False)
    _sample_node_weights().to_csv(weights_path, index=False)

    result = build_grid_node_load_history(
        national_load_path=national_path,
        node_weights_path=weights_path,
        output_path=output_path,
        default_grid_total_load_mw=100.0,
        source="unit-history",
    )

    assert output_path.exists()
    saved = pd.read_csv(output_path)
    assert list(result.columns) == list(GRID_NODE_LOAD_HISTORY_COLUMNS)
    assert list(saved.columns) == list(GRID_NODE_LOAD_HISTORY_COLUMNS)
    assert len(saved) == 3
    assert saved["load_mw"].sum() == pytest.approx(100.0)
    assert saved["generation_mw"].sum() == pytest.approx(120.0)


def _sample_grid_dataset() -> GridDataset:
    return GridDataset(
        nodes=[
            GridNode(
                node_id="PLANT_A",
                node_name="A 발전소",
                node_type="power_plant",
                latitude=36.0,
                longitude=127.0,
                voltage_kv=345.0,
                region="테스트권",
            ),
            GridNode(
                node_id="TOWER_A",
                node_name="A 송전탑",
                node_type="transmission_tower",
                latitude=36.1,
                longitude=127.1,
                voltage_kv=345.0,
                region="테스트권",
            ),
            GridNode(
                node_id="TOWER_B",
                node_name="B 송전탑",
                node_type="transmission_tower",
                latitude=36.2,
                longitude=127.2,
                voltage_kv=345.0,
                region="테스트권",
            ),
        ],
        lines=[
            GridLine(
                line_id="GLINE_TEST_PLANT_A_TOWER_A",
                from_node_id="PLANT_A",
                to_node_id="TOWER_A",
                voltage_kv=345.0,
                capacity_mw=200.0,
                reactance_pu=0.1,
                distance_km=10.0,
            ),
            GridLine(
                line_id="GLINE_TEST_TOWER_A_TOWER_B",
                from_node_id="TOWER_A",
                to_node_id="TOWER_B",
                voltage_kv=345.0,
                capacity_mw=100.0,
                reactance_pu=0.1,
                distance_km=8.0,
            ),
        ],
    )


def _sample_node_load_history() -> pd.DataFrame:
    national = pd.DataFrame(
        [
            {
                "timestamp": "2026-05-14 00:00:00",
                "demand_mw": 1000.0,
                "supply_mw": 1200.0,
                "source_file": "unit-test",
            },
            {
                "timestamp": "2026-05-14 01:00:00",
                "demand_mw": 1000.0,
                "supply_mw": 1300.0,
                "source_file": "unit-test",
            },
        ]
    )
    return normalize_grid_node_load_history(
        national_load_df=national,
        node_weights_df=_sample_node_weights(),
        default_grid_total_load_mw=100.0,
        source="unit-node-history",
    )


def test_normalize_grid_line_flow_history_runs_dc_power_flow_per_timestamp() -> None:
    result = normalize_grid_line_flow_history(
        node_load_history_df=_sample_node_load_history(),
        grid_dataset=_sample_grid_dataset(),
        source="unit-line-history",
    )

    assert list(result.columns) == list(GRID_LINE_FLOW_HISTORY_COLUMNS)
    assert len(result) == 4
    assert result["timestamp"].nunique() == 2
    assert result["line_id"].nunique() == 2
    assert result["source"].unique().tolist() == ["unit-line-history"]
    assert result["line_status_source"].unique().tolist() == [
        "dc_power_flow_balanced_dispatch"
    ]
    assert result["slack_bus_id"].unique().tolist() == ["PLANT_A"]

    first_timestamp = result[result["timestamp"] == result["timestamp"].min()]
    plant_line = first_timestamp[
        first_timestamp["line_id"] == "GLINE_TEST_PLANT_A_TOWER_A"
    ].iloc[0]
    tower_line = first_timestamp[
        first_timestamp["line_id"] == "GLINE_TEST_TOWER_A_TOWER_B"
    ].iloc[0]
    assert plant_line["abs_flow_mw"] == pytest.approx(100.0)
    assert plant_line["utilization"] == pytest.approx(0.5)
    assert tower_line["abs_flow_mw"] == pytest.approx(30.0)
    assert tower_line["utilization"] == pytest.approx(0.3)


def test_build_grid_line_flow_history_creates_fixed_processed_csv(tmp_path: Path) -> None:
    node_history_path = tmp_path / "grid_node_load_history.csv"
    output_path = tmp_path / "grid_line_flow_history.csv"
    node_history = _sample_node_load_history()
    node_history[node_history["timestamp"] == node_history["timestamp"].min()].to_csv(
        node_history_path,
        index=False,
    )

    result = build_grid_line_flow_history(
        grid_node_load_history_path=node_history_path,
        output_path=output_path,
        grid_dataset=_sample_grid_dataset(),
        source="unit-line-history",
    )

    assert output_path.exists()
    saved = pd.read_csv(output_path)
    assert list(result.columns) == list(GRID_LINE_FLOW_HISTORY_COLUMNS)
    assert list(saved.columns) == list(GRID_LINE_FLOW_HISTORY_COLUMNS)
    assert len(saved) == 2
    assert saved["line_id"].tolist() == [
        "GLINE_TEST_PLANT_A_TOWER_A",
        "GLINE_TEST_TOWER_A_TOWER_B",
    ]


def test_normalize_grid_line_flow_history_rejects_missing_grid_node() -> None:
    node_history = _sample_node_load_history()
    node_history = node_history[node_history["node_id"] != "TOWER_B"]

    with pytest.raises(ValueError, match="누락된 GridNode"):
        normalize_grid_line_flow_history(
            node_load_history_df=node_history,
            grid_dataset=_sample_grid_dataset(),
        )
