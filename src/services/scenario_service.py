# 사용자 시뮬레이션 시나리오의 저장, 불러오기, 비교를 관리한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.data.schemas import (
    InstallationPoint,
    SavedScenarioState,
    ScenarioContext,
    ScenarioPageState,
)


class ScenarioService:
    """시나리오 식별자와 페이지 입력 상태를 JSON 파일에 저장한다."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self.storage_path = (
            Path(storage_path)
            if storage_path is not None
            else settings.private_data_dir / "scenarios.json"
        )

    def save_scenario(self, scenario: ScenarioContext) -> ScenarioContext:
        """시나리오를 저장한다. 기존 페이지 상태가 있으면 유지한다."""
        if not isinstance(scenario, ScenarioContext):
            raise TypeError("scenario는 ScenarioContext여야 합니다.")

        scenario_id = self._validate_scenario_id(scenario.scenario_id)
        page_state = self._find_saved_page_state(scenario_id) or ScenarioPageState()
        saved_state = self.save_scenario_state(
            SavedScenarioState(scenario=scenario, page_state=page_state)
        )
        return saved_state.scenario

    def save_scenario_state(self, saved_state: SavedScenarioState) -> SavedScenarioState:
        """시나리오와 페이지 입력 상태를 함께 저장한다."""
        if not isinstance(saved_state, SavedScenarioState):
            raise TypeError("saved_state는 SavedScenarioState여야 합니다.")
        if not isinstance(saved_state.scenario, ScenarioContext):
            raise TypeError("saved_state.scenario는 ScenarioContext여야 합니다.")
        if not isinstance(saved_state.page_state, ScenarioPageState):
            raise TypeError("saved_state.page_state는 ScenarioPageState여야 합니다.")

        scenario_id = self._validate_scenario_id(saved_state.scenario.scenario_id)
        resolved_scenario = replace(
            saved_state.scenario,
            scenario_id=scenario_id,
            created_at=saved_state.scenario.created_at or _round_to_second(datetime.now()),
        )
        resolved_state = replace(
            saved_state,
            scenario=resolved_scenario,
            schema_version=int(saved_state.schema_version or 1),
        )

        store = self._read_store()
        scenarios = store["scenarios"]
        record = _saved_state_to_record(resolved_state)

        for index, saved in enumerate(scenarios):
            saved_id = _record_scenario_id(saved)
            if saved_id == scenario_id:
                scenarios[index] = record
                break
        else:
            scenarios.append(record)

        self._write_store(store)
        return resolved_state

    def load_scenario(self, scenario_id: str) -> ScenarioContext:
        """scenario_id에 해당하는 시나리오를 반환한다."""
        return self.load_scenario_state(scenario_id).scenario

    def load_scenario_state(self, scenario_id: str) -> SavedScenarioState:
        """scenario_id에 해당하는 전체 저장 상태를 반환한다."""
        resolved_id = self._validate_scenario_id(scenario_id)
        for record in self._read_store()["scenarios"]:
            if _record_scenario_id(record) == resolved_id:
                return _saved_state_from_record(record)
        raise KeyError(f"저장된 시나리오가 없습니다: {resolved_id}")

    def list_scenarios(self) -> list[ScenarioContext]:
        """저장된 시나리오 목록을 created_at 내림차순으로 반환한다."""
        scenarios = [
            _saved_state_from_record(record).scenario
            for record in self._read_store()["scenarios"]
        ]
        return sorted(
            scenarios,
            key=lambda scenario: (
                scenario.created_at or datetime.min,
                scenario.scenario_id,
            ),
            reverse=True,
        )

    def delete_scenario(self, scenario_id: str) -> bool:
        """scenario_id에 해당하는 시나리오를 삭제한다."""
        resolved_id = self._validate_scenario_id(scenario_id)
        store = self._read_store()
        original_count = len(store["scenarios"])
        store["scenarios"] = [
            record
            for record in store["scenarios"]
            if _record_scenario_id(record) != resolved_id
        ]

        if len(store["scenarios"]) == original_count:
            return False

        self._write_store(store)
        return True

    def _find_saved_page_state(self, scenario_id: str) -> ScenarioPageState | None:
        for record in self._read_store()["scenarios"]:
            if _record_scenario_id(record) == scenario_id:
                return _saved_state_from_record(record).page_state
        return None

    def _read_store(self) -> dict[str, list[dict[str, Any]]]:
        if not self.storage_path.exists():
            return {"scenarios": []}

        try:
            raw_store = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"시나리오 저장 파일의 JSON 형식이 올바르지 않습니다: {self.storage_path}"
            ) from exc

        if not isinstance(raw_store, dict):
            raise ValueError("시나리오 저장 파일의 최상위 구조는 객체여야 합니다.")

        scenarios = raw_store.get("scenarios", [])
        if not isinstance(scenarios, list):
            raise ValueError("시나리오 저장 파일의 scenarios 필드는 리스트여야 합니다.")

        return {"scenarios": scenarios}

    def _write_store(self, store: dict[str, list[dict[str, Any]]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _validate_scenario_id(self, scenario_id: str) -> str:
        if not isinstance(scenario_id, str):
            raise TypeError("scenario_id는 문자열이어야 합니다.")

        resolved_id = scenario_id.strip()
        if not resolved_id:
            raise ValueError("scenario_id는 빈 문자열일 수 없습니다.")
        return resolved_id


def _saved_state_to_record(saved_state: SavedScenarioState) -> dict[str, Any]:
    scenario_record = _scenario_to_record(saved_state.scenario)
    return {
        **scenario_record,
        "schema_version": saved_state.schema_version,
        "scenario": scenario_record,
        "page_state": _page_state_to_record(saved_state.page_state),
    }


def _saved_state_from_record(record: dict[str, Any]) -> SavedScenarioState:
    if not isinstance(record, dict):
        raise ValueError("시나리오 레코드는 객체여야 합니다.")

    raw_scenario = record.get("scenario")
    scenario_record = raw_scenario if isinstance(raw_scenario, dict) else record
    page_state_record = record.get("page_state", {})
    schema_version = _int_value(record.get("schema_version", 1), 1, "schema_version")

    return SavedScenarioState(
        scenario=_scenario_from_record(scenario_record),
        page_state=_page_state_from_record(page_state_record),
        schema_version=schema_version,
    )


def _scenario_to_record(scenario: ScenarioContext) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "description": scenario.description,
        "region": scenario.region,
        "created_at": (
            scenario.created_at.isoformat()
            if scenario.created_at is not None
            else None
        ),
        "created_by": scenario.created_by,
        "updated_at": _round_to_second(datetime.now()).isoformat(),
    }


def _scenario_from_record(record: dict[str, Any]) -> ScenarioContext:
    if not isinstance(record, dict):
        raise ValueError("시나리오 레코드는 객체여야 합니다.")

    scenario_id = str(record.get("scenario_id", "")).strip()
    if not scenario_id:
        raise ValueError("시나리오 레코드에 scenario_id가 없습니다.")

    return ScenarioContext(
        scenario_id=scenario_id,
        title=str(record.get("title", "") or ""),
        description=str(record.get("description", "") or ""),
        region=str(record.get("region", "") or ""),
        created_at=_parse_datetime(record.get("created_at")),
        created_by=str(record.get("created_by", "") or ""),
    )


def _page_state_to_record(page_state: ScenarioPageState) -> dict[str, Any]:
    return {
        "landing_installations": [
            _installation_point_to_record(installation)
            for installation in page_state.landing_installations
        ],
        "monitoring_load_scale": page_state.monitoring_load_scale,
        "monitoring_data_source": page_state.monitoring_data_source,
        "simulation_start_bus_id": page_state.simulation_start_bus_id,
        "simulation_end_bus_id": page_state.simulation_end_bus_id,
        "simulation_candidate_site_ids": list(page_state.simulation_candidate_site_ids),
        "simulation_load_scale": page_state.simulation_load_scale,
        "prediction_load_scale": page_state.prediction_load_scale,
        "prediction_model_source": page_state.prediction_model_source,
        "prediction_selected_bus_ids": list(page_state.prediction_selected_bus_ids),
        "prediction_retrain": page_state.prediction_retrain,
        "prediction_epochs": page_state.prediction_epochs,
        "metadata": dict(page_state.metadata),
    }


def _page_state_from_record(record: Any) -> ScenarioPageState:
    if record in (None, ""):
        return ScenarioPageState()
    if not isinstance(record, dict):
        raise ValueError("page_state는 객체여야 합니다.")

    return ScenarioPageState(
        landing_installations=[
            _installation_point_from_record(item)
            for item in _list_value(record.get("landing_installations"), "landing_installations")
        ],
        monitoring_load_scale=_float_value(
            record.get("monitoring_load_scale"), 1.0, "monitoring_load_scale"
        ),
        monitoring_data_source=str(record.get("monitoring_data_source") or "DC Power Flow"),
        simulation_start_bus_id=str(record.get("simulation_start_bus_id") or "BUS_001"),
        simulation_end_bus_id=str(record.get("simulation_end_bus_id") or "BUS_011"),
        simulation_candidate_site_ids=_str_list(
            record.get("simulation_candidate_site_ids"),
            "simulation_candidate_site_ids",
        ),
        simulation_load_scale=_float_value(
            record.get("simulation_load_scale"), 1.0, "simulation_load_scale"
        ),
        prediction_load_scale=_float_value(
            record.get("prediction_load_scale"), 1.0, "prediction_load_scale"
        ),
        prediction_model_source=str(record.get("prediction_model_source") or "Mock"),
        prediction_selected_bus_ids=_str_list(
            record.get("prediction_selected_bus_ids"),
            "prediction_selected_bus_ids",
        ),
        prediction_retrain=_bool_value(record.get("prediction_retrain"), False),
        prediction_epochs=_int_value(record.get("prediction_epochs"), 20, "prediction_epochs"),
        metadata=_dict_value(record.get("metadata"), "metadata"),
    )


def _installation_point_to_record(installation: InstallationPoint) -> dict[str, Any]:
    if not isinstance(installation, InstallationPoint):
        raise TypeError("landing_installations 항목은 InstallationPoint여야 합니다.")

    return {
        "installation_id": installation.installation_id,
        "label": installation.label,
        "kind": installation.kind,
        "latitude": installation.latitude,
        "longitude": installation.longitude,
        "mode": installation.mode,
        "elevation_m": installation.elevation_m,
        "coordinate_system": installation.coordinate_system,
        "elevation_source": installation.elevation_source,
        "capacity_mw": installation.capacity_mw,
        "voltage_kv": installation.voltage_kv,
        "notes": installation.notes,
        "created_at": (
            installation.created_at.isoformat()
            if installation.created_at is not None
            else None
        ),
        "metadata": dict(installation.metadata),
    }


def _installation_point_from_record(record: Any) -> InstallationPoint:
    if not isinstance(record, dict):
        raise ValueError("landing_installations 항목은 객체여야 합니다.")

    installation_id = str(record.get("installation_id", "")).strip()
    if not installation_id:
        raise ValueError("InstallationPoint 레코드에 installation_id가 없습니다.")

    return InstallationPoint(
        installation_id=installation_id,
        label=str(record.get("label", "") or ""),
        kind=str(record.get("kind") or "transmission_tower"),  # type: ignore[arg-type]
        latitude=_float_value(record.get("latitude"), 0.0, "latitude"),
        longitude=_float_value(record.get("longitude"), 0.0, "longitude"),
        mode=str(record.get("mode") or "new"),  # type: ignore[arg-type]
        elevation_m=_float_or_none(record.get("elevation_m"), "elevation_m"),
        coordinate_system=str(record.get("coordinate_system") or "EPSG:4326"),
        elevation_source=str(record.get("elevation_source") or "not_queried"),
        capacity_mw=_float_or_none(record.get("capacity_mw"), "capacity_mw"),
        voltage_kv=_float_or_none(record.get("voltage_kv"), "voltage_kv"),
        notes=str(record.get("notes", "") or ""),
        created_at=_parse_datetime(record.get("created_at")),
        metadata=_dict_value(record.get("metadata"), "metadata"),
    )


def _record_scenario_id(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    scenario_id = str(record.get("scenario_id", "") or "").strip()
    if scenario_id:
        return scenario_id
    nested = record.get("scenario")
    if isinstance(nested, dict):
        return str(nested.get("scenario_id", "") or "").strip()
    return ""


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("created_at은 ISO 문자열이어야 합니다.")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"created_at ISO 형식이 올바르지 않습니다: {value}") from exc


def _round_to_second(value: datetime) -> datetime:
    return value.replace(microsecond=0)


def _list_value(value: Any, field_name: str) -> list[Any]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name}은 리스트여야 합니다.")
    return value


def _str_list(value: Any, field_name: str) -> list[str]:
    return [str(item) for item in _list_value(value, field_name)]


def _dict_value(value: Any, field_name: str) -> dict[str, object]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name}은 객체여야 합니다.")
    return dict(value)


def _float_value(value: Any, default: float, field_name: str) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}은 숫자여야 합니다.") from exc


def _float_or_none(value: Any, field_name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}은 숫자 또는 null이어야 합니다.") from exc


def _int_value(value: Any, default: int, field_name: str) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}은 정수여야 합니다.") from exc


def _bool_value(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ValueError("boolean 필드는 true 또는 false여야 합니다.")
