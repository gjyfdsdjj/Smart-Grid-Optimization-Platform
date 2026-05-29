from datetime import datetime

import pytest

from src.data.schemas import GridDataset, GridLine, GridNode, RouteResult, TransmissionScenario
from src.services.transmission_scenario_service import TransmissionScenarioService


def _node(
    node_id: str,
    name: str,
    *,
    latitude: float = 36.0,
    longitude: float = 127.0,
) -> GridNode:
    return GridNode(
        node_id=node_id,
        node_name=name,
        node_type="transmission_tower",
        latitude=latitude,
        longitude=longitude,
        voltage_kv=345.0,
    )


def _line(
    line_id: str,
    from_node_id: str,
    to_node_id: str,
    *,
    is_bidirectional: bool = True,
    status: str = "active",
) -> GridLine:
    return GridLine(
        line_id=line_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        voltage_kv=345.0,
        capacity_mw=500.0,
        reactance_pu=0.04,
        distance_km=20.0,
        is_bidirectional=is_bidirectional,
        status=status,
    )


def _dataset() -> GridDataset:
    return GridDataset(
        nodes=[
            _node("PLANT_INCHEON", "인천 발전소", latitude=37.45, longitude=126.70),
            _node("TOWER_SEOUL", "서울 송전탑", latitude=37.56, longitude=126.97),
            _node("TOWER_DAEGU", "대구 송전탑", latitude=35.87, longitude=128.60),
            _node("TOWER_BUSAN", "부산 송전탑", latitude=35.18, longitude=129.07),
        ],
        lines=[
            _line("GLINE_INCHEON_SEOUL", "PLANT_INCHEON", "TOWER_SEOUL"),
            _line("GLINE_DAEGU_SEOUL", "TOWER_DAEGU", "TOWER_SEOUL"),
            _line("GLINE_DAEGU_BUSAN", "TOWER_DAEGU", "TOWER_BUSAN", is_bidirectional=False),
            _line("GLINE_OFF", "TOWER_SEOUL", "TOWER_BUSAN", status="out_of_service"),
        ],
    )


def test_create_transmission_scenario_resolves_node_names_and_active_status() -> None:
    service = TransmissionScenarioService()
    created_at = datetime(2026, 5, 29, 14, 10, 12, 456)

    scenario = service.create_transmission_scenario(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=_dataset(),
        requested_transfer_mw=420.0,
        scenario_index=1,
        created_at=created_at,
    )

    assert scenario.scenario_route_id == "TX_001_PLANT_INCHEON_TOWER_DAEGU"
    assert scenario.label == "인천 발전소 -> 대구 송전탑 420MW 송전"
    assert scenario.start_node_name == "인천 발전소"
    assert scenario.end_node_name == "대구 송전탑"
    assert scenario.status == "active"
    assert scenario.created_at == datetime(2026, 5, 29, 14, 10, 12)
    assert scenario.warnings == []
    assert scenario.metadata["grid_node_count"] == 4


def test_create_transmission_scenario_keeps_invalid_selection_as_draft() -> None:
    service = TransmissionScenarioService()

    same_node = service.create_transmission_scenario(
        start_node_id="TOWER_SEOUL",
        end_node_id="TOWER_SEOUL",
        grid_dataset=_dataset(),
        requested_transfer_mw=300.0,
        scenario_index=2,
    )
    missing_node = service.create_transmission_scenario(
        start_node_id="TOWER_SEOUL",
        end_node_id="TOWER_UNKNOWN",
        grid_dataset=_dataset(),
        requested_transfer_mw=0.0,
        scenario_index=3,
    )

    assert same_node.status == "draft"
    assert any("시작 노드와 종료 노드가 같" in warning for warning in same_node.warnings)
    assert missing_node.status == "draft"
    assert any("GridDataset에서 찾을 수 없습니다" in warning for warning in missing_node.warnings)
    assert any("0MW보다 커야" in warning for warning in missing_node.warnings)


def test_attach_route_to_scenario_resolves_forward_and_reverse_grid_lines() -> None:
    service = TransmissionScenarioService()
    scenario = service.create_transmission_scenario(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=_dataset(),
        scenario_index=4,
    )
    route = RouteResult(
        route_id="astar-test",
        start_bus_id="PLANT_INCHEON",
        end_bus_id="TOWER_DAEGU",
        path_node_ids=["PLANT_INCHEON", "TOWER_SEOUL", "TOWER_DAEGU"],
        source="astar",
    )

    resolved = service.attach_route_to_scenario(
        scenario,
        route=route,
        grid_dataset=_dataset(),
    )

    assert resolved.route is route
    assert resolved.source == "astar"
    assert resolved.path_node_ids == ["PLANT_INCHEON", "TOWER_SEOUL", "TOWER_DAEGU"]
    assert resolved.used_line_ids == ["GLINE_INCHEON_SEOUL", "GLINE_DAEGU_SEOUL"]
    assert resolved.metadata["used_line_count"] == 2
    assert resolved.warnings == []


def test_resolve_used_line_ids_reports_missing_or_unusable_segments() -> None:
    service = TransmissionScenarioService()

    used_line_ids, warnings = service.resolve_used_line_ids(
        ["TOWER_SEOUL", "TOWER_BUSAN", "TOWER_DAEGU"],
        _dataset().lines,
    )

    assert used_line_ids == []
    assert any("TOWER_SEOUL -> TOWER_BUSAN" in warning for warning in warnings)
    assert any("TOWER_BUSAN -> TOWER_DAEGU" in warning for warning in warnings)


def test_build_route_between_nodes_uses_gridline_astar_path() -> None:
    service = TransmissionScenarioService()

    route = service.build_route_between_nodes(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=_dataset(),
        load_scale=1.0,
        route_id="route-test",
    )

    assert route.route_id == "route-test"
    assert route.source == "astar"
    assert route.start_bus_id == "PLANT_INCHEON"
    assert route.end_bus_id == "TOWER_DAEGU"
    assert route.path_node_ids == ["PLANT_INCHEON", "TOWER_SEOUL", "TOWER_DAEGU"]
    assert [point.point_id for point in route.waypoints] == route.path_node_ids
    assert route.total_distance_km == 40.0
    assert route.estimated_cost > 0.0
    assert "A* 자동 송전 경로" in route.summary


def test_build_route_between_nodes_respects_one_way_lines() -> None:
    service = TransmissionScenarioService()

    forward_route = service.build_route_between_nodes(
        start_node_id="TOWER_DAEGU",
        end_node_id="TOWER_BUSAN",
        grid_dataset=_dataset(),
    )

    assert forward_route.path_node_ids == ["TOWER_DAEGU", "TOWER_BUSAN"]

    with pytest.raises(ValueError, match="연결 경로"):
        service.build_route_between_nodes(
            start_node_id="TOWER_BUSAN",
            end_node_id="TOWER_DAEGU",
            grid_dataset=_dataset(),
        )


def test_route_can_be_attached_to_transmission_scenario_with_used_lines() -> None:
    service = TransmissionScenarioService()
    dataset = _dataset()
    route = service.build_route_between_nodes(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=dataset,
    )

    scenario = service.create_transmission_scenario(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=dataset,
        requested_transfer_mw=350.0,
        scenario_index=6,
        route=route,
        source="astar",
    )

    assert scenario.status == "active"
    assert scenario.route is route
    assert scenario.source == "astar"
    assert scenario.used_line_ids == ["GLINE_INCHEON_SEOUL", "GLINE_DAEGU_SEOUL"]
    assert scenario.metadata["route_source"] == "astar"


def test_active_filter_and_disable_transmission_scenario_are_non_destructive() -> None:
    service = TransmissionScenarioService()
    active = service.create_transmission_scenario(
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        grid_dataset=_dataset(),
        scenario_index=5,
    )
    draft = TransmissionScenario(
        scenario_route_id="TX_DRAFT",
        label="draft",
        start_node_id="",
        end_node_id="",
        status="draft",
    )

    disabled_list = service.disable_transmission_scenario(
        [active, draft],
        active.scenario_route_id,
    )

    assert active.status == "active"
    assert disabled_list[0].status == "disabled"
    assert disabled_list[1] is draft
    assert service.list_active_transmission_scenarios([active, draft]) == [active]
    assert service.list_active_transmission_scenarios(disabled_list) == []
