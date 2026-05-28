from __future__ import annotations

from datetime import datetime

from src.data.adapters.vworld_adapter import get_map_capability
from src.data.schemas import ScenarioContext
from src.services.map_overlay_service import MapOverlayService
from src.services.prediction_service import PredictionService
from src.ui.map_overlay_renderer import (
    line_id_from_overlay_line,
    line_style_for_status,
    line_utilization_from_overlay_line,
)
from src.ui.table_selection import selected_value_from_dataframe_event


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="prediction-page-contract",
        title="Prediction Page Contract",
        region="South Korea",
        created_at=datetime(2026, 5, 17, 13, 0),
        created_by="pytest",
    )


def test_prediction_risk_table_selection_returns_line_id():
    rows = [
        {
            "선로 ID": "L01",
            "구간": "서울 → 대전",
            "위험도": "high",
            "예측 이용률 (%)": 92.5,
            "피크 시각": "18:00",
        },
        {
            "선로 ID": "L07",
            "구간": "대전 → 대구",
            "위험도": "critical",
            "예측 이용률 (%)": 104.2,
            "피크 시각": "19:00",
        },
    ]

    selected = selected_value_from_dataframe_event(
        {"selection": {"rows": [1]}},
        rows,
        "선로 ID",
    )

    assert selected == "L07"


def test_prediction_overlay_line_ids_match_risk_line_ids():
    scenario = _scenario()
    prediction = PredictionService().run_mock_prediction(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.5,
    )
    overlay = MapOverlayService().build_prediction_overlay(
        prediction,
        map_capability=get_map_capability(api_key="", use_settings=False),
    )

    risk_line_ids = {risk.line_id for risk in prediction.risk_lines}
    overlay_line_ids = {line_id_from_overlay_line(line) for line in overlay.lines}

    assert prediction.risk_lines
    assert overlay.scenario.scenario_id == scenario.scenario_id
    assert overlay_line_ids == risk_line_ids
    assert all(line.kind == "risk_line" for line in overlay.lines)
    assert all(line_id.startswith("GLINE_") for line_id in overlay_line_ids)
    assert all(point.metadata["coordinate_precision"] == "grid_node" for point in overlay.points)


def test_prediction_overlay_uses_predicted_utilization_for_fallback_tables():
    scenario = _scenario()
    prediction = PredictionService().run_mock_prediction(
        scenario=scenario,
        created_at=scenario.created_at,
        load_scale=1.5,
    )
    overlay = MapOverlayService().build_prediction_overlay(
        prediction,
        map_capability=get_map_capability(api_key="", use_settings=False),
    )
    first_line = overlay.lines[0]

    assert line_utilization_from_overlay_line(first_line) == first_line.metadata["predicted_utilization"]


def test_selected_prediction_line_style_is_emphasized():
    base = line_style_for_status("critical", selected=False)
    selected = line_style_for_status("critical", selected=True)

    assert selected["weight"] > base["weight"]
    assert selected["opacity"] > base["opacity"]
    assert selected["color"] != base["color"]
