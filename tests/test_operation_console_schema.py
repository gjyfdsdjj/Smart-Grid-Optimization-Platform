from datetime import datetime

from src.data.schemas import (
    FallbackInfo,
    LineStressSnapshot,
    NodeStressSnapshot,
    RoutePoint,
    RouteResult,
    ScenarioContext,
    StressAnalysisResult,
    SuggestedGridNode,
    TransmissionScenario,
    XaiGridExplanation,
)


def test_transmission_scenario_keeps_route_contract_and_line_ids() -> None:
    route = RouteResult(
        route_id="route-001",
        start_bus_id="PLANT_INCHEON",
        end_bus_id="TOWER_DAEGU",
        path_node_ids=["PLANT_INCHEON", "TOWER_SEOUL", "TOWER_DAEGU"],
        waypoints=[
            RoutePoint("PLANT_INCHEON", "인천 발전소", 37.45, 126.70),
            RoutePoint("TOWER_DAEGU", "대구 송전탑", 35.87, 128.60),
        ],
        total_distance_km=285.4,
        source="astar",
    )

    transmission = TransmissionScenario(
        scenario_route_id="tx-001",
        label="인천-대구 420MW 송전",
        start_node_id="PLANT_INCHEON",
        end_node_id="TOWER_DAEGU",
        requested_transfer_mw=420.0,
        route=route,
        path_node_ids=route.path_node_ids,
        used_line_ids=["GLINE_PLANT_INCHEON_TOWER_SEOUL", "GLINE_TOWER_SEOUL_TOWER_DAEGU"],
        status="active",
        source="astar",
    )

    assert transmission.route is route
    assert transmission.requested_transfer_mw == 420.0
    assert transmission.path_node_ids[-1] == "TOWER_DAEGU"
    assert transmission.used_line_ids == [
        "GLINE_PLANT_INCHEON_TOWER_SEOUL",
        "GLINE_TOWER_SEOUL_TOWER_DAEGU",
    ]
    assert transmission.status == "active"


def test_stress_analysis_result_groups_line_and_node_stress() -> None:
    scenario = ScenarioContext(
        scenario_id="scenario-grid-console",
        title="운영 콘솔 통합 테스트",
    )
    transmission = TransmissionScenario(
        scenario_route_id="tx-001",
        label="서울-대구 300MW 송전",
        start_node_id="TOWER_SEOUL",
        end_node_id="TOWER_DAEGU",
        requested_transfer_mw=300.0,
        used_line_ids=["GLINE_TOWER_SEOUL_TOWER_DAEGU"],
        status="active",
    )
    line_stress = LineStressSnapshot(
        line_id="GLINE_TOWER_SEOUL_TOWER_DAEGU",
        from_node_id="TOWER_SEOUL",
        to_node_id="TOWER_DAEGU",
        capacity_mw=500.0,
        base_flow_mw=120.0,
        scenario_flow_mw=300.0,
        predicted_flow_mw=70.0,
        total_flow_mw=490.0,
        utilization=0.98,
        risk_level="critical",
        contributing_scenario_ids=["tx-001"],
        shared_route_count=1,
        status="critical",
    )
    node_stress = NodeStressSnapshot(
        node_id="TOWER_DAEGU",
        node_name="대구 송전탑",
        node_type="transmission_tower",
        load_mw=210.0,
        connected_line_ids=["GLINE_TOWER_SEOUL_TOWER_DAEGU"],
        connected_scenario_ids=["tx-001"],
        risk_level="high",
    )

    result = StressAnalysisResult(
        scenario=scenario,
        created_at=datetime(2026, 5, 29, 12, 0),
        load_scale=1.15,
        transmission_scenarios=[transmission],
        line_stresses=[line_stress],
        node_stresses=[node_stress],
        bottleneck_line_ids=["GLINE_TOWER_SEOUL_TOWER_DAEGU"],
        critical_line_ids=["GLINE_TOWER_SEOUL_TOWER_DAEGU"],
    )

    assert result.scenario.scenario_id == "scenario-grid-console"
    assert result.fallback == FallbackInfo(enabled=False)
    assert result.load_scale == 1.15
    assert result.transmission_scenarios[0].scenario_route_id == "tx-001"
    assert result.line_stresses[0].contributing_scenario_ids == ["tx-001"]
    assert result.node_stresses[0].connected_scenario_ids == ["tx-001"]
    assert result.critical_line_ids == ["GLINE_TOWER_SEOUL_TOWER_DAEGU"]


def test_xai_explanation_and_suggested_node_hold_before_after_metrics() -> None:
    explanation = XaiGridExplanation(
        target_id="GLINE_TOWER_SEOUL_TOWER_DAEGU",
        target_type="line",
        title="서울-대구 선로 병목 설명",
        reason_summary="두 개 송전 시나리오가 같은 선로를 공유해 이용률이 임계치에 접근했습니다.",
        before_metrics={
            "utilization": 0.98,
            "critical_line_count": 1,
            "shared_route_count": 2,
        },
        after_metrics={
            "utilization": 0.71,
            "critical_line_count": 0,
            "shared_route_count": 1,
        },
        bottleneck_causes=["중복 경로", "예측 부하 증가"],
        recommended_actions=["우회 경로 적용", "신규 송전탑 후보 검토"],
        contributing_scenario_ids=["tx-001", "tx-002"],
        confidence=0.82,
    )
    suggested_node = SuggestedGridNode(
        suggested_node_id="SUGGESTED_TOWER_DAEGU_BYPASS",
        label="대구 우회 송전탑 후보",
        latitude=35.91,
        longitude=128.49,
        voltage_kv=345.0,
        capacity_mw=650.0,
        target_line_id="GLINE_TOWER_SEOUL_TOWER_DAEGU",
        relief_line_ids=["GLINE_TOWER_SEOUL_TOWER_DAEGU"],
        expected_utilization_delta=-0.27,
        reason="병목 선로 중간부를 우회해 부하를 분산합니다.",
    )

    assert explanation.target_type == "line"
    assert explanation.before_metrics["utilization"] > explanation.after_metrics["utilization"]
    assert explanation.contributing_scenario_ids == ["tx-001", "tx-002"]
    assert suggested_node.status == "proposed"
    assert suggested_node.coordinate_system == "EPSG:4326"
    assert suggested_node.elevation_source == "not_queried"
    assert suggested_node.capacity_mw == 650.0
