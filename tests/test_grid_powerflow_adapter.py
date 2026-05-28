from __future__ import annotations

from datetime import datetime

from src.data.grid_builder import build_default_grid_dataset
from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
from src.data.schemas import ScenarioContext
from src.services.monitoring_service import MonitoringService


def test_grid_powerflow_adapter_uses_grid_node_and_line_ids():
    dataset = build_default_grid_dataset(created_at=datetime(2026, 5, 29, 16, 0))

    inputs = build_powerflow_inputs_from_grid(dataset)

    assert len(inputs.buses) == len(dataset.nodes)
    assert len(inputs.lines) == len(dataset.lines)
    assert inputs.slack_bus_id == "PLANT_ULSAN"
    assert all(bus.bus_id.startswith(("PLANT_", "TOWER_")) for bus in inputs.buses)
    assert all(line.line_id.startswith("GLINE_") for line in inputs.lines)
    assert not any(bus.bus_id.startswith(("BUS_", "B0", "SITE_")) for bus in inputs.buses)


def test_monitoring_dc_power_flow_uses_grid_dataset_metadata():
    scenario = ScenarioContext(
        scenario_id="grid-monitoring",
        created_at=datetime(2026, 5, 29, 16, 0),
    )

    result = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )

    assert result.source == "dc_power_flow"
    assert result.fallback.mode == "none"
    assert result.metadata["legacy_bus_source"] is False
    assert result.metadata["slack_bus_id"].startswith("PLANT_")
    assert all(line.line_id.startswith("GLINE_") for line in result.line_statuses)
    assert all(line.from_bus.startswith(("PLANT_", "TOWER_")) for line in result.line_statuses)
    assert all(line.to_bus.startswith(("PLANT_", "TOWER_")) for line in result.line_statuses)
