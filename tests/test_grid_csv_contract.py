from __future__ import annotations

import csv
from collections import deque
from pathlib import Path
from typing import get_args

from src.data.schemas import GridDataSource, GridLineStatus, GridNodeType


GRID_MOCK_DIR = Path("data/grid/mock")

EXPECTED_COLUMNS = {
    "nodes.csv": [
        "node_id",
        "node_name",
        "node_type",
        "latitude",
        "longitude",
        "voltage_kv",
        "region",
        "base_load_mw",
        "elevation_m",
        "coordinate_system",
        "elevation_source",
        "source",
        "source_id",
    ],
    "lines.csv": [
        "line_id",
        "from_node_id",
        "to_node_id",
        "voltage_kv",
        "capacity_mw",
        "reactance_pu",
        "distance_km",
        "resistance_pu",
        "loss_factor",
        "terrain_risk",
        "is_bidirectional",
        "status",
        "source",
    ],
    "plants.csv": [
        "plant_id",
        "plant_name",
        "node_id",
        "capacity_mw",
        "fuel_type",
        "min_output_mw",
        "max_output_mw",
        "ramp_rate_mw_per_h",
        "availability",
        "operating_cost",
        "emission_factor",
        "source",
    ],
    "tower_candidates.csv": [
        "tower_id",
        "tower_name",
        "node_id",
        "voltage_kv",
        "elevation_m",
        "height_m",
        "terrain_slope_deg",
        "install_cost_billion",
        "land_type",
        "environment_risk",
        "policy_risk",
        "accessibility_score",
        "nearest_node_id",
        "source",
    ],
}

EXPECTED_PLANT_NODE_IDS = {
    "PLANT_INCHEON",
    "PLANT_GWANGJU",
    "PLANT_SOKCHO",
    "PLANT_BUSAN",
    "PLANT_ULSAN",
    "PLANT_POHANG",
}

EXPECTED_TOWER_NODE_IDS = {
    "TOWER_GEOCHANG",
    "TOWER_SEOUL",
    "TOWER_GANGNEUNG",
    "TOWER_DAEJEON",
    "TOWER_CHUNCHEON",
    "TOWER_JEJU",
    "TOWER_GUMI",
    "TOWER_DAEGU",
    "TOWER_CHANGWON",
    "TOWER_YEONGCHEON",
    "TOWER_SANGJU",
    "TOWER_HAENAM",
}


def _read_rows(filename: str) -> list[dict[str, str]]:
    with (GRID_MOCK_DIR / filename).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def _read_fieldnames(filename: str) -> list[str]:
    with (GRID_MOCK_DIR / filename).open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or [])


def _float(row: dict[str, str], key: str) -> float | None:
    value = row[key]
    if value == "":
        return None
    return float(value)


def test_grid_csv_schema_headers_are_fixed():
    for filename, expected_columns in EXPECTED_COLUMNS.items():
        assert _read_fieldnames(filename) == expected_columns


def test_grid_mock_nodes_include_all_default_assets():
    rows = _read_rows("nodes.csv")
    node_ids = {row["node_id"] for row in rows}
    node_types = set(get_args(GridNodeType))
    sources = set(get_args(GridDataSource))

    assert len(rows) == 18
    assert node_ids == EXPECTED_PLANT_NODE_IDS | EXPECTED_TOWER_NODE_IDS
    assert len(node_ids) == len(rows)

    for row in rows:
        assert row["node_type"] in node_types
        assert row["source"] in sources
        assert row["coordinate_system"] == "EPSG:4326"
        assert row["elevation_source"] == "not_queried"
        assert _float(row, "latitude") is not None
        assert _float(row, "longitude") is not None
        assert _float(row, "voltage_kv") is not None
        assert _float(row, "base_load_mw") is not None


def test_grid_mock_lines_reference_nodes_and_form_connected_graph():
    nodes = {row["node_id"]: row for row in _read_rows("nodes.csv")}
    rows = _read_rows("lines.csv")
    line_ids = {row["line_id"] for row in rows}
    statuses = set(get_args(GridLineStatus))
    sources = set(get_args(GridDataSource))
    neighbors = {node_id: set() for node_id in nodes}

    assert len(line_ids) == len(rows)

    for row in rows:
        from_node_id = row["from_node_id"]
        to_node_id = row["to_node_id"]
        assert from_node_id in nodes
        assert to_node_id in nodes
        assert from_node_id != to_node_id
        assert row["is_bidirectional"] in {"true", "false"}
        assert row["status"] in statuses
        assert row["source"] in sources
        assert (_float(row, "voltage_kv") or 0.0) > 0.0
        assert (_float(row, "capacity_mw") or 0.0) > 0.0
        assert (_float(row, "reactance_pu") or 0.0) > 0.0
        assert (_float(row, "distance_km") or 0.0) > 0.0
        assert 0.0 <= (_float(row, "terrain_risk") or 0.0) <= 1.0
        neighbors[from_node_id].add(to_node_id)
        neighbors[to_node_id].add(from_node_id)

    start_node_id = next(iter(nodes))
    seen = {start_node_id}
    queue: deque[str] = deque([start_node_id])
    while queue:
        current_node_id = queue.popleft()
        for next_node_id in neighbors[current_node_id]:
            if next_node_id not in seen:
                seen.add(next_node_id)
                queue.append(next_node_id)

    assert seen == set(nodes)


def test_grid_mock_plants_reference_power_plant_nodes():
    nodes = {row["node_id"]: row for row in _read_rows("nodes.csv")}
    rows = _read_rows("plants.csv")

    assert {row["node_id"] for row in rows} == EXPECTED_PLANT_NODE_IDS

    for row in rows:
        node = nodes[row["node_id"]]
        capacity_mw = _float(row, "capacity_mw") or 0.0
        min_output_mw = _float(row, "min_output_mw") or 0.0
        max_output_mw = _float(row, "max_output_mw") or 0.0
        availability = _float(row, "availability") or 0.0

        assert node["node_type"] == "power_plant"
        assert capacity_mw > 0.0
        assert 0.0 <= min_output_mw <= max_output_mw <= capacity_mw
        assert 0.0 <= availability <= 1.0
        assert row["source"] in set(get_args(GridDataSource))


def test_grid_mock_towers_reference_transmission_tower_nodes():
    nodes = {row["node_id"]: row for row in _read_rows("nodes.csv")}
    rows = _read_rows("tower_candidates.csv")

    assert {row["node_id"] for row in rows} == EXPECTED_TOWER_NODE_IDS

    for row in rows:
        node = nodes[row["node_id"]]
        nearest_node_id = row["nearest_node_id"]

        assert node["node_type"] == "transmission_tower"
        assert nearest_node_id in nodes
        assert (_float(row, "voltage_kv") or 0.0) > 0.0
        assert (_float(row, "height_m") or 0.0) > 0.0
        assert (_float(row, "terrain_slope_deg") or 0.0) >= 0.0
        assert (_float(row, "install_cost_billion") or 0.0) > 0.0
        assert 0.0 <= (_float(row, "environment_risk") or 0.0) <= 1.0
        assert 0.0 <= (_float(row, "policy_risk") or 0.0) <= 1.0
        assert 0.0 <= (_float(row, "accessibility_score") or 0.0) <= 1.0
        assert row["source"] in set(get_args(GridDataSource))


def test_grid_csv_schema_document_matches_mock_files():
    document = Path("docs/GRID_CSV_SCHEMA_2026-05-29.md").read_text(encoding="utf-8")

    for filename, expected_columns in EXPECTED_COLUMNS.items():
        path = f"data/grid/mock/{filename}"
        header = ",".join(expected_columns)

        assert path in document
        assert header in document

    for contract_name in [
        "GridNode",
        "GridLine",
        "PowerPlantSpec",
        "TransmissionTowerSpec",
        "GridDataset",
    ]:
        assert contract_name in document
