from __future__ import annotations

from datetime import datetime
import json

import pytest

from src.data.schemas import (
    InstallationPoint,
    SavedScenarioState,
    ScenarioContext,
    ScenarioPageState,
)
from src.services.monitoring_service import MonitoringService
from src.services.prediction_service import PredictionService
from src.services.scenario_service import ScenarioService
from src.services.simulation_service import SimulationService


def _service(tmp_path):
    return ScenarioService(storage_path=tmp_path / "scenarios.json")


def test_save_and_load_scenario_round_trips_fields(tmp_path):
    service = _service(tmp_path)
    scenario = ScenarioContext(
        scenario_id="shared-001",
        title="Shared Scenario",
        description="Monitoring, Simulation, Prediction 공유 시나리오",
        region="South Korea",
        created_at=datetime(2026, 5, 11, 19, 0),
        created_by="pytest",
    )

    saved = service.save_scenario(scenario)
    loaded = service.load_scenario("shared-001")

    assert saved.scenario_id == "shared-001"
    assert loaded.scenario_id == scenario.scenario_id
    assert loaded.title == scenario.title
    assert loaded.description == scenario.description
    assert loaded.region == scenario.region
    assert loaded.created_at == scenario.created_at
    assert loaded.created_by == scenario.created_by


def test_save_scenario_updates_same_id_without_duplicate(tmp_path):
    service = _service(tmp_path)
    service.save_scenario(
        ScenarioContext(
            scenario_id="same-id",
            title="Before",
            created_at=datetime(2026, 5, 11, 19, 0),
        )
    )
    service.save_scenario(
        ScenarioContext(
            scenario_id="same-id",
            title="After",
            created_at=datetime(2026, 5, 11, 20, 0),
        )
    )

    scenarios = service.list_scenarios()

    assert len(scenarios) == 1
    assert scenarios[0].scenario_id == "same-id"
    assert scenarios[0].title == "After"
    assert scenarios[0].created_at == datetime(2026, 5, 11, 20, 0)


def test_save_and_load_scenario_state_round_trips_page_inputs(tmp_path):
    service = _service(tmp_path)
    installation = InstallationPoint(
        installation_id="tower-001",
        label="신규 송전탑 1",
        kind="transmission_tower",
        latitude=36.45,
        longitude=127.85,
        mode="new",
        voltage_kv=345.0,
        notes="현장 검토",
        created_at=datetime(2026, 5, 17, 12, 0),
    )
    saved_state = SavedScenarioState(
        scenario=ScenarioContext(
            scenario_id="full-state",
            title="Full State",
            created_at=datetime(2026, 5, 17, 12, 0),
        ),
        page_state=ScenarioPageState(
            landing_installations=[installation],
            monitoring_load_scale=1.25,
            monitoring_data_source="DC Power Flow",
            simulation_start_bus_id="BUS_001",
            simulation_end_bus_id="BUS_011",
            simulation_candidate_site_ids=["CANDIDATE_A", "CANDIDATE_B"],
            simulation_load_scale=1.15,
            prediction_load_scale=1.1,
            prediction_model_source="Baseline",
            prediction_selected_bus_ids=["BUS_001", "BUS_011"],
            prediction_retrain=False,
            prediction_epochs=20,
        ),
    )

    service.save_scenario_state(saved_state)
    loaded = service.load_scenario_state("full-state")

    assert loaded.scenario.scenario_id == "full-state"
    assert loaded.page_state.monitoring_load_scale == 1.25
    assert loaded.page_state.simulation_candidate_site_ids == ["CANDIDATE_A", "CANDIDATE_B"]
    assert loaded.page_state.prediction_model_source == "Baseline"
    assert loaded.page_state.prediction_selected_bus_ids == ["BUS_001", "BUS_011"]
    assert len(loaded.page_state.landing_installations) == 1
    assert loaded.page_state.landing_installations[0].installation_id == "tower-001"
    assert loaded.page_state.landing_installations[0].elevation_source == "not_queried"


def test_load_scenario_state_keeps_legacy_context_only_records_compatible(tmp_path):
    storage_path = tmp_path / "scenarios.json"
    storage_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_id": "legacy",
                        "title": "Legacy",
                        "description": "ScenarioContext only",
                        "region": "South Korea",
                        "created_at": "2026-05-17T12:00:00",
                        "created_by": "pytest",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ScenarioService(storage_path=storage_path)

    loaded = service.load_scenario_state("legacy")

    assert loaded.scenario.scenario_id == "legacy"
    assert loaded.scenario.title == "Legacy"
    assert loaded.page_state == ScenarioPageState()


def test_legacy_save_scenario_preserves_existing_page_state(tmp_path):
    service = _service(tmp_path)
    service.save_scenario_state(
        SavedScenarioState(
            scenario=ScenarioContext(scenario_id="preserve", title="Before"),
            page_state=ScenarioPageState(
                simulation_candidate_site_ids=["CANDIDATE_A"],
                prediction_model_source="GNN",
            ),
        )
    )

    service.save_scenario(ScenarioContext(scenario_id="preserve", title="After"))
    loaded = service.load_scenario_state("preserve")

    assert loaded.scenario.title == "After"
    assert loaded.page_state.simulation_candidate_site_ids == ["CANDIDATE_A"]
    assert loaded.page_state.prediction_model_source == "GNN"


def test_list_scenarios_is_empty_when_storage_file_is_missing(tmp_path):
    service = _service(tmp_path)

    assert service.list_scenarios() == []


def test_list_scenarios_sorts_by_created_at_desc(tmp_path):
    service = _service(tmp_path)
    service.save_scenario(
        ScenarioContext(
            scenario_id="older",
            title="Older",
            created_at=datetime(2026, 5, 10, 12, 0),
        )
    )
    service.save_scenario(
        ScenarioContext(
            scenario_id="newer",
            title="Newer",
            created_at=datetime(2026, 5, 11, 12, 0),
        )
    )

    assert [scenario.scenario_id for scenario in service.list_scenarios()] == [
        "newer",
        "older",
    ]


def test_load_missing_scenario_raises_key_error(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(KeyError, match="missing"):
        service.load_scenario("missing")


def test_save_empty_scenario_id_raises_value_error(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="scenario_id"):
        service.save_scenario(ScenarioContext(scenario_id="   "))


def test_delete_scenario_removes_saved_record(tmp_path):
    service = _service(tmp_path)
    service.save_scenario(ScenarioContext(scenario_id="delete-me"))

    assert service.delete_scenario("delete-me") is True
    assert service.delete_scenario("delete-me") is False
    with pytest.raises(KeyError):
        service.load_scenario("delete-me")


def test_corrupt_json_store_raises_value_error(tmp_path):
    storage_path = tmp_path / "scenarios.json"
    storage_path.write_text("{not-json", encoding="utf-8")
    service = ScenarioService(storage_path=storage_path)

    with pytest.raises(ValueError, match="JSON"):
        service.list_scenarios()


def test_saved_scenario_context_is_shared_across_core_services(tmp_path):
    service = _service(tmp_path)
    saved = service.save_scenario(
        ScenarioContext(
            scenario_id="shared-integration",
            title="Shared Integration",
            created_at=datetime(2026, 5, 11, 19, 0),
        )
    )
    loaded = service.load_scenario(saved.scenario_id)

    monitoring = MonitoringService().run_dc_power_flow(
        scenario=loaded,
        load_scale=1.0,
    )
    simulation_service = SimulationService()
    simulation = simulation_service.run_simulation(
        simulation_service.build_default_input(
            scenario=loaded,
            load_scale=1.0,
        )
    )
    prediction = PredictionService().run_mock_prediction(
        scenario=loaded,
        load_scale=1.0,
    )

    assert monitoring.scenario.scenario_id == "shared-integration"
    assert simulation.scenario.scenario_id == "shared-integration"
    assert prediction.scenario.scenario_id == "shared-integration"
    assert simulation.source == "astar"
    assert prediction.source == "mock"


def test_saved_file_uses_scenarios_collection(tmp_path):
    storage_path = tmp_path / "scenarios.json"
    service = ScenarioService(storage_path=storage_path)
    service.save_scenario(ScenarioContext(scenario_id="file-check"))

    payload = json.loads(storage_path.read_text(encoding="utf-8"))

    assert list(payload) == ["scenarios"]
    assert payload["scenarios"][0]["scenario_id"] == "file-check"
    assert "updated_at" in payload["scenarios"][0]
