"""공통 시나리오 sidebar UI와 session state 관리를 제공한다."""
from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime
from typing import Any, Iterable

import streamlit as st

from src.data.schemas import (
    InstallationPoint,
    SavedScenarioState,
    ScenarioContext,
    ScenarioPageState,
)
from src.services.scenario_service import ScenarioService


SCENARIO_STATE_KEY = "sgop_shared_scenario"
SCENARIO_NOTICE_KEY = "sgop_scenario_notice"
PAGE_STATE_RESTORE_PENDING_KEY = "sgop_page_state_restore_pending"
LANDING_INSTALLATIONS_KEY = "sgop_landing_installations"
MONITORING_LOAD_SCALE_KEY = "monitoring_load_scale"
MONITORING_DATA_SOURCE_KEY = "monitoring_data_source"
SIMULATION_START_BUS_KEY = "simulation_start_bus_id"
SIMULATION_END_BUS_KEY = "simulation_end_bus_id"
SIMULATION_CANDIDATES_KEY = "simulation_candidate_site_ids"
SIMULATION_LOAD_SCALE_KEY = "simulation_load_scale"
PREDICTION_LOAD_SCALE_KEY = "prediction_load_scale"
PREDICTION_MODEL_SOURCE_KEY = "prediction_model_source"
PREDICTION_SELECTED_BUS_IDS_KEY = "prediction_selected_bus_ids"
PREDICTION_RETRAIN_KEY = "prediction_retrain"
PREDICTION_EPOCHS_KEY = "prediction_epochs"

DEFAULT_SCENARIO_ID = "sgop-demo-scenario"
DEFAULT_SCENARIO_TITLE = "SGOP Demo Scenario"
DEFAULT_SCENARIO_DESCRIPTION = "Monitoring, Simulation, Prediction이 공유하는 기본 시나리오"
DEFAULT_SCENARIO_REGION = "South Korea"
DEFAULT_SCENARIO_CREATED_BY = "streamlit-session"

_SCENARIO_BOUND_RESULT_KEYS = (
    "sgop_landing_service_overlay",
    "sgop_monitoring_result",
    "sgop_monitoring_overlay",
    "monitoring_selected_line_id",
    "sim_result",
    "sim_map_capability",
    "sim_map_overlay",
    "pred_result",
    "pred_map_capability",
    "pred_map_overlay",
    "prediction_selected_line_id",
    "pred_scenario_a",
)


def scenario_result_state_keys() -> tuple[str, ...]:
    """시나리오가 바뀔 때 폐기해야 하는 화면 결과 캐시 키를 반환한다."""
    return _SCENARIO_BOUND_RESULT_KEYS


def collect_current_page_state(
    state: MutableMapping[str, Any] | None = None,
) -> ScenarioPageState:
    """현재 Streamlit session의 페이지 입력값을 저장 계약으로 모은다."""
    session_state = state if state is not None else st.session_state
    return ScenarioPageState(
        landing_installations=_coerce_installations(
            session_state.get(LANDING_INSTALLATIONS_KEY, [])
        ),
        monitoring_load_scale=_float_from_state(
            session_state,
            MONITORING_LOAD_SCALE_KEY,
            1.0,
        ),
        monitoring_data_source=str(
            session_state.get(MONITORING_DATA_SOURCE_KEY) or "DC Power Flow"
        ),
        simulation_start_bus_id=str(session_state.get(SIMULATION_START_BUS_KEY) or "BUS_001"),
        simulation_end_bus_id=str(session_state.get(SIMULATION_END_BUS_KEY) or "BUS_011"),
        simulation_candidate_site_ids=_str_list_from_state(
            session_state.get(
                SIMULATION_CANDIDATES_KEY,
                session_state.get("selected_candidates", []),
            )
        ),
        simulation_load_scale=_float_from_state(
            session_state,
            SIMULATION_LOAD_SCALE_KEY,
            1.0,
        ),
        prediction_load_scale=_float_from_state(
            session_state,
            PREDICTION_LOAD_SCALE_KEY,
            _float_from_state(session_state, "pred_scale", 1.0),
        ),
        prediction_model_source=str(
            session_state.get(PREDICTION_MODEL_SOURCE_KEY)
            or session_state.get("pred_source")
            or "Mock"
        ),
        prediction_selected_bus_ids=_str_list_from_state(
            session_state.get(PREDICTION_SELECTED_BUS_IDS_KEY, [])
        ),
        prediction_retrain=bool(session_state.get(PREDICTION_RETRAIN_KEY, False)),
        prediction_epochs=_int_from_state(session_state, PREDICTION_EPOCHS_KEY, 20),
    )


def apply_saved_page_state(
    page_state: ScenarioPageState,
    *,
    state: MutableMapping[str, Any] | None = None,
    clear_results: bool = True,
) -> None:
    """저장된 페이지 입력 상태를 session state에 복원한다."""
    if not isinstance(page_state, ScenarioPageState):
        raise TypeError("page_state는 ScenarioPageState여야 합니다.")

    session_state = state if state is not None else st.session_state
    session_state[LANDING_INSTALLATIONS_KEY] = list(page_state.landing_installations)
    session_state["sgop_landing_last_click"] = None
    session_state["sgop_landing_add_requested"] = False
    session_state[MONITORING_LOAD_SCALE_KEY] = page_state.monitoring_load_scale
    session_state[MONITORING_DATA_SOURCE_KEY] = page_state.monitoring_data_source
    session_state[SIMULATION_START_BUS_KEY] = page_state.simulation_start_bus_id
    session_state[SIMULATION_END_BUS_KEY] = page_state.simulation_end_bus_id
    session_state[SIMULATION_CANDIDATES_KEY] = list(page_state.simulation_candidate_site_ids)
    session_state["selected_candidates"] = list(page_state.simulation_candidate_site_ids)
    session_state[SIMULATION_LOAD_SCALE_KEY] = page_state.simulation_load_scale
    session_state[PREDICTION_LOAD_SCALE_KEY] = page_state.prediction_load_scale
    session_state[PREDICTION_MODEL_SOURCE_KEY] = page_state.prediction_model_source
    session_state[PREDICTION_SELECTED_BUS_IDS_KEY] = list(page_state.prediction_selected_bus_ids)
    session_state[PREDICTION_RETRAIN_KEY] = page_state.prediction_retrain
    session_state[PREDICTION_EPOCHS_KEY] = page_state.prediction_epochs
    session_state[PAGE_STATE_RESTORE_PENDING_KEY] = True

    if clear_results:
        clear_scenario_bound_results(state=session_state)


def build_default_scenario(now: datetime | None = None) -> ScenarioContext:
    """새 Streamlit session에서 사용할 기본 시나리오를 만든다."""
    created_at = (now or datetime.now()).replace(minute=0, second=0, microsecond=0)
    return ScenarioContext(
        scenario_id=DEFAULT_SCENARIO_ID,
        title=DEFAULT_SCENARIO_TITLE,
        description=DEFAULT_SCENARIO_DESCRIPTION,
        region=DEFAULT_SCENARIO_REGION,
        created_at=created_at,
        created_by=DEFAULT_SCENARIO_CREATED_BY,
    )


def build_scenario_from_form(
    *,
    scenario_id: str,
    title: str,
    description: str,
    region: str,
    created_by: str,
    current: ScenarioContext | None = None,
    now: datetime | None = None,
) -> ScenarioContext:
    """sidebar 입력값을 ScenarioContext 계약으로 정규화한다."""
    resolved_id = scenario_id.strip()
    current_id = current.scenario_id.strip() if current is not None else ""
    if current is not None and current.created_at is not None and resolved_id == current_id:
        created_at = current.created_at
    else:
        created_at = (now or datetime.now()).replace(microsecond=0)

    return ScenarioContext(
        scenario_id=resolved_id,
        title=title.strip(),
        description=description.strip(),
        region=region.strip(),
        created_at=created_at,
        created_by=created_by.strip(),
    )


def scenario_exists(scenarios: Iterable[ScenarioContext], scenario_id: str) -> bool:
    """저장 목록에 같은 scenario_id가 있는지 확인한다."""
    resolved_id = scenario_id.strip()
    if not resolved_id:
        return False
    return any(scenario.scenario_id.strip() == resolved_id for scenario in scenarios)


def scenario_option_label(scenario: ScenarioContext) -> str:
    """selectbox에 표시할 저장 시나리오 라벨을 만든다."""
    title = scenario.title or "제목 없음"
    created_at = (
        scenario.created_at.strftime("%Y-%m-%d %H:%M")
        if scenario.created_at is not None
        else "생성 시각 없음"
    )
    region = f" / {scenario.region}" if scenario.region else ""
    return f"{scenario.scenario_id} | {title}{region} | {created_at}"


def get_or_create_shared_scenario() -> ScenarioContext:
    """session state에서 공통 ScenarioContext를 가져오거나 기본값을 만든다."""
    scenario = st.session_state.get(SCENARIO_STATE_KEY)
    if isinstance(scenario, ScenarioContext):
        return scenario

    scenario = build_default_scenario()
    st.session_state[SCENARIO_STATE_KEY] = scenario
    return scenario


def clear_scenario_bound_results(state: MutableMapping[str, Any] | None = None) -> None:
    """시나리오 변경 뒤 이전 결과가 화면에 남지 않도록 관련 캐시를 비운다."""
    session_state = state if state is not None else st.session_state
    for key in _SCENARIO_BOUND_RESULT_KEYS:
        session_state.pop(key, None)
    session_state["sim_run"] = False


def set_shared_scenario(
    scenario: ScenarioContext,
    *,
    clear_results: bool = True,
) -> ScenarioContext:
    """공통 ScenarioContext를 session state에 반영한다."""
    st.session_state[SCENARIO_STATE_KEY] = scenario
    if clear_results:
        clear_scenario_bound_results()
    return scenario


def render_scenario_sidebar(service: ScenarioService | None = None) -> ScenarioContext:
    """저장/불러오기/삭제 UI를 sidebar에 렌더링하고 현재 시나리오를 반환한다."""
    scenario_service = service or ScenarioService()
    current = get_or_create_shared_scenario()

    with st.sidebar.expander("시나리오 관리", expanded=False):
        _render_notice()
        _render_current_summary(current)

        try:
            saved_scenarios = scenario_service.list_scenarios()
            store_error = None
        except ValueError as exc:
            saved_scenarios = []
            store_error = str(exc)
            st.error(f"시나리오 저장소를 읽을 수 없습니다. {exc}")

        st.divider()
        _render_save_form(
            scenario_service=scenario_service,
            current=current,
            saved_scenarios=saved_scenarios,
        )

        st.divider()
        if store_error is None:
            _render_load_controls(
                scenario_service=scenario_service,
                saved_scenarios=saved_scenarios,
            )
            st.divider()
            _render_delete_controls(
                scenario_service=scenario_service,
                saved_scenarios=saved_scenarios,
            )

    return get_or_create_shared_scenario()


def _render_current_summary(current: ScenarioContext) -> None:
    st.caption("현재 시나리오")
    st.write(
        {
            "scenario_id": current.scenario_id,
            "title": current.title,
            "region": current.region,
            "created_at": current.created_at.isoformat() if current.created_at else None,
        }
    )


def _render_save_form(
    *,
    scenario_service: ScenarioService,
    current: ScenarioContext,
    saved_scenarios: list[ScenarioContext],
) -> None:
    form_suffix = current.scenario_id or "new"
    with st.form(f"scenario_save_form_{form_suffix}"):
        scenario_id = st.text_input(
            "시나리오 ID",
            value=current.scenario_id,
            key=f"scenario_save_id_{form_suffix}",
        )
        title = st.text_input(
            "제목",
            value=current.title,
            key=f"scenario_save_title_{form_suffix}",
        )
        region = st.text_input(
            "지역",
            value=current.region,
            key=f"scenario_save_region_{form_suffix}",
        )
        created_by = st.text_input(
            "작성자",
            value=current.created_by,
            key=f"scenario_save_created_by_{form_suffix}",
        )
        description = st.text_area(
            "설명",
            value=current.description,
            height=90,
            key=f"scenario_save_description_{form_suffix}",
        )
        submitted = st.form_submit_button("현재 시나리오 저장", type="primary")

    if not submitted:
        return

    try:
        next_scenario = build_scenario_from_form(
            scenario_id=scenario_id,
            title=title,
            description=description,
            region=region,
            created_by=created_by,
            current=current,
        )
        overwrites_existing = scenario_exists(saved_scenarios, next_scenario.scenario_id)
        saved_state = scenario_service.save_scenario_state(
            SavedScenarioState(
                scenario=next_scenario,
                page_state=collect_current_page_state(),
            )
        )
        saved = saved_state.scenario
        changed_scenario_id = saved.scenario_id != current.scenario_id
        set_shared_scenario(saved, clear_results=changed_scenario_id)
    except (TypeError, ValueError) as exc:
        st.error(f"시나리오 저장 실패: {exc}")
        return

    if overwrites_existing:
        _set_notice(f"`{saved.scenario_id}` 저장본을 덮어썼습니다.", level="info")
    else:
        _set_notice(f"`{saved.scenario_id}` 시나리오를 저장했습니다.", level="success")
    st.rerun()


def _render_load_controls(
    *,
    scenario_service: ScenarioService,
    saved_scenarios: list[ScenarioContext],
) -> None:
    st.caption("불러오기")
    if not saved_scenarios:
        st.info("저장된 시나리오가 없습니다.")
        return

    selected_id = st.selectbox(
        "저장된 시나리오",
        options=[scenario.scenario_id for scenario in saved_scenarios],
        format_func={
            scenario.scenario_id: scenario_option_label(scenario)
            for scenario in saved_scenarios
        }.get,
        key="scenario_load_select",
    )
    if st.button("시나리오 불러오기", key="scenario_load_button", use_container_width=True):
        try:
            loaded_state = scenario_service.load_scenario_state(selected_id)
        except (KeyError, TypeError, ValueError) as exc:
            st.error(f"시나리오 불러오기 실패: {exc}")
            return

        set_shared_scenario(loaded_state.scenario, clear_results=False)
        apply_saved_page_state(loaded_state.page_state, clear_results=True)
        _set_notice(
            f"`{loaded_state.scenario.scenario_id}` 시나리오를 불러왔습니다.",
            level="success",
        )
        st.rerun()


def _render_delete_controls(
    *,
    scenario_service: ScenarioService,
    saved_scenarios: list[ScenarioContext],
) -> None:
    st.caption("삭제")
    if not saved_scenarios:
        st.caption("삭제할 저장 시나리오가 없습니다.")
        return

    selected_id = st.selectbox(
        "삭제할 시나리오",
        options=[scenario.scenario_id for scenario in saved_scenarios],
        format_func={
            scenario.scenario_id: scenario_option_label(scenario)
            for scenario in saved_scenarios
        }.get,
        key="scenario_delete_select",
    )
    confirmed = st.checkbox(
        "선택한 시나리오 삭제 확인",
        key=f"scenario_delete_confirm_{selected_id}",
    )
    if st.button(
        "선택한 시나리오 삭제",
        key="scenario_delete_button",
        disabled=not confirmed,
        use_container_width=True,
    ):
        try:
            deleted = scenario_service.delete_scenario(selected_id)
        except (TypeError, ValueError) as exc:
            st.error(f"시나리오 삭제 실패: {exc}")
            return

        if not deleted:
            st.warning(f"저장된 시나리오가 없습니다: {selected_id}")
            return

        current = get_or_create_shared_scenario()
        if current.scenario_id == selected_id:
            set_shared_scenario(build_default_scenario(), clear_results=True)
            apply_saved_page_state(ScenarioPageState(), clear_results=True)
        else:
            clear_scenario_bound_results()
        _set_notice(f"`{selected_id}` 시나리오를 삭제했습니다.", level="success")
        st.rerun()


def _set_notice(message: str, *, level: str) -> None:
    st.session_state[SCENARIO_NOTICE_KEY] = {"message": message, "level": level}


def _render_notice() -> None:
    notice = st.session_state.pop(SCENARIO_NOTICE_KEY, None)
    if not isinstance(notice, dict):
        return

    message = str(notice.get("message", ""))
    level = str(notice.get("level", "info"))
    if not message:
        return
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def _coerce_installations(value: object) -> list[InstallationPoint]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return []

    installations: list[InstallationPoint] = []
    for item in value:
        installation = _coerce_installation(item)
        if installation is not None:
            installations.append(installation)
    return installations


def _coerce_installation(value: object) -> InstallationPoint | None:
    if isinstance(value, InstallationPoint):
        return value
    if not isinstance(value, dict):
        return None

    installation_id = str(value.get("installation_id", "") or "").strip()
    if not installation_id:
        return None

    created_at = value.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = None

    return InstallationPoint(
        installation_id=installation_id,
        label=str(value.get("label", "") or ""),
        kind=str(value.get("kind") or "transmission_tower"),  # type: ignore[arg-type]
        latitude=_float_value(value.get("latitude"), 0.0),
        longitude=_float_value(value.get("longitude"), 0.0),
        mode=str(value.get("mode") or "new"),  # type: ignore[arg-type]
        elevation_m=_optional_float_value(value.get("elevation_m")),
        coordinate_system=str(value.get("coordinate_system") or "EPSG:4326"),
        elevation_source=str(value.get("elevation_source") or "not_queried"),
        capacity_mw=_optional_float_value(value.get("capacity_mw")),
        voltage_kv=_optional_float_value(value.get("voltage_kv")),
        notes=str(value.get("notes", "") or ""),
        created_at=created_at,
        metadata=dict(value.get("metadata") or {}),
    )


def _float_from_state(
    state: MutableMapping[str, Any],
    key: str,
    default: float,
) -> float:
    return _float_value(state.get(key, default), default)


def _int_from_state(
    state: MutableMapping[str, Any],
    key: str,
    default: int,
) -> int:
    value = state.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float_value(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_list_from_state(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
