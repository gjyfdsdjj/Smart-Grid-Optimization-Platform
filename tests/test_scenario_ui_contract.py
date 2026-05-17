from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.data.schemas import InstallationPoint, ScenarioContext, ScenarioPageState
from src.ui.scenario_controls import (
    LANDING_INSTALLATIONS_KEY,
    MONITORING_DATA_SOURCE_KEY,
    MONITORING_LOAD_SCALE_KEY,
    PREDICTION_LOAD_SCALE_KEY,
    PREDICTION_MODEL_SOURCE_KEY,
    PREDICTION_SELECTED_BUS_IDS_KEY,
    SIMULATION_CANDIDATES_KEY,
    SIMULATION_END_BUS_KEY,
    SIMULATION_LOAD_SCALE_KEY,
    SIMULATION_START_BUS_KEY,
    apply_saved_page_state,
    build_default_scenario,
    build_scenario_from_form,
    collect_current_page_state,
    scenario_exists,
    scenario_option_label,
    scenario_result_state_keys,
)


def test_default_scenario_uses_shared_contract_and_hour_boundary():
    scenario = build_default_scenario(now=datetime(2026, 5, 17, 12, 34, 56))

    assert scenario.scenario_id == "sgop-demo-scenario"
    assert scenario.title == "SGOP Demo Scenario"
    assert scenario.region == "South Korea"
    assert scenario.created_at == datetime(2026, 5, 17, 12, 0)
    assert scenario.created_by == "streamlit-session"


def test_scenario_form_values_are_normalized_to_context():
    current = ScenarioContext(
        scenario_id=" current-id ",
        title="Before",
        created_at=datetime(2026, 5, 17, 12, 0),
    )

    scenario = build_scenario_from_form(
        scenario_id=" current-id ",
        title="  현재 운영 시나리오  ",
        description="  설명  ",
        region="  South Korea  ",
        created_by="  operator  ",
        current=current,
    )

    assert scenario.scenario_id == "current-id"
    assert scenario.title == "현재 운영 시나리오"
    assert scenario.description == "설명"
    assert scenario.region == "South Korea"
    assert scenario.created_by == "operator"
    assert scenario.created_at == current.created_at


def test_new_scenario_id_gets_new_created_at():
    current = ScenarioContext(
        scenario_id="before",
        created_at=datetime(2026, 5, 17, 12, 0),
    )

    scenario = build_scenario_from_form(
        scenario_id="after",
        title="After",
        description="",
        region="",
        created_by="pytest",
        current=current,
        now=datetime(2026, 5, 17, 13, 5, 6, 999),
    )

    assert scenario.scenario_id == "after"
    assert scenario.created_at == datetime(2026, 5, 17, 13, 5, 6)


def test_scenario_option_label_contains_id_title_region_and_created_at():
    scenario = ScenarioContext(
        scenario_id="shared-001",
        title="Shared Scenario",
        region="South Korea",
        created_at=datetime(2026, 5, 17, 12, 0),
    )

    label = scenario_option_label(scenario)

    assert "shared-001" in label
    assert "Shared Scenario" in label
    assert "South Korea" in label
    assert "2026-05-17 12:00" in label


def test_scenario_exists_matches_trimmed_ids():
    scenarios = [
        ScenarioContext(scenario_id="alpha"),
        ScenarioContext(scenario_id="beta"),
    ]

    assert scenario_exists(scenarios, " beta ") is True
    assert scenario_exists(scenarios, "gamma") is False
    assert scenario_exists(scenarios, "   ") is False


def test_scenario_result_state_keys_cover_core_page_caches():
    keys = set(scenario_result_state_keys())

    assert "sgop_monitoring_result" in keys
    assert "sgop_monitoring_overlay" in keys
    assert "sim_result" in keys
    assert "sim_map_overlay" in keys
    assert "pred_result" in keys
    assert "pred_map_overlay" in keys
    assert "pred_scenario_a" in keys
    assert "selected_candidates" not in keys
    assert "pred_source" not in keys


def test_collect_current_page_state_reads_core_input_keys():
    installation = InstallationPoint(
        installation_id="plant-001",
        label="신규 발전소",
        kind="power_plant",
        latitude=36.0,
        longitude=127.0,
        capacity_mw=500.0,
        created_at=datetime(2026, 5, 17, 12, 0),
    )
    state = {
        LANDING_INSTALLATIONS_KEY: [installation],
        MONITORING_LOAD_SCALE_KEY: 1.2,
        MONITORING_DATA_SOURCE_KEY: "DC Power Flow",
        SIMULATION_START_BUS_KEY: "BUS_001",
        SIMULATION_END_BUS_KEY: "BUS_011",
        SIMULATION_CANDIDATES_KEY: ["CANDIDATE_A"],
        SIMULATION_LOAD_SCALE_KEY: 1.15,
        PREDICTION_LOAD_SCALE_KEY: 1.1,
        PREDICTION_MODEL_SOURCE_KEY: "Baseline",
        PREDICTION_SELECTED_BUS_IDS_KEY: ["BUS_001", "BUS_013"],
    }

    page_state = collect_current_page_state(state)

    assert page_state.landing_installations == [installation]
    assert page_state.monitoring_load_scale == 1.2
    assert page_state.simulation_candidate_site_ids == ["CANDIDATE_A"]
    assert page_state.prediction_model_source == "Baseline"
    assert page_state.prediction_selected_bus_ids == ["BUS_001", "BUS_013"]


def test_apply_saved_page_state_restores_inputs_and_clears_results():
    state = {
        "sgop_monitoring_result": object(),
        "sim_result": object(),
        "pred_result": object(),
        "sim_run": True,
    }
    page_state = ScenarioPageState(
        monitoring_load_scale=1.3,
        monitoring_data_source="mock",
        simulation_start_bus_id="BUS_002",
        simulation_end_bus_id="BUS_012",
        simulation_candidate_site_ids=["CANDIDATE_B"],
        simulation_load_scale=1.2,
        prediction_load_scale=1.15,
        prediction_model_source="GNN",
        prediction_selected_bus_ids=["BUS_002"],
    )

    apply_saved_page_state(page_state, state=state)

    assert state[MONITORING_LOAD_SCALE_KEY] == 1.3
    assert state[MONITORING_DATA_SOURCE_KEY] == "mock"
    assert state[SIMULATION_START_BUS_KEY] == "BUS_002"
    assert state[SIMULATION_END_BUS_KEY] == "BUS_012"
    assert state[SIMULATION_CANDIDATES_KEY] == ["CANDIDATE_B"]
    assert state["selected_candidates"] == ["CANDIDATE_B"]
    assert state[PREDICTION_MODEL_SOURCE_KEY] == "GNN"
    assert state[PREDICTION_SELECTED_BUS_IDS_KEY] == ["BUS_002"]
    assert "sgop_monitoring_result" not in state
    assert "sim_result" not in state
    assert "pred_result" not in state
    assert state["sim_run"] is False


def test_core_pages_use_common_scenario_sidebar():
    root = Path(__file__).resolve().parents[1]
    page_paths = [
        root / "app.py",
        root / "pages" / "01_monitoring.py",
        root / "pages" / "02_simulation.py",
        root / "pages" / "03_prediction.py",
    ]

    for path in page_paths:
        source = path.read_text(encoding="utf-8")
        assert "from src.ui.scenario_controls import render_scenario_sidebar" in source
        assert "render_scenario_sidebar()" in source
        assert "def _get_shared_scenario" not in source
