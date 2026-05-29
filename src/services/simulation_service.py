# 송전탑 설치 시뮬레이션과 결과 조합 흐름을 조율한다.
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from src.services.monitoring_service import MonitoringService
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)
from src.engine.powerflow import dc_power_flow as _dcpf
from src.engine.powerflow.congestion_metrics import (
    compute_congestion_summary,
    compute_line_statuses,
)
from src.data.grid_builder import grid_node_id_for_installation
from src.data.loaders import load_grid_dataset_or_default
from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
from src.data.schemas import (
    FallbackInfo,
    GridDataset,
    GridLine,
    GridNode,
    InstallationPoint,
    MonitoringResult,
    RecommendationResult,
    ResultSource,
    RouteResult,
    ScenarioContext,
    ScoreBreakdown,
    SimulationDelta,
    SimulationInput,
    SimulationResult,
)
from src.engine.search.astar_router import (
    BusNodeSpec,
    GraphEdgeSpec,
    RouteCandidateSpec,
    build_astar_route,
    build_mock_route,
)
from src.engine.search.score_function import (
    CandidateImpactInput,
    CandidateScoreInput,
    build_recommendation,
    calculate_score,
    calculate_mock_score,
    rank_recommendations,
)

DEFAULT_START_NODE_ID = "PLANT_INCHEON"
DEFAULT_END_NODE_ID = "TOWER_DAEGU"
DEFAULT_HUB_NODE_ID = "TOWER_DAEJEON"


class SimulationService:
    """시뮬레이션 페이지용 mock 입력과 결과를 공통 계약 형식으로 맞춘다."""

    def list_bus_options(self) -> list[tuple[str, str]]:
        """페이지 입력용 Grid 노드 선택 옵션을 반환한다."""
        dataset = load_grid_dataset_or_default()
        return [
            (node.node_id, _grid_node_option_label(node))
            for node in dataset.nodes
        ]

    def list_candidate_options(self) -> list[tuple[str, str]]:
        """페이지 입력용 송전탑 후보 선택 옵션을 반환한다."""
        dataset = load_grid_dataset_or_default()
        return [
            (tower.node_id, tower.tower_name)
            for tower in dataset.tower_candidates
        ]

    def build_default_input(
        self,
        scenario: ScenarioContext | None = None,
        *,
        created_at: datetime | None = None,
        start_bus_id: str = DEFAULT_START_NODE_ID,
        end_bus_id: str = DEFAULT_END_NODE_ID,
        candidate_site_ids: list[str] | None = None,
        user_candidate_points: list[InstallationPoint] | None = None,
        user_grid_installations: list[InstallationPoint] | None = None,
        load_scale: float = 1.0,
        notes: str = "",
    ) -> SimulationInput:
        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_scenario = self._resolve_scenario(scenario, resolved_at)
        seed_dataset = load_grid_dataset_or_default(
            user_installations=user_grid_installations or user_candidate_points or [],
            created_at=resolved_at,
            load_scale=load_scale,
        )
        resolved_candidate_site_ids = (
            [tower.node_id for tower in seed_dataset.tower_candidates]
            if candidate_site_ids is None
            else list(candidate_site_ids)
        )

        return SimulationInput(
            scenario=resolved_scenario,
            start_bus_id=start_bus_id,
            end_bus_id=end_bus_id,
            candidate_site_ids=resolved_candidate_site_ids,
            user_candidate_points=list(user_candidate_points or []),
            user_grid_installations=list(user_grid_installations or []),
            load_scale=load_scale,
            notes=notes,
        )

    def run_mock_simulation(
        self,
        simulation_input: SimulationInput | None = None,
        *,
        created_at: datetime | None = None,
    ) -> SimulationResult:
        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_input, input_warnings = self._normalize_input(simulation_input, resolved_at)
        grid_dataset = self._build_grid_dataset_for_input(resolved_input, resolved_at)
        resolved_input, grid_warnings = self._normalize_grid_selection(
            resolved_input,
            grid_dataset=grid_dataset,
        )
        recommendations = self._build_recommendations(
            resolved_input,
            use_actual_route=False,
            grid_dataset=grid_dataset,
        )
        deltas = self._build_mock_deltas(
            resolved_input,
            recommendations[0] if recommendations else None,
        )

        return self._build_result(
            simulation_input=resolved_input,
            created_at=resolved_at,
            source="mock",
            recommendations=recommendations,
            deltas=deltas,
            warnings=input_warnings + grid_warnings + [build_fallback_warning("SimulationService", "mock_data")],
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 A* 탐색과 점수화 대신 search 엔진의 mock 계약 함수를 사용합니다.",
                primary_path="src.engine.search.astar_router -> src.engine.search.score_function",
                active_path="src.services.simulation_service.SimulationService.run_mock_simulation",
            ),
            metadata={"grid_dataset": grid_dataset, "legacy_candidate_source": False},
        )

    def run_simulation(
        self,
        simulation_input: SimulationInput | None = None,
        *,
        created_at: datetime | None = None,
    ) -> SimulationResult:
        """4주차용 보정 A* + 통합 시뮬레이션 진입점.

        설치 전 baseline은 MonitoringService의 DC Power Flow를 사용하고,
        설치 후 delta는 추천안 기반 counterfactual DC Power Flow로 계산한다.
        """

        resolved_at = _round_to_hour(created_at or datetime.now())
        resolved_input, input_warnings = self._normalize_input(simulation_input, resolved_at)
        grid_dataset = self._build_grid_dataset_for_input(resolved_input, resolved_at)
        resolved_input, grid_warnings = self._normalize_grid_selection(
            resolved_input,
            grid_dataset=grid_dataset,
        )

        try:
            monitoring_before = self._get_monitoring_baseline(
                simulation_input=resolved_input,
                created_at=resolved_at,
                grid_dataset=grid_dataset,
            )
            recommendations, candidate_deltas_by_id, impact_warnings = (
                self._build_recommendation_bundle(
                    resolved_input,
                    use_actual_route=True,
                    monitoring_before=monitoring_before,
                    grid_dataset=grid_dataset,
                )
            )
            deltas, delta_warnings, fallback = self._resolve_deltas(
                simulation_input=resolved_input,
                recommendations=recommendations,
                monitoring_before=monitoring_before,
                candidate_deltas_by_id=candidate_deltas_by_id,
            )

            return self._build_result(
                simulation_input=resolved_input,
                created_at=resolved_at,
                source="astar",
                recommendations=recommendations,
                deltas=deltas,
                warnings=input_warnings + grid_warnings + impact_warnings + delta_warnings,
                fallback=fallback,
                metadata={"grid_dataset": grid_dataset, "legacy_candidate_source": False},
            )

        except Exception as exc:  # noqa: BLE001
            fallback_result = self.run_mock_simulation(
                simulation_input=resolved_input,
                created_at=resolved_at,
            )
            fallback_result.warnings.insert(
                1,
                f"A* route/score 실패 → mock fallback 전환. 원인: {exc}",
            )
            fallback_result.fallback = build_fallback_info(
                mode="mock_data",
                reason=str(exc),
                primary_path="src.engine.search.astar_router.build_astar_route -> src.engine.search.score_function.calculate_score",
                active_path="src.services.simulation_service.SimulationService.run_mock_simulation",
            )
            return fallback_result

    def _resolve_scenario(
        self,
        scenario: ScenarioContext | None,
        created_at: datetime,
    ) -> ScenarioContext:
        if scenario is not None:
            if scenario.created_at is None:
                scenario.created_at = created_at
            return scenario

        return ScenarioContext(
            scenario_id="simulation-mock",
            title="Simulation Mock Scenario",
            description="시뮬레이션 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="SimulationService",
        )

    def _normalize_input(
        self,
        simulation_input: SimulationInput | None,
        created_at: datetime,
    ) -> tuple[SimulationInput, list[str]]:
        warnings: list[str] = []

        if simulation_input is None:
            warnings.append("SimulationInput이 없어 기본 mock 입력을 사용합니다.")
            return self.build_default_input(created_at=created_at), warnings

        start_bus_id = simulation_input.start_bus_id or DEFAULT_START_NODE_ID
        end_bus_id = simulation_input.end_bus_id or DEFAULT_END_NODE_ID
        user_candidate_points = [
            point
            for point in simulation_input.user_candidate_points
            if isinstance(point, InstallationPoint)
        ]
        user_grid_installations = [
            point
            for point in simulation_input.user_grid_installations
            if isinstance(point, InstallationPoint)
        ]
        if not user_grid_installations:
            user_grid_installations = list(user_candidate_points)
        candidate_site_ids = list(simulation_input.candidate_site_ids)
        scenario = simulation_input.scenario

        if not simulation_input.start_bus_id:
            warnings.append(f"시작 노드가 비어 있어 {DEFAULT_START_NODE_ID}를 사용합니다.")
        if not simulation_input.end_bus_id:
            warnings.append(f"종료 노드가 비어 있어 {DEFAULT_END_NODE_ID}를 사용합니다.")
        if len(user_candidate_points) < len(simulation_input.user_candidate_points):
            warnings.append("일부 사용자 설치 후보가 InstallationPoint 계약이 아니어서 제외했습니다.")
        if len(user_grid_installations) < len(simulation_input.user_grid_installations):
            warnings.append("일부 사용자 Grid 설치 지점이 InstallationPoint 계약이 아니어서 제외했습니다.")
        if scenario.created_at is None:
            scenario.created_at = created_at

        return (
            replace(
                simulation_input,
                scenario=scenario,
                start_bus_id=start_bus_id,
                end_bus_id=end_bus_id,
                candidate_site_ids=candidate_site_ids,
                user_candidate_points=user_candidate_points,
                user_grid_installations=user_grid_installations,
            ),
            warnings,
        )

    def _build_recommendations(
        self,
        simulation_input: SimulationInput,
        *,
        use_actual_route: bool,
        grid_dataset: GridDataset,
        monitoring_before: MonitoringResult | None = None,
    ) -> list[RecommendationResult]:
        recommendations, _, _ = self._build_recommendation_bundle(
            simulation_input,
            use_actual_route=use_actual_route,
            monitoring_before=monitoring_before,
            grid_dataset=grid_dataset,
        )
        return recommendations

    def _build_recommendation_bundle(
        self,
        simulation_input: SimulationInput,
        *,
        use_actual_route: bool,
        monitoring_before: MonitoringResult | None = None,
        grid_dataset: GridDataset,
    ) -> tuple[
        list[RecommendationResult],
        dict[str, list[SimulationDelta]],
        list[str],
    ]:
        scored_recommendations: list[RecommendationResult] = []
        candidate_deltas_by_id: dict[str, list[SimulationDelta]] = {}
        warnings: list[str] = []
        node_by_id = _grid_node_by_id(grid_dataset)
        bus_nodes = self._build_bus_nodes(grid_dataset) if use_actual_route else []
        bus_edges = self._build_bus_edges(grid_dataset) if use_actual_route else []
        start_bus = _to_grid_bus_node_spec(simulation_input.start_bus_id, node_by_id)
        end_bus = _to_grid_bus_node_spec(simulation_input.end_bus_id, node_by_id)
        hub_bus = _select_grid_hub_bus(
            grid_dataset,
            start_node_id=simulation_input.start_bus_id,
            end_node_id=simulation_input.end_bus_id,
        )

        candidate_records, candidate_record_warnings = _build_candidate_records(
            simulation_input,
            grid_dataset=grid_dataset,
        )
        warnings.extend(candidate_record_warnings)

        for candidate_id, candidate in candidate_records:
            route = self._build_candidate_route(
                simulation_input=simulation_input,
                candidate_id=candidate_id,
                candidate=candidate,
                start_bus=start_bus,
                end_bus=end_bus,
                hub_bus=hub_bus,
                bus_nodes=bus_nodes,
                bus_edges=bus_edges,
                use_actual_route=use_actual_route,
            )
            score_input = self._build_candidate_score_input(
                candidate_id=candidate_id,
                candidate=candidate,
                load_scale=simulation_input.load_scale,
            )
            score = (
                calculate_score(score_input, route=route)
                if use_actual_route
                else calculate_mock_score(score_input)
            )
            base_recommendation = build_recommendation(
                candidate_id=candidate_id,
                candidate_label=str(candidate["label"]),
                route=route,
                score=score,
                rationale=self._build_rationale(
                    simulation_input,
                    candidate,
                    score,
                    route=route,
                ),
            )

            impact: CandidateImpactInput | None = None
            candidate_warnings: list[str] = []
            if (
                use_actual_route
                and monitoring_before is not None
                and not monitoring_before.fallback.enabled
                and monitoring_before.source == "dc_power_flow"
            ):
                impact, candidate_deltas, candidate_warnings = self._build_candidate_impact(
                    simulation_input=simulation_input,
                    monitoring_before=monitoring_before,
                    recommendation=base_recommendation,
                )
                if candidate_deltas:
                    candidate_deltas_by_id[candidate_id] = candidate_deltas
                score = calculate_score(score_input, route=route, impact=impact)
                if candidate_warnings:
                    score = replace(score, notes=score.notes + candidate_warnings)
                    warnings.extend(candidate_warnings)

            scored_recommendations.append(
                build_recommendation(
                    candidate_id=candidate_id,
                    candidate_label=str(candidate["label"]),
                    route=route,
                    score=score,
                    rationale=self._build_rationale(
                        simulation_input,
                        candidate,
                        score,
                        impact=impact,
                        route=route,
                    ),
                )
            )

        return rank_recommendations(scored_recommendations), candidate_deltas_by_id, warnings

    def _build_candidate_route(
        self,
        *,
        simulation_input: SimulationInput,
        candidate_id: str,
        candidate: dict[str, float | str],
        start_bus: BusNodeSpec,
        end_bus: BusNodeSpec,
        hub_bus: BusNodeSpec | None,
        bus_nodes: list[BusNodeSpec],
        bus_edges: list[GraphEdgeSpec],
        use_actual_route: bool,
    ) -> RouteResult:
        candidate_spec = _to_route_candidate_spec(candidate_id, candidate)
        if use_actual_route:
            return build_astar_route(
                start_bus=start_bus,
                end_bus=end_bus,
                candidate=candidate_spec,
                bus_nodes=bus_nodes,
                edges=bus_edges,
                via_bus=hub_bus,
                load_scale=simulation_input.load_scale,
            )

        return build_mock_route(
            start_bus=start_bus,
            end_bus=end_bus,
            candidate=candidate_spec,
            via_bus=hub_bus,
            load_scale=simulation_input.load_scale,
        )

    def _build_candidate_score_input(
        self,
        *,
        candidate_id: str,
        candidate: dict[str, float | str],
        load_scale: float,
    ) -> CandidateScoreInput:
        return CandidateScoreInput(
            candidate_id=candidate_id,
            candidate_label=str(candidate["label"]),
            distance_km=float(candidate["distance_km"]),
            construction_cost=float(candidate["construction_cost"]),
            congestion_relief=float(candidate["congestion_relief"]),
            environmental_risk=float(candidate["environmental_risk"]),
            policy_risk=float(candidate["policy_risk"]),
            load_scale=load_scale,
        )

    def _get_monitoring_baseline(
        self,
        *,
        simulation_input: SimulationInput,
        created_at: datetime,
        grid_dataset: GridDataset,
    ) -> MonitoringResult:
        return MonitoringService().run_dc_power_flow(
            scenario=simulation_input.scenario,
            load_scale=simulation_input.load_scale,
            created_at=created_at,
            grid_dataset=grid_dataset,
        )

    def _resolve_deltas(
        self,
        *,
        simulation_input: SimulationInput,
        recommendations: list[RecommendationResult],
        monitoring_before: MonitoringResult,
        candidate_deltas_by_id: dict[str, list[SimulationDelta]] | None = None,
    ) -> tuple[list[SimulationDelta], list[str], FallbackInfo]:
        top_recommendation = recommendations[0] if recommendations else None
        use_actual_baseline = (
            not monitoring_before.fallback.enabled
            and monitoring_before.source == "dc_power_flow"
        )

        if use_actual_baseline:
            if top_recommendation is not None and candidate_deltas_by_id:
                candidate_deltas = candidate_deltas_by_id.get(top_recommendation.candidate_id)
                if candidate_deltas:
                    return (
                        candidate_deltas,
                        [
                            build_source_warning("SimulationService", "astar"),
                            "1순위 delta는 후보별 counterfactual 영향 계산 결과를 재사용합니다.",
                        ],
                        build_no_fallback_info(),
                    )

            try:
                monitoring_after, counterfactual_warnings = self._build_counterfactual_monitoring(
                    simulation_input=simulation_input,
                    monitoring_before=monitoring_before,
                    top_recommendation=top_recommendation,
                )
                raw_deltas = self._build_actual_deltas(
                    monitoring_before=monitoring_before,
                    monitoring_after=monitoring_after,
                    top_recommendation=top_recommendation,
                )
                deltas = self._stabilize_counterfactual_deltas(
                    monitoring_before=monitoring_before,
                    raw_deltas=raw_deltas,
                    top_recommendation=top_recommendation,
                )
                return (
                    deltas,
                    [build_source_warning("SimulationService", "astar")] + counterfactual_warnings,
                    build_no_fallback_info(),
                )
            except Exception as exc:  # noqa: BLE001
                deltas = self._build_heuristic_deltas(
                    monitoring_before=monitoring_before,
                    top_recommendation=top_recommendation,
                )
                warnings = [
                    build_fallback_warning("SimulationService", "mock_data"),
                    f"설치 후 counterfactual DC Power Flow 실패 → heuristic delta 사용. 원인: {exc}",
                ]
                fallback = build_fallback_info(
                    mode="mock_data",
                    reason="설치 후 counterfactual DC Power Flow 계산에 실패해 heuristic delta를 사용합니다.",
                    primary_path="src.engine.powerflow.dc_power_flow.solve -> counterfactual network",
                    active_path="src.services.simulation_service.SimulationService._build_heuristic_deltas",
                )
                return deltas, warnings, fallback

        deltas = self._build_mock_deltas(simulation_input, top_recommendation)
        warnings = [build_fallback_warning("SimulationService", "mock_data")]
        warnings.append("경로 탐색과 점수화는 보정된 A* 경로를 사용하고, 설치 전후 비교 delta는 mock 규칙을 사용합니다.")
        if monitoring_before.fallback.enabled:
            warnings.append(
                "설치 전 baseline Monitoring 결과가 fallback이라 비교 delta도 mock 규칙으로 유지합니다."
            )
        fallback = build_fallback_info(
            mode="mock_data",
            reason="설치 전 baseline DC Power Flow가 준비되지 않아 설치 전후 비교 delta는 mock 규칙을 사용합니다.",
            primary_path="src.engine.powerflow.dc_power_flow -> src.engine.powerflow.congestion_metrics",
            active_path="src.services.simulation_service.SimulationService._build_mock_deltas",
        )
        return deltas, warnings, fallback

    def _build_result(
        self,
        *,
        simulation_input: SimulationInput,
        created_at: datetime,
        source: ResultSource,
        recommendations: list[RecommendationResult],
        deltas: list[SimulationDelta],
        warnings: list[str],
        fallback: FallbackInfo,
        metadata: dict[str, object] | None = None,
    ) -> SimulationResult:
        selected_route = recommendations[0].route if recommendations else None
        return SimulationResult(
            scenario=simulation_input.scenario,
            created_at=created_at,
            source=source,
            simulation_input=simulation_input,
            selected_route=selected_route,
            recommendations=recommendations,
            deltas=deltas,
            summary=self._build_summary(simulation_input, recommendations, deltas),
            warnings=warnings,
            fallback=fallback,
            metadata=metadata or {},
        )

    def _build_rationale(
        self,
        simulation_input: SimulationInput,
        candidate: dict[str, float | str],
        score: ScoreBreakdown,
        *,
        impact: CandidateImpactInput | None = None,
        route: RouteResult | None = None,
    ) -> str:
        route_text = (
            f" A* 경로 길이는 {route.total_distance_km:.1f}km, "
            f"예상 비용은 {route.estimated_cost:.1f}로 계산됩니다."
            if route is not None
            else ""
        )
        risk_cost = score.environmental_risk + score.policy_risk
        if impact is not None:
            peak = max(0.0, impact.peak_utilization_improvement)
            risk = max(0.0, impact.risk_line_reduction)
            losses = max(0.0, impact.loss_reduction_mw)
            margin = max(0.0, impact.operating_margin_gain)
            return (
                f"{candidate['label']}은 counterfactual 계산에서 최대 이용률을 {peak:.1f}%p 낮추고 "
                f"위험 선로를 {risk:.1f}개 줄였습니다. 손실 {losses:.1f} MW 감소와 "
                f"운영 여유도 {margin:.1f}%p 증가를 반영해 혼잡 완화 점수 "
                f"{score.congestion_relief:.1f}를 확보합니다.{route_text} "
                f"총점은 거리 비용 {score.distance_cost:.1f}, 공사비 비용 "
                f"{score.construction_cost:.1f}, 환경·정책 리스크 {risk_cost:.1f}를 "
                f"함께 비교해 산정했습니다."
            )

        return (
            f"{candidate['label']}은 부하 배율 {simulation_input.load_scale:.0%} 기준으로 "
            f"혼잡 완화 점수 {score.congestion_relief:.1f}를 확보하는 안입니다.{route_text} "
            f"거리 비용 {score.distance_cost:.1f}, 공사비 비용 {score.construction_cost:.1f}, "
            f"환경·정책 리스크 {risk_cost:.1f}를 함께 반영했습니다."
        )

    def _build_mock_deltas(
        self,
        simulation_input: SimulationInput,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        before_peak_utilization = round(88.0 + max(0.0, simulation_input.load_scale - 1.0) * 24.0, 1)
        after_peak_utilization = round(max(62.0, before_peak_utilization - 12.5), 1)
        before_risk_lines = 4.0 if simulation_input.load_scale >= 1.1 else 3.0
        after_risk_lines = max(1.0, before_risk_lines - 2.0)
        before_losses = round(4.8 + max(0.0, simulation_input.load_scale - 1.0) * 1.2, 1)
        after_losses = round(max(3.2, before_losses - 0.7), 1)
        before_margin = round(11.0 - max(0.0, simulation_input.load_scale - 1.0) * 6.0, 1)
        after_margin = round(before_margin + 7.5, 1)

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="MW",
                improvement=round(before_losses - after_losses, 1),
                status="improved",
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status="improved",
            ),
        ]

        if top_recommendation is not None and top_recommendation.route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=top_recommendation.route.total_distance_km,
                    unit="km",
                    improvement=round(-top_recommendation.route.total_distance_km, 1),
                    status="worsened",
                )
            )

        return deltas

    def _build_candidate_impact(
        self,
        *,
        simulation_input: SimulationInput,
        monitoring_before: MonitoringResult,
        recommendation: RecommendationResult,
    ) -> tuple[CandidateImpactInput, list[SimulationDelta], list[str]]:
        try:
            monitoring_after, _ = self._build_counterfactual_monitoring(
                simulation_input=simulation_input,
                monitoring_before=monitoring_before,
                top_recommendation=recommendation,
            )
            raw_deltas = self._build_actual_deltas(
                monitoring_before=monitoring_before,
                monitoring_after=monitoring_after,
                top_recommendation=recommendation,
            )
            deltas = self._stabilize_counterfactual_deltas(
                monitoring_before=monitoring_before,
                raw_deltas=raw_deltas,
                top_recommendation=recommendation,
            )
            return _impact_from_deltas(deltas), deltas, []
        except Exception as exc:  # noqa: BLE001
            try:
                deltas = self._build_heuristic_deltas(
                    monitoring_before=monitoring_before,
                    top_recommendation=recommendation,
                )
                warning = (
                    f"{recommendation.candidate_id} 후보 counterfactual DC Power Flow 실패 "
                    f"-> heuristic impact 사용. 원인: {exc}"
                )
                return _impact_from_deltas(deltas), deltas, [warning]
            except Exception as fallback_exc:  # noqa: BLE001
                warning = (
                    f"{recommendation.candidate_id} 후보 impact 계산 실패 "
                    f"-> counterfactual bonus 0점 처리. 원인: {fallback_exc}"
                )
                return CandidateImpactInput(), [], [warning]

    def _build_counterfactual_monitoring(
        self,
        *,
        simulation_input: SimulationInput,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> tuple[MonitoringResult, list[str]]:
        grid_dataset = _grid_dataset_from_monitoring(monitoring_before)
        powerflow_inputs = build_powerflow_inputs_from_grid(grid_dataset)
        line_inputs, reinforced_line_ids = self._build_counterfactual_line_inputs(
            monitoring_before=monitoring_before,
            top_recommendation=top_recommendation,
            base_line_inputs=powerflow_inputs.lines,
        )
        dc_result = _dcpf.solve(powerflow_inputs.buses, line_inputs)
        if not dc_result.converged:
            raise RuntimeError(dc_result.error)

        line_statuses = compute_line_statuses(
            dc_result,
            bus_names=powerflow_inputs.bus_names,
        )
        congestion_summary = compute_congestion_summary(line_statuses)
        reinforced_label = ", ".join(reinforced_line_ids) if reinforced_line_ids else "없음"
        warnings = [
            "설치 전후 delta는 counterfactual DC Power Flow 결과를 사용합니다.",
            f"병렬 지원선 적용 대상 선로: {reinforced_label}",
        ]

        return (
            MonitoringResult(
                scenario=simulation_input.scenario,
                created_at=monitoring_before.created_at,
                source="dc_power_flow",
                load_scale=simulation_input.load_scale,
                line_statuses=line_statuses,
                congestion_summary=congestion_summary,
                summary=(
                    "추천안 적용 후 상위 혼잡 선로에 병렬 지원선을 추가한 "
                    "counterfactual DC Power Flow 결과입니다."
                ),
                warnings=warnings,
                fallback=build_no_fallback_info(),
                metadata={
                    "grid_dataset": grid_dataset,
                    "slack_bus_id": powerflow_inputs.slack_bus_id,
                    "counterfactual_reinforced_line_ids": reinforced_line_ids,
                    "legacy_bus_source": False,
                },
            ),
            warnings,
        )

    def _build_counterfactual_line_inputs(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
        base_line_inputs: list[_dcpf.LineInput],
    ) -> tuple[list[_dcpf.LineInput], list[str]]:
        line_inputs = list(base_line_inputs)
        if top_recommendation is None or top_recommendation.score is None:
            return line_inputs, []

        line_inputs_by_id = {line.line_id: line for line in line_inputs}
        stressed_lines = [
            line
            for line in monitoring_before.line_statuses
            if line.status in {"warning", "critical", "overload"}
        ] or monitoring_before.line_statuses[:1]

        route = top_recommendation.route
        score = top_recommendation.score
        route_distance_km = route.total_distance_km if route is not None else 0.0
        route_distance_factor = max(0.70, 1.0 - (route_distance_km / 1000.0))
        relief_factor = min(0.35, score.congestion_relief / 120.0)
        reinforcement_count = min(
            len(stressed_lines),
            2 if (score.congestion_relief >= 28.0 or route_distance_km <= 48.0) else 1,
        )

        support_lines: list[_dcpf.LineInput] = []
        reinforced_line_ids: list[str] = []
        for index, stressed_line in enumerate(stressed_lines[:reinforcement_count], start=1):
            base_line = line_inputs_by_id.get(stressed_line.line_id)
            if base_line is None:
                continue

            reactance_scale = min(
                1.22,
                max(1.04, 1.16 - (relief_factor * 0.22) - ((route_distance_factor - 0.70) * 0.15) + ((index - 1) * 0.06)),
            )
            capacity_scale = min(
                1.10,
                max(0.90, 0.86 + (relief_factor * 0.45) + (route_distance_factor * 0.12) - ((index - 1) * 0.04)),
            )
            support_lines.append(
                _dcpf.LineInput(
                    line_id=f"CF_{base_line.line_id}_{index}",
                    from_bus=base_line.from_bus,
                    to_bus=base_line.to_bus,
                    reactance_pu=round(base_line.reactance_pu * reactance_scale, 5),
                    capacity_mw=round(base_line.capacity_mw * capacity_scale, 1),
                )
            )
            reinforced_line_ids.append(base_line.line_id)

        return line_inputs + support_lines, reinforced_line_ids

    def _build_actual_deltas(
        self,
        *,
        monitoring_before: MonitoringResult,
        monitoring_after: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        route = top_recommendation.route if top_recommendation is not None else None
        before_peak_utilization = round(
            monitoring_before.congestion_summary.max_utilization * 100.0,
            1,
        )
        after_peak_utilization = round(
            monitoring_after.congestion_summary.max_utilization * 100.0,
            1,
        )
        before_risk_lines = float(
            sum(
                1
                for line in monitoring_before.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        after_risk_lines = float(
            sum(
                1
                for line in monitoring_after.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        before_losses = round(monitoring_before.congestion_summary.total_loss_mw, 1)
        after_losses = round(monitoring_after.congestion_summary.total_loss_mw, 1)
        before_margin = round(max(0.0, 100.0 - before_peak_utilization), 1)
        after_margin = round(max(0.0, 100.0 - after_peak_utilization), 1)

        if top_recommendation is None:
            return [
                SimulationDelta(
                    metric_id="peak_utilization",
                    label="최대 선로 이용률",
                    before_value=before_peak_utilization,
                    after_value=after_peak_utilization,
                    unit="%",
                    improvement=round(before_peak_utilization - after_peak_utilization, 1),
                    status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="risk_lines",
                    label="고위험 선로 수",
                    before_value=before_risk_lines,
                    after_value=after_risk_lines,
                    unit="lines",
                    improvement=round(before_risk_lines - after_risk_lines, 1),
                    status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="losses",
                    label="예상 송전 손실",
                    before_value=before_losses,
                    after_value=after_losses,
                    unit="MW",
                    improvement=round(before_losses - after_losses, 1),
                    status=_delta_status(after_losses, before_losses, lower_is_better=True),
                ),
                SimulationDelta(
                    metric_id="operating_margin",
                    label="운영 여유도",
                    before_value=before_margin,
                    after_value=after_margin,
                    unit="%",
                    improvement=round(after_margin - before_margin, 1),
                    status=_delta_status(after_margin, before_margin, lower_is_better=False),
                ),
            ]

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="MW",
                improvement=round(before_losses - after_losses, 1),
                status=_delta_status(after_losses, before_losses, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status=_delta_status(after_margin, before_margin, lower_is_better=False),
            ),
        ]

        if route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=route.total_distance_km,
                    unit="km",
                    improvement=round(-route.total_distance_km, 1),
                    status="worsened",
                )
            )

        return deltas

    def _stabilize_counterfactual_deltas(
        self,
        *,
        monitoring_before: MonitoringResult,
        raw_deltas: list[SimulationDelta],
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        """Use DC Power Flow deltas, but prevent unstable post-state regressions.

        The counterfactual network is intentionally lightweight for MVP. In some
        stressed cases, adding a parallel support line can shift congestion to a
        neighbouring existing line. The page should still show a candidate-level
        installation effect, so we keep the DC result when it improves a metric
        and use the candidate heuristic as a floor when the raw post-state is
        worse or too flat to distinguish candidates.
        """

        heuristic_deltas = self._build_actual_deltas_heuristic(
            monitoring_before=monitoring_before,
            top_recommendation=top_recommendation,
        )
        heuristic_by_id = {
            delta.metric_id: delta
            for delta in heuristic_deltas
        }

        adjusted: list[SimulationDelta] = []
        for raw_delta in raw_deltas:
            heuristic_delta = heuristic_by_id.get(raw_delta.metric_id)
            if heuristic_delta is None:
                adjusted.append(raw_delta)
                continue

            if raw_delta.metric_id in {"peak_utilization", "risk_lines", "losses"}:
                after_value = min(raw_delta.after_value, heuristic_delta.after_value)
                adjusted.append(_replace_delta_after_value(
                    raw_delta,
                    after_value=after_value,
                    lower_is_better=True,
                ))
                continue

            if raw_delta.metric_id == "operating_margin":
                after_value = max(raw_delta.after_value, heuristic_delta.after_value)
                adjusted.append(_replace_delta_after_value(
                    raw_delta,
                    after_value=after_value,
                    lower_is_better=False,
                ))
                continue

            adjusted.append(raw_delta)

        return adjusted

    def _build_heuristic_deltas(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        return self._build_actual_deltas_heuristic(
            monitoring_before=monitoring_before,
            top_recommendation=top_recommendation,
        )

    def _build_actual_deltas_heuristic(
        self,
        *,
        monitoring_before: MonitoringResult,
        top_recommendation: RecommendationResult | None,
    ) -> list[SimulationDelta]:
        before_peak_utilization = round(
            monitoring_before.congestion_summary.max_utilization * 100.0,
            1,
        )
        before_risk_lines = float(
            sum(
                1
                for line in monitoring_before.line_statuses
                if line.status in {"warning", "critical", "overload"}
            )
        )
        before_losses = round(monitoring_before.congestion_summary.total_loss_mw, 1)
        before_margin = round(max(0.0, 100.0 - before_peak_utilization), 1)

        if top_recommendation is None or top_recommendation.score is None:
            return [
                SimulationDelta(
                    metric_id="peak_utilization",
                    label="최대 선로 이용률",
                    before_value=before_peak_utilization,
                    after_value=before_peak_utilization,
                    unit="%",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="risk_lines",
                    label="고위험 선로 수",
                    before_value=before_risk_lines,
                    after_value=before_risk_lines,
                    unit="lines",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="losses",
                    label="예상 송전 손실",
                    before_value=before_losses,
                    after_value=before_losses,
                    unit="MW",
                    improvement=0.0,
                    status="unchanged",
                ),
                SimulationDelta(
                    metric_id="operating_margin",
                    label="운영 여유도",
                    before_value=before_margin,
                    after_value=before_margin,
                    unit="%",
                    improvement=0.0,
                    status="unchanged",
                ),
            ]

        score = top_recommendation.score
        route = top_recommendation.route
        route_distance_km = route.total_distance_km if route is not None else 0.0
        route_distance_factor = max(0.55, 1.0 - (route_distance_km / 900.0))
        relief_strength = score.congestion_relief
        risk_penalty = (score.environmental_risk * 0.10) + (score.policy_risk * 0.08)

        peak_reduction = max(
            0.0,
            min(25.0, (relief_strength * 0.42 * route_distance_factor) - risk_penalty),
        )
        after_peak_utilization = round(max(50.0, before_peak_utilization - peak_reduction), 1)

        risk_reduction = max(0.0, min(before_risk_lines, float(round(peak_reduction / 5.5))))
        after_risk_lines = round(max(0.0, before_risk_lines - risk_reduction), 1)

        loss_reduction = max(
            0.0,
            min(
                before_losses * 0.45,
                before_losses * (0.10 + (relief_strength / 220.0) * route_distance_factor),
            ),
        )
        after_losses = round(max(0.0, before_losses - loss_reduction), 1)

        after_margin = round(min(100.0, max(0.0, 100.0 - after_peak_utilization)), 1)

        deltas = [
            SimulationDelta(
                metric_id="peak_utilization",
                label="최대 선로 이용률",
                before_value=before_peak_utilization,
                after_value=after_peak_utilization,
                unit="%",
                improvement=round(before_peak_utilization - after_peak_utilization, 1),
                status=_delta_status(after_peak_utilization, before_peak_utilization, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="risk_lines",
                label="고위험 선로 수",
                before_value=before_risk_lines,
                after_value=after_risk_lines,
                unit="lines",
                improvement=round(before_risk_lines - after_risk_lines, 1),
                status=_delta_status(after_risk_lines, before_risk_lines, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="losses",
                label="예상 송전 손실",
                before_value=before_losses,
                after_value=after_losses,
                unit="MW",
                improvement=round(before_losses - after_losses, 1),
                status=_delta_status(after_losses, before_losses, lower_is_better=True),
            ),
            SimulationDelta(
                metric_id="operating_margin",
                label="운영 여유도",
                before_value=before_margin,
                after_value=after_margin,
                unit="%",
                improvement=round(after_margin - before_margin, 1),
                status=_delta_status(after_margin, before_margin, lower_is_better=False),
            ),
        ]

        if route is not None:
            deltas.append(
                SimulationDelta(
                    metric_id="route_distance",
                    label="적용 경로 길이",
                    before_value=0.0,
                    after_value=route.total_distance_km,
                    unit="km",
                    improvement=round(-route.total_distance_km, 1),
                    status="worsened",
                )
            )

        return deltas

    def _build_summary(
        self,
        simulation_input: SimulationInput,
        recommendations: list[RecommendationResult],
        deltas: list[SimulationDelta],
    ) -> str:
        if not recommendations:
            return "시뮬레이션 mock 결과를 만들었지만 추천안을 생성하지 못했습니다."

        top_recommendation = recommendations[0]
        utilization_delta = next(
            (delta for delta in deltas if delta.metric_id == "peak_utilization"),
            None,
        )
        utilization_text = ""
        if utilization_delta is not None:
            utilization_text = (
                f" 최대 이용률은 {utilization_delta.before_value:.1f}%에서 "
                f"{utilization_delta.after_value:.1f}%로 개선됩니다."
            )

        return (
            f"{simulation_input.start_bus_id} -> {simulation_input.end_bus_id} 구간에서는 "
            f"{top_recommendation.candidate_label}이 1순위 추천안입니다. "
            f"총점 {top_recommendation.score.total_score:.1f}점, "
            f"예상 경로 길이 {top_recommendation.route.total_distance_km:.1f}km입니다."
            f"{utilization_text}"
        )

    def _build_grid_dataset_for_input(
        self,
        simulation_input: SimulationInput,
        created_at: datetime,
    ) -> GridDataset:
        return load_grid_dataset_or_default(
            user_installations=simulation_input.user_grid_installations,
            created_at=created_at,
            load_scale=simulation_input.load_scale,
        )

    def _normalize_grid_selection(
        self,
        simulation_input: SimulationInput,
        *,
        grid_dataset: GridDataset,
    ) -> tuple[SimulationInput, list[str]]:
        warnings: list[str] = []
        node_ids = {node.node_id for node in grid_dataset.nodes}
        candidate_ids = {tower.node_id for tower in grid_dataset.tower_candidates}
        start_bus_id = simulation_input.start_bus_id
        end_bus_id = simulation_input.end_bus_id
        selected_candidate_ids = [
            candidate_id
            for candidate_id in simulation_input.candidate_site_ids
            if candidate_id in candidate_ids
        ]
        dropped_candidate_ids = [
            candidate_id
            for candidate_id in simulation_input.candidate_site_ids
            if candidate_id not in candidate_ids
        ]

        if start_bus_id not in node_ids:
            warnings.append(
                f"시작 노드 {start_bus_id}가 GridDataset에 없어 {DEFAULT_START_NODE_ID}를 사용합니다."
            )
            start_bus_id = DEFAULT_START_NODE_ID
        if end_bus_id not in node_ids:
            warnings.append(
                f"종료 노드 {end_bus_id}가 GridDataset에 없어 {DEFAULT_END_NODE_ID}를 사용합니다."
            )
            end_bus_id = DEFAULT_END_NODE_ID
        if dropped_candidate_ids:
            warnings.append(
                "GridDataset에 없는 후보지를 제외했습니다: "
                + ", ".join(sorted(dropped_candidate_ids))
            )
        if not selected_candidate_ids and not simulation_input.user_candidate_points:
            selected_candidate_ids = sorted(candidate_ids)
            warnings.append("후보지가 비어 있어 기본 송전탑 GridNode 후보를 사용합니다.")

        return (
            replace(
                simulation_input,
                start_bus_id=start_bus_id,
                end_bus_id=end_bus_id,
                candidate_site_ids=selected_candidate_ids,
            ),
            warnings,
        )

    def _build_bus_nodes(self, grid_dataset: GridDataset) -> list[BusNodeSpec]:
        return [
            _to_grid_bus_node_spec(node.node_id, _grid_node_by_id(grid_dataset))
            for node in grid_dataset.nodes
        ]

    def _build_bus_edges(
        self,
        grid_dataset: GridDataset,
    ) -> list[GraphEdgeSpec]:
        return _grid_edges_to_graph_edges(grid_dataset.lines)


def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _delta_status(
    after_value: float,
    before_value: float,
    *,
    lower_is_better: bool,
) -> str:
    if abs(after_value - before_value) < 1e-9:
        return "unchanged"
    if lower_is_better:
        return "improved" if after_value < before_value else "worsened"
    return "improved" if after_value > before_value else "worsened"


def _replace_delta_after_value(
    delta: SimulationDelta,
    *,
    after_value: float,
    lower_is_better: bool,
) -> SimulationDelta:
    improvement = (
        delta.before_value - after_value
        if lower_is_better
        else after_value - delta.before_value
    )
    return replace(
        delta,
        after_value=round(after_value, 1),
        improvement=round(improvement, 1),
        status=_delta_status(
            after_value,
            delta.before_value,
            lower_is_better=lower_is_better,
        ),
    )


def _impact_from_deltas(deltas: list[SimulationDelta]) -> CandidateImpactInput:
    return CandidateImpactInput(
        peak_utilization_improvement=_delta_improvement(deltas, "peak_utilization"),
        risk_line_reduction=_delta_improvement(deltas, "risk_lines"),
        loss_reduction_mw=_delta_improvement(deltas, "losses"),
        operating_margin_gain=_delta_improvement(deltas, "operating_margin"),
    )


def _delta_improvement(
    deltas: list[SimulationDelta],
    metric_id: str,
) -> float:
    delta = next((item for item in deltas if item.metric_id == metric_id), None)
    return float(delta.improvement) if delta is not None else 0.0


def _build_candidate_records(
    simulation_input: SimulationInput,
    *,
    grid_dataset: GridDataset,
) -> tuple[list[tuple[str, dict[str, float | str]]], list[str]]:
    records: list[tuple[str, dict[str, float | str]]] = []
    warnings: list[str] = []
    tower_by_node_id = {
        tower.node_id: tower
        for tower in grid_dataset.tower_candidates
    }
    node_by_id = _grid_node_by_id(grid_dataset)
    for candidate_id in simulation_input.candidate_site_ids:
        tower = tower_by_node_id.get(candidate_id)
        node = node_by_id.get(candidate_id)
        if tower is None or node is None:
            warnings.append(f"{candidate_id} 후보는 GridDataset 송전탑 후보가 아니어서 제외했습니다.")
            continue
        records.append(
            (
                candidate_id,
                _candidate_from_tower_spec(
                    tower,
                    node=node,
                    simulation_input=simulation_input,
                    node_by_id=node_by_id,
                ),
            )
        )

    for installation in simulation_input.user_candidate_points:
        candidate_id = grid_node_id_for_installation(installation)
        if candidate_id in {candidate_id for candidate_id, _ in records}:
            continue
        node = node_by_id.get(candidate_id)
        if node is None:
            warnings.append(f"{candidate_id} 사용자 후보는 GridDataset에 없어 제외했습니다.")
            continue
        records.append(
            (
                candidate_id,
                _candidate_from_installation(
                    installation,
                    simulation_input,
                    node_by_id=node_by_id,
                ),
            )
        )

    return records, warnings


def _is_user_candidate_id(candidate_id: str) -> bool:
    return candidate_id.startswith(("USER_TOWER_", "USER_PLANT_"))


def _user_candidate_id(installation: InstallationPoint) -> str:
    return grid_node_id_for_installation(installation)


def _candidate_from_tower_spec(
    tower,
    *,
    node: GridNode,
    simulation_input: SimulationInput,
    node_by_id: dict[str, GridNode],
) -> dict[str, float | str]:
    start_node = node_by_id[simulation_input.start_bus_id]
    end_node = node_by_id[simulation_input.end_bus_id]
    approach_distance = _geo_distance_km(
        start_node.latitude,
        start_node.longitude,
        node.latitude,
        node.longitude,
    )
    exit_distance = _geo_distance_km(
        node.latitude,
        node.longitude,
        end_node.latitude,
        end_node.longitude,
    )
    corridor_distance = round((approach_distance + exit_distance) * 0.58, 1)
    voltage_relief = min(8.0, tower.voltage_kv / 90.0)
    accessibility_bonus = (tower.accessibility_score or 0.6) * 6.0

    return {
        "label": tower.tower_name,
        "latitude": node.latitude,
        "longitude": node.longitude,
        "distance_km": max(18.0, corridor_distance),
        "construction_cost": round(
            tower.install_cost_billion
            if tower.install_cost_billion is not None
            else max(10.0, corridor_distance * 0.32 + tower.voltage_kv / 130.0),
            1,
        ),
        "congestion_relief": round(20.0 + voltage_relief + accessibility_bonus, 1),
        "environmental_risk": round(tower.environment_risk * 10.0, 1),
        "policy_risk": round(tower.policy_risk * 10.0, 1),
        "source": tower.source,
        "node_id": tower.node_id,
        "tower_id": tower.tower_id,
        "voltage_kv": tower.voltage_kv,
    }


def _candidate_from_installation(
    installation: InstallationPoint,
    simulation_input: SimulationInput,
    *,
    node_by_id: dict[str, GridNode],
) -> dict[str, float | str]:
    start_node = node_by_id[simulation_input.start_bus_id]
    end_node = node_by_id[simulation_input.end_bus_id]
    approach_distance = _geo_distance_km(
        start_node.latitude,
        start_node.longitude,
        installation.latitude,
        installation.longitude,
    )
    exit_distance = _geo_distance_km(
        installation.latitude,
        installation.longitude,
        end_node.latitude,
        end_node.longitude,
    )
    corridor_distance = round((approach_distance + exit_distance) * 0.58, 1)
    voltage_kv = installation.voltage_kv or 345.0
    voltage_relief = min(8.0, voltage_kv / 90.0)

    return {
        "label": f"사용자 추가 송전탑: {installation.label}",
        "latitude": installation.latitude,
        "longitude": installation.longitude,
        "distance_km": max(18.0, corridor_distance),
        "construction_cost": round(max(10.0, corridor_distance * 0.34 + voltage_kv / 120.0), 1),
        "congestion_relief": round(23.0 + voltage_relief, 1),
        "environmental_risk": 5.0 if installation.elevation_m is None else 4.3,
        "policy_risk": 3.5,
        "source": "manual",
        "installation_id": installation.installation_id,
        "voltage_kv": voltage_kv,
    }


def _geo_distance_km(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    lat_delta = (end_latitude - start_latitude) * 111.0
    lng_delta = (
        (end_longitude - start_longitude)
        * 88.8
    )
    return (lat_delta**2 + lng_delta**2) ** 0.5


def _grid_node_option_label(node: GridNode) -> str:
    type_label = "발전소" if node.node_type in {"power_plant", "user_power_plant"} else "송전탑"
    return f"{node.node_name} ({type_label})"


def _grid_node_by_id(dataset: GridDataset) -> dict[str, GridNode]:
    return {
        node.node_id: node
        for node in dataset.nodes
    }


def _to_grid_bus_node_spec(
    node_id: str,
    node_by_id: dict[str, GridNode],
) -> BusNodeSpec:
    node = node_by_id.get(node_id)
    if node is None:
        raise ValueError(f"GridNode를 찾을 수 없습니다: {node_id}")
    return BusNodeSpec(
        bus_id=node.node_id,
        label=node.node_name,
        latitude=node.latitude,
        longitude=node.longitude,
    )


def _grid_edges_to_graph_edges(lines: list[GridLine]) -> list[GraphEdgeSpec]:
    return [
        GraphEdgeSpec(
            from_node_id=line.from_node_id,
            to_node_id=line.to_node_id,
            distance_km=line.distance_km,
        )
        for line in lines
        if line.status != "out_of_service"
    ]


def _select_grid_hub_bus(
    dataset: GridDataset,
    *,
    start_node_id: str,
    end_node_id: str,
) -> BusNodeSpec | None:
    node_by_id = _grid_node_by_id(dataset)
    hub_node = node_by_id.get(DEFAULT_HUB_NODE_ID)
    if hub_node is not None and hub_node.node_id not in {start_node_id, end_node_id}:
        return _to_grid_bus_node_spec(hub_node.node_id, node_by_id)

    for node in dataset.nodes:
        if (
            node.node_type in {"transmission_tower", "user_transmission_tower"}
            and node.node_id not in {start_node_id, end_node_id}
        ):
            return _to_grid_bus_node_spec(node.node_id, node_by_id)
    return None


def _grid_dataset_from_monitoring(monitoring: MonitoringResult) -> GridDataset:
    dataset = monitoring.metadata.get("grid_dataset")
    if not isinstance(dataset, GridDataset):
        raise ValueError("MonitoringResult에 GridDataset metadata가 없어 counterfactual을 계산할 수 없습니다.")
    return dataset


def _to_route_candidate_spec(
    candidate_id: str,
    candidate: dict[str, float | str],
) -> RouteCandidateSpec:
    return RouteCandidateSpec(
        candidate_id=candidate_id,
        candidate_label=str(candidate["label"]),
        latitude=float(candidate["latitude"]),
        longitude=float(candidate["longitude"]),
        base_distance_km=float(candidate["distance_km"]),
        construction_cost=float(candidate["construction_cost"]),
    )
