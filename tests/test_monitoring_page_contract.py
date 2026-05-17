from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.data.adapters.vworld_adapter import get_map_capability
from src.data.schemas import ScenarioContext
from src.services.map_overlay_service import MapOverlayService
from src.services.monitoring_service import MonitoringService
from src.ui.map_overlay_renderer import line_id_from_overlay_line, line_style_for_status
from src.ui.table_selection import selected_value_from_dataframe_event


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="monitoring-page-contract",
        title="Monitoring Page Contract",
        region="South Korea",
        created_at=datetime(2026, 5, 17, 12, 0),
        created_by="pytest",
    )


def test_dataframe_selection_event_returns_selected_line_id_from_mapping():
    rows = [
        {"선로 ID": "L01", "구간": "A -> B"},
        {"선로 ID": "L12", "구간": "C -> D"},
    ]

    value = selected_value_from_dataframe_event(
        {"selection": {"rows": [1]}},
        rows,
        "선로 ID",
    )

    assert value == "L12"


def test_dataframe_selection_event_returns_selected_line_id_from_object():
    @dataclass
    class Selection:
        rows: list[int]

    @dataclass
    class Event:
        selection: Selection

    rows = [
        {"선로 ID": "L01", "구간": "A -> B"},
        {"선로 ID": "L03", "구간": "C -> D"},
    ]

    value = selected_value_from_dataframe_event(
        Event(selection=Selection(rows=[0])),
        rows,
        "선로 ID",
    )

    assert value == "L01"


def test_dataframe_selection_event_ignores_missing_or_out_of_range_selection():
    rows = [{"선로 ID": "L01", "구간": "A -> B"}]

    assert selected_value_from_dataframe_event(None, rows, "선로 ID") is None
    assert selected_value_from_dataframe_event({"selection": {"rows": []}}, rows, "선로 ID") is None
    assert selected_value_from_dataframe_event({"selection": {"rows": [99]}}, rows, "선로 ID") is None
    assert selected_value_from_dataframe_event({"selection": {"rows": ["bad"]}}, rows, "선로 ID") is None


def test_monitoring_overlay_line_ids_match_status_table_source():
    scenario = _scenario()
    monitoring = MonitoringService().run_dc_power_flow(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.0,
    )
    overlay = MapOverlayService().build_monitoring_overlay(
        monitoring,
        map_capability=get_map_capability(api_key="", use_settings=False),
    )

    source_line_ids = {line.line_id for line in monitoring.line_statuses}
    overlay_line_ids = {line_id_from_overlay_line(line) for line in overlay.lines}

    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay_line_ids == source_line_ids
    assert all(line.metadata["line_id"] in source_line_ids for line in overlay.lines)


def test_selected_line_style_is_visibly_emphasized():
    base = line_style_for_status("warning", selected=False)
    selected = line_style_for_status("warning", selected=True)

    assert selected["weight"] > base["weight"]
    assert selected["opacity"] > base["opacity"]
    assert selected["color"] != base["color"]
