from datetime import datetime

from src.data.schemas import (
    CongestionSummary,
    GridDataset,
    GridLine,
    GridNode,
    GridPowerProfile,
    LineStatus,
    MonitoringResult,
    ScenarioContext,
    TransmissionScenario,
)
from src.engine.stress.route_stress_analyzer import analyze_route_stress


def _node(
    node_id: str,
    name: str,
    *,
    node_type: str = "transmission_tower",
    base_load_mw: float = 0.0,
) -> GridNode:
    return GridNode(
        node_id=node_id,
        node_name=name,
        node_type=node_type,
        latitude=36.0,
        longitude=127.0,
        voltage_kv=345.0,
        base_load_mw=base_load_mw,
    )


def _line(
    line_id: str,
    from_node_id: str,
    to_node_id: str,
    *,
    capacity_mw: float = 500.0,
    is_bidirectional: bool = True,
    status: str = "active",
) -> GridLine:
    return GridLine(
        line_id=line_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        voltage_kv=345.0,
        capacity_mw=capacity_mw,
        reactance_pu=0.04,
        distance_km=25.0,
        is_bidirectional=is_bidirectional,
        status=status,
    )


def _dataset() -> GridDataset:
    return GridDataset(
        nodes=[
            _node("PLANT_A", "A 발전소", node_type="power_plant"),
            _node("TOWER_B", "B 송전탑", base_load_mw=80.0),
            _node("TOWER_C", "C 송전탑", base_load_mw=120.0),
            _node("TOWER_D", "D 송전탑", base_load_mw=40.0),
        ],
        lines=[
            _line("LINE_AB", "PLANT_A", "TOWER_B", capacity_mw=500.0),
            _line("LINE_CB", "TOWER_C", "TOWER_B", capacity_mw=500.0),
            _line("LINE_CD", "TOWER_C", "TOWER_D", capacity_mw=200.0, is_bidirectional=False),
            _line("LINE_OFF", "TOWER_B", "TOWER_D", status="out_of_service"),
        ],
        power_profiles=[
            GridPowerProfile(
                node_id="PLANT_A",
                generation_mw=300.0,
                load_mw=20.0,
                net_injection_mw=280.0,
            ),
            GridPowerProfile(
                node_id="TOWER_B",
                generation_mw=0.0,
                load_mw=90.0,
                net_injection_mw=-90.0,
            ),
        ],
    )


def _scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="stress-test",
        title="stress test",
        created_at=datetime(2026, 5, 29, 16, 0),
    )


def test_no_transmission_scenarios_uses_base_flow_scaled_by_capacity() -> None:
    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[],
        load_scale=1.2,
        created_at=datetime(2026, 5, 29, 16, 0),
    )

    line_ab = next(line for line in result.line_stresses if line.line_id == "LINE_AB")
    line_cd = next(line for line in result.line_stresses if line.line_id == "LINE_CD")

    assert result.metadata["active_scenario_count"] == 0
    assert line_ab.base_flow_mw == 210.0
    assert line_ab.scenario_flow_mw == 0.0
    assert line_ab.utilization == 0.42
    assert line_cd.base_flow_mw == 84.0
    assert "활성 송전 시나리오 없음" in result.summary
    assert "LINE_OFF" not in {line.line_id for line in result.line_stresses}
    assert result.metadata["base_flow_source"] == "capacity_ratio"
    assert result.metadata["base_flow_source_by_line"]["LINE_AB"] == "capacity_ratio"
    assert any("capacity_ratio" in warning for warning in result.warnings)


def test_active_scenarios_accumulate_shared_route_flow_and_ignore_disabled() -> None:
    active_a = TransmissionScenario(
        scenario_route_id="TX_001",
        label="A-B",
        start_node_id="PLANT_A",
        end_node_id="TOWER_B",
        requested_transfer_mw=120.0,
        used_line_ids=["LINE_AB"],
        status="active",
    )
    active_b = TransmissionScenario(
        scenario_route_id="TX_002",
        label="A-B second",
        start_node_id="PLANT_A",
        end_node_id="TOWER_B",
        requested_transfer_mw=80.0,
        used_line_ids=["LINE_AB"],
        status="active",
    )
    disabled = TransmissionScenario(
        scenario_route_id="TX_DISABLED",
        label="disabled",
        start_node_id="PLANT_A",
        end_node_id="TOWER_B",
        requested_transfer_mw=300.0,
        used_line_ids=["LINE_AB"],
        status="disabled",
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[active_a, active_b, disabled],
        load_scale=1.0,
    )
    line_ab = next(line for line in result.line_stresses if line.line_id == "LINE_AB")

    assert result.transmission_scenarios == [active_a, active_b]
    assert line_ab.scenario_flow_mw == 200.0
    assert line_ab.shared_route_count == 2
    assert line_ab.contributing_scenario_ids == ["TX_001", "TX_002"]
    assert line_ab.total_flow_mw == 375.0
    assert line_ab.status == "warning"
    assert result.metadata["shared_route_line_ids"] == ["LINE_AB"]
    assert result.metadata["bottleneck_rule"] == "status>=warning or shared_route_count>=2"


def test_empty_used_lines_are_recovered_from_path_node_ids() -> None:
    recovered = TransmissionScenario(
        scenario_route_id="TX_RECOVERED",
        label="recover",
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        requested_transfer_mw=110.0,
        path_node_ids=["PLANT_A", "TOWER_B", "TOWER_C"],
        status="active",
    )
    missing = TransmissionScenario(
        scenario_route_id="TX_MISSING",
        label="missing",
        start_node_id="TOWER_D",
        end_node_id="TOWER_C",
        requested_transfer_mw=60.0,
        path_node_ids=["TOWER_D", "TOWER_C"],
        status="active",
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[recovered, missing],
        load_scale=1.0,
    )
    line_ab = next(line for line in result.line_stresses if line.line_id == "LINE_AB")
    line_cb = next(line for line in result.line_stresses if line.line_id == "LINE_CB")

    assert line_ab.scenario_flow_mw == 110.0
    assert line_cb.scenario_flow_mw == 110.0
    assert any("TX_MISSING" in warning for warning in result.warnings)
    assert any("stress 누적에서 제외" in warning for warning in result.warnings)


def test_over_capacity_line_is_reported_as_overload_and_critical() -> None:
    overloaded = TransmissionScenario(
        scenario_route_id="TX_OVER",
        label="over",
        start_node_id="TOWER_C",
        end_node_id="TOWER_D",
        requested_transfer_mw=160.0,
        used_line_ids=["LINE_CD"],
        status="active",
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[overloaded],
        load_scale=1.0,
    )
    line_cd = next(line for line in result.line_stresses if line.line_id == "LINE_CD")

    assert line_cd.total_flow_mw == 230.0
    assert line_cd.utilization == 1.15
    assert line_cd.status == "overload"
    assert line_cd.risk_level == "critical"
    assert result.critical_line_ids == ["LINE_CD"]
    assert result.bottleneck_line_ids == ["LINE_CD"]
    assert result.metadata["max_utilization_line_id"] == "LINE_CD"
    assert result.metadata["top_utilization_line_ids"][0] == "LINE_CD"


def test_shared_route_is_bottleneck_even_when_utilization_is_normal() -> None:
    shared_a = TransmissionScenario(
        scenario_route_id="TX_SHARED_A",
        label="shared a",
        start_node_id="PLANT_A",
        end_node_id="TOWER_B",
        requested_transfer_mw=10.0,
        used_line_ids=["LINE_AB"],
        status="active",
    )
    shared_b = TransmissionScenario(
        scenario_route_id="TX_SHARED_B",
        label="shared b",
        start_node_id="PLANT_A",
        end_node_id="TOWER_B",
        requested_transfer_mw=10.0,
        used_line_ids=["LINE_AB"],
        status="active",
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[shared_a, shared_b],
        load_scale=1.0,
    )
    line_ab = next(line for line in result.line_stresses if line.line_id == "LINE_AB")

    assert line_ab.status == "normal"
    assert line_ab.shared_route_count == 2
    assert result.warning_line_ids == []
    assert result.critical_line_ids == []
    assert result.metadata["shared_route_line_ids"] == ["LINE_AB"]
    assert result.bottleneck_line_ids == ["LINE_AB"]


def test_node_stress_uses_profiles_and_connected_scenarios() -> None:
    active = TransmissionScenario(
        scenario_route_id="TX_NODE",
        label="node",
        start_node_id="PLANT_A",
        end_node_id="TOWER_C",
        requested_transfer_mw=110.0,
        path_node_ids=["PLANT_A", "TOWER_B", "TOWER_C"],
        status="active",
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[active],
        load_scale=1.5,
    )
    plant = next(node for node in result.node_stresses if node.node_id == "PLANT_A")
    tower_b = next(node for node in result.node_stresses if node.node_id == "TOWER_B")
    tower_d = next(node for node in result.node_stresses if node.node_id == "TOWER_D")

    assert plant.generation_mw == 300.0
    assert plant.load_mw == 20.0
    assert tower_b.load_mw == 90.0
    assert tower_b.connected_scenario_ids == ["TX_NODE"]
    assert "LINE_AB" in tower_b.connected_line_ids
    assert tower_b.metadata["connected_line_count"] == 2
    assert tower_b.metadata["connected_scenario_count"] == 1
    assert tower_b.metadata["max_connected_line_id"] in {"LINE_AB", "LINE_CB"}
    assert tower_b.metadata["max_connected_utilization"] > 0.0
    assert tower_d.load_mw == 60.0


def test_monitoring_result_overrides_capacity_ratio_base_flow() -> None:
    monitoring = MonitoringResult(
        scenario=_scenario(),
        created_at=datetime(2026, 5, 29, 16, 0),
        source="dc_power_flow",
        load_scale=1.0,
        line_statuses=[
            LineStatus(
                line_id="LINE_AB",
                from_bus="PLANT_A",
                to_bus="TOWER_B",
                from_bus_name="A 발전소",
                to_bus_name="B 송전탑",
                flow_mw=-260.0,
                capacity_mw=500.0,
                utilization=0.52,
                status="normal",
                risk_level="low",
                loss_mw=0.5,
            )
        ],
        congestion_summary=CongestionSummary(
            total_lines=1,
            normal_count=1,
            warning_count=0,
            critical_count=0,
            overload_count=0,
            avg_utilization=0.52,
            total_loss_mw=0.5,
            max_utilization=0.52,
            max_utilization_line_id="LINE_AB",
        ),
    )

    result = analyze_route_stress(
        scenario=_scenario(),
        grid_dataset=_dataset(),
        transmission_scenarios=[],
        load_scale=1.5,
        monitoring_result=monitoring,
    )
    line_ab = next(line for line in result.line_stresses if line.line_id == "LINE_AB")
    line_cb = next(line for line in result.line_stresses if line.line_id == "LINE_CB")

    assert line_ab.base_flow_mw == 260.0
    assert line_cb.base_flow_mw == 262.5
    assert line_ab.metadata["base_flow_source"] == "monitoring_result"
    assert line_cb.metadata["base_flow_source"] == "capacity_ratio"
    assert result.metadata["base_flow_source"] == "mixed"
    assert result.metadata["base_flow_source_by_line"]["LINE_AB"] == "monitoring_result"
    assert "LINE_CB" in result.metadata["capacity_ratio_base_flow_line_ids"]
    assert any("DC Power Flow 결과에 없는 선로" in warning for warning in result.warnings)
