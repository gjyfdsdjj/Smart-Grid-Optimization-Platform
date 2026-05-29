# Monitoring, Simulation, Prediction 결과를 지도/표 공통 overlay 계약으로 변환한다.
from __future__ import annotations

from datetime import datetime

from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.schemas import (
    FallbackInfo,
    GridDataset,
    GridLine,
    GridNode,
    GridPowerProfile,
    LineStatus,
    MapOverlayLine,
    MapOverlayPoint,
    MapOverlayResult,
    MapOverlayRoute,
    MonitoringResult,
    PredictionResult,
    RecommendationResult,
    ResultSource,
    RiskLine,
    RiskLevel,
    RoutePoint,
    ScenarioContext,
    SimulationResult,
)
from src.services.result_metadata import (
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)


_ELEVATION_WARNING = (
    "MapOverlayService는 현재 고도(z/elevation_m) 미조회 상태로 2.5D 좌표를 반환합니다."
)


class MapOverlayService:
    """서비스 결과를 지도 UI가 아닌 공통 overlay 데이터로 변환한다."""

    def build_landing_overlay(
        self,
        *,
        scenario: ScenarioContext,
        created_at: datetime,
        points: list[MapOverlayPoint],
        lines: list[MapOverlayLine] | None = None,
        routes: list[MapOverlayRoute] | None = None,
        warnings: list[str] | None = None,
        map_capability: MapCapability | None = None,
    ) -> MapOverlayResult:
        capability = _resolve_map_capability(map_capability)
        route_list = list(routes or [])
        line_list = list(lines or [])
        point_list = list(points)
        return _build_overlay_result(
            scenario=scenario,
            created_at=created_at,
            source="manual",
            points=point_list,
            lines=line_list,
            routes=route_list,
            summary=(
                f"Landing overlay: 운영 지점 {len(point_list)}개와 "
                f"송전망 {len(line_list)}개, 추천 경로 {len(route_list)}개를 제공합니다."
            ),
            source_warnings=[],
            local_warnings=list(warnings or []),
            source_fallback=build_no_fallback_info(),
            map_capability=capability,
        )

    def build_grid_overlay(
        self,
        dataset: GridDataset,
        *,
        scenario: ScenarioContext,
        created_at: datetime | None = None,
        map_capability: MapCapability | None = None,
    ) -> MapOverlayResult:
        capability = _resolve_map_capability(map_capability)
        resolved_at = created_at or dataset.created_at or datetime.now()
        profile_by_node_id = {
            profile.node_id: profile
            for profile in dataset.power_profiles
        }
        points_by_node_id = {
            node.node_id: _grid_node_overlay_point(
                node,
                profile=profile_by_node_id.get(node.node_id),
            )
            for node in dataset.nodes
        }
        warnings: list[str] = []
        lines: list[MapOverlayLine] = []

        for grid_line in dataset.lines:
            from_point = points_by_node_id.get(grid_line.from_node_id)
            to_point = points_by_node_id.get(grid_line.to_node_id)
            if from_point is None or to_point is None:
                warnings.append(
                    f"{grid_line.line_id}는 존재하지 않는 GridNode를 참조해 grid overlay에서 제외했습니다."
                )
                continue
            lines.append(_grid_line_overlay(grid_line, from_point, to_point))

        overlay = _build_overlay_result(
            scenario=scenario,
            created_at=resolved_at,
            source="manual",
            points=list(points_by_node_id.values()),
            lines=lines,
            routes=[],
            summary=(
                f"Grid overlay: GridNode {len(points_by_node_id)}개와 "
                f"GridLine {len(lines)}개를 제공합니다."
            ),
            source_warnings=dataset.warnings,
            local_warnings=warnings,
            source_fallback=dataset.fallback,
            map_capability=capability,
        )
        overlay.metadata.update(
            {
                "grid_source": dataset.source,
                "grid_stage": dataset.metadata.get("grid_stage", ""),
                "line_generation_status": dataset.metadata.get("line_generation_status", ""),
                "profile_count": len(dataset.power_profiles),
                "slack_node_ids": [
                    profile.node_id
                    for profile in dataset.power_profiles
                    if profile.is_slack_candidate
                ],
            }
        )
        return overlay

    def build_monitoring_overlay(
        self,
        result: MonitoringResult,
        *,
        map_capability: MapCapability | None = None,
    ) -> MapOverlayResult:
        capability = _resolve_map_capability(map_capability)
        points_by_id: dict[str, MapOverlayPoint] = {}
        lines: list[MapOverlayLine] = []
        warnings: list[str] = []
        grid_points_by_node_id = _grid_points_by_node_id_from_metadata(result.metadata)

        for line in result.line_statuses:
            from_point = self._monitoring_bus_point(
                line.from_bus,
                fallback_label=line.from_bus_name,
                source=result.source,
                warnings=warnings,
                grid_points_by_node_id=grid_points_by_node_id,
            )
            to_point = self._monitoring_bus_point(
                line.to_bus,
                fallback_label=line.to_bus_name,
                source=result.source,
                warnings=warnings,
                grid_points_by_node_id=grid_points_by_node_id,
            )
            if from_point is None or to_point is None:
                continue

            points_by_id.setdefault(from_point.overlay_id, from_point)
            points_by_id.setdefault(to_point.overlay_id, to_point)
            lines.append(_monitoring_line_overlay(line, from_point, to_point, result.source))

        return _build_overlay_result(
            scenario=result.scenario,
            created_at=result.created_at,
            source=result.source,
            points=list(points_by_id.values()),
            lines=lines,
            routes=[],
            summary=(
                f"Monitoring overlay: {len(lines)}개 선로와 "
                f"{len(points_by_id)}개 GridNode 지점을 제공합니다."
            ),
            source_warnings=result.warnings,
            local_warnings=warnings,
            source_fallback=result.fallback,
            map_capability=capability,
        )

    def build_simulation_overlay(
        self,
        result: SimulationResult,
        *,
        baseline_monitoring: MonitoringResult | None = None,
        map_capability: MapCapability | None = None,
    ) -> MapOverlayResult:
        capability = _resolve_map_capability(map_capability)
        points_by_id: dict[str, MapOverlayPoint] = {}
        lines: list[MapOverlayLine] = []
        routes: list[MapOverlayRoute] = []
        warnings: list[str] = []

        if baseline_monitoring is not None:
            grid_points_by_node_id = _grid_points_by_node_id_from_metadata(baseline_monitoring.metadata)
            for line in baseline_monitoring.line_statuses:
                from_point = self._monitoring_bus_point(
                    line.from_bus,
                    fallback_label=line.from_bus_name,
                    source=baseline_monitoring.source,
                    warnings=warnings,
                    grid_points_by_node_id=grid_points_by_node_id,
                )
                to_point = self._monitoring_bus_point(
                    line.to_bus,
                    fallback_label=line.to_bus_name,
                    source=baseline_monitoring.source,
                    warnings=warnings,
                    grid_points_by_node_id=grid_points_by_node_id,
                )
                if from_point is None or to_point is None:
                    continue

                points_by_id.setdefault(from_point.overlay_id, from_point)
                points_by_id.setdefault(to_point.overlay_id, to_point)
                lines.append(
                    _monitoring_line_overlay(
                        line,
                        from_point,
                        to_point,
                        baseline_monitoring.source,
                    )
                )

        for recommendation in result.recommendations:
            candidate_point = self._candidate_point_from_recommendation(
                recommendation,
                source=result.source,
            )
            if candidate_point is not None:
                points_by_id[candidate_point.overlay_id] = candidate_point

            route = _route_overlay_from_recommendation(recommendation, result.source)
            if route is not None:
                routes.append(route)

        source_fallback = result.fallback
        source_warnings = list(result.warnings)
        if baseline_monitoring is not None:
            source_warnings.extend(baseline_monitoring.warnings)
            if not source_fallback.enabled and baseline_monitoring.fallback.enabled:
                source_fallback = baseline_monitoring.fallback

        return _build_overlay_result(
            scenario=result.scenario,
            created_at=result.created_at,
            source=result.source,
            points=list(points_by_id.values()),
            lines=lines,
            routes=routes,
            summary=(
                f"Simulation overlay: 후보지 {len(result.recommendations)}개, "
                f"기존 선로 {len(lines)}개, 추천 경로 {len(routes)}개를 제공합니다."
            ),
            source_warnings=source_warnings,
            local_warnings=warnings,
            source_fallback=source_fallback,
            map_capability=capability,
        )

    def build_prediction_overlay(
        self,
        result: PredictionResult,
        *,
        selected_node_ids: list[str] | None = None,
        map_capability: MapCapability | None = None,
    ) -> MapOverlayResult:
        capability = _resolve_map_capability(map_capability)
        scenario = result.scenario or ScenarioContext(
            scenario_id=result.scenario_id,
            created_at=result.created_at,
            created_by="PredictionService",
        )
        points_by_id: dict[str, MapOverlayPoint] = {}
        lines: list[MapOverlayLine] = []
        warnings: list[str] = []
        grid_points_by_node_id = _grid_points_by_node_id_from_metadata(result.metadata)
        selected_ids = list(dict.fromkeys(selected_node_ids or []))

        for risk_line in result.risk_lines:
            from_point = self._simulation_bus_point(
                risk_line.from_bus,
                fallback_label=risk_line.from_bus_name,
                source=result.source,
                warnings=warnings,
                grid_points_by_node_id=grid_points_by_node_id,
            )
            to_point = self._simulation_bus_point(
                risk_line.to_bus,
                fallback_label=risk_line.to_bus_name,
                source=result.source,
                warnings=warnings,
                grid_points_by_node_id=grid_points_by_node_id,
            )
            if from_point is None or to_point is None:
                continue

            points_by_id.setdefault(from_point.overlay_id, from_point)
            points_by_id.setdefault(to_point.overlay_id, to_point)
            lines.append(_prediction_risk_line_overlay(risk_line, from_point, to_point, result.source))

        for node_id in selected_ids:
            selected_point = self._simulation_bus_point(
                node_id,
                fallback_label=node_id,
                source=result.source,
                warnings=warnings,
                grid_points_by_node_id=grid_points_by_node_id,
            )
            if selected_point is None:
                continue
            points_by_id[selected_point.overlay_id] = _prediction_selected_node_point(
                selected_point,
                node_id=node_id,
            )

        return _build_overlay_result(
            scenario=scenario,
            created_at=result.created_at,
            source=result.source,
            points=list(points_by_id.values()),
            lines=lines,
            routes=[],
            summary=(
                f"Prediction overlay: 예측 위험 선로 {len(lines)}개와 "
                f"선택 노드 {sum(1 for point in points_by_id.values() if point.metadata.get('selected_for') == 'prediction_chart')}개, "
                f"전체 {len(points_by_id)}개 GridNode 지점을 제공합니다."
            ),
            source_warnings=result.warnings,
            local_warnings=warnings,
            source_fallback=result.fallback,
            map_capability=capability,
        )

    def _monitoring_bus_point(
        self,
        bus_id: str,
        *,
        fallback_label: str,
        source: ResultSource,
        warnings: list[str],
        grid_points_by_node_id: dict[str, MapOverlayPoint] | None = None,
    ) -> MapOverlayPoint | None:
        if grid_points_by_node_id is not None and bus_id in grid_points_by_node_id:
            point = grid_points_by_node_id[bus_id]
            metadata = dict(point.metadata)
            metadata.update(
                {
                    "bus_id": bus_id,
                    "bus_name": fallback_label,
                    "coordinate_precision": "grid_node",
                }
            )
            return MapOverlayPoint(
                overlay_id=point.overlay_id,
                label=point.label,
                kind=point.kind,
                latitude=point.latitude,
                longitude=point.longitude,
                elevation_m=point.elevation_m,
                coordinate_system=point.coordinate_system,
                elevation_source=point.elevation_source,
                status=point.status,
                risk_level=point.risk_level,
                source=source,
                metadata=metadata,
            )

        warnings.append(f"{bus_id} GridNode 좌표가 없어 monitoring overlay에서 제외했습니다.")
        return None

    def _simulation_bus_point(
        self,
        bus_id: str,
        *,
        fallback_label: str,
        source: ResultSource,
        warnings: list[str],
        grid_points_by_node_id: dict[str, MapOverlayPoint] | None = None,
    ) -> MapOverlayPoint | None:
        if grid_points_by_node_id is not None and bus_id in grid_points_by_node_id:
            point = grid_points_by_node_id[bus_id]
            metadata = dict(point.metadata)
            metadata.update(
                {
                    "bus_id": bus_id,
                    "bus_name": fallback_label,
                    "coordinate_precision": "grid_node",
                }
            )
            return MapOverlayPoint(
                overlay_id=point.overlay_id,
                label=point.label,
                kind=point.kind,
                latitude=point.latitude,
                longitude=point.longitude,
                elevation_m=point.elevation_m,
                coordinate_system=point.coordinate_system,
                elevation_source=point.elevation_source,
                status=point.status,
                risk_level=point.risk_level,
                source=source,
                metadata=metadata,
            )

        warnings.append(f"{bus_id} GridNode 좌표가 없어 prediction overlay에서 제외했습니다.")
        return None

    def _candidate_point_from_recommendation(
        self,
        recommendation: RecommendationResult,
        *,
        source: ResultSource,
    ) -> MapOverlayPoint | None:
        route_point = _find_route_point(recommendation, recommendation.candidate_id)
        if route_point is None:
            return None

        score = recommendation.score
        is_user_candidate = _is_user_grid_candidate_id(recommendation.candidate_id)
        return MapOverlayPoint(
            overlay_id=f"tower_candidate:{route_point.point_id}",
            label=route_point.label,
            kind="tower_candidate",
            latitude=route_point.latitude,
            longitude=route_point.longitude,
            elevation_m=None,
            elevation_source="not_queried",
            status="selected" if recommendation.rank == 1 else "normal",
            source="manual" if is_user_candidate else source,
            metadata={
                "candidate_id": recommendation.candidate_id,
                "installation_id": recommendation.candidate_id if is_user_candidate else None,
                "candidate_source": "landing_installation" if is_user_candidate else "service_candidate",
                "rank": recommendation.rank,
                "score_total": score.total_score if score is not None else None,
                "congestion_relief": score.congestion_relief if score is not None else None,
                "rationale": recommendation.rationale,
            },
        )


def _grid_node_overlay_point(
    node: GridNode,
    *,
    profile: GridPowerProfile | None,
) -> MapOverlayPoint:
    metadata: dict[str, object] = dict(node.metadata)
    metadata.update(
        {
            "node_id": node.node_id,
            "node_type": node.node_type,
            "grid_source": node.source,
            "source_id": node.source_id,
            "voltage_kv": node.voltage_kv,
            "region": node.region,
            "base_load_mw": node.base_load_mw,
        }
    )
    if profile is not None:
        metadata.update(
            {
                "generation_mw": profile.generation_mw,
                "load_mw": profile.load_mw,
                "net_injection_mw": profile.net_injection_mw,
                "load_weight": profile.load_weight,
                "generation_weight": profile.generation_weight,
                "is_slack_candidate": profile.is_slack_candidate,
            }
        )

    return MapOverlayPoint(
        overlay_id=f"grid-node:{node.node_id}",
        label=node.node_name,
        kind=_overlay_kind_from_grid_node(node),
        latitude=node.latitude,
        longitude=node.longitude,
        elevation_m=node.elevation_m,
        coordinate_system=node.coordinate_system,
        elevation_source=node.elevation_source,
        status="selected" if node.source == "user_installation" else "normal",
        source="manual",
        metadata=metadata,
    )


def _grid_points_by_node_id_from_metadata(
    metadata: dict[str, object],
) -> dict[str, MapOverlayPoint]:
    dataset = metadata.get("grid_dataset")
    if not isinstance(dataset, GridDataset):
        return {}

    profile_by_node_id = {
        profile.node_id: profile
        for profile in dataset.power_profiles
    }
    return {
        node.node_id: _grid_node_overlay_point(
            node,
            profile=profile_by_node_id.get(node.node_id),
        )
        for node in dataset.nodes
    }


def _grid_line_overlay(
    line: GridLine,
    from_point: MapOverlayPoint,
    to_point: MapOverlayPoint,
) -> MapOverlayLine:
    return MapOverlayLine(
        overlay_id=f"grid-line:{line.line_id}",
        label=f"{from_point.label} -> {to_point.label}",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status=_overlay_status_from_grid_line(line),
        source="manual",
        metadata={
            "line_id": line.line_id,
            "from_node_id": line.from_node_id,
            "to_node_id": line.to_node_id,
            "voltage_kv": line.voltage_kv,
            "capacity_mw": line.capacity_mw,
            "reactance_pu": line.reactance_pu,
            "distance_km": line.distance_km,
            "resistance_pu": line.resistance_pu,
            "loss_factor": line.loss_factor,
            "terrain_risk": line.terrain_risk,
            "is_bidirectional": line.is_bidirectional,
            "grid_line_status": line.status,
            "grid_source": line.source,
            **line.metadata,
        },
    )


def _overlay_kind_from_grid_node(node: GridNode) -> str:
    if node.node_type in {"power_plant", "user_power_plant"}:
        return "power_plant"
    return "transmission_tower"


def _overlay_status_from_grid_line(line: GridLine) -> str:
    if line.status == "active":
        return "normal"
    if line.status == "out_of_service":
        return "critical"
    if line.status == "candidate":
        return "selected"
    return "unknown"


def _monitoring_line_overlay(
    line: LineStatus,
    from_point: MapOverlayPoint,
    to_point: MapOverlayPoint,
    source: ResultSource,
) -> MapOverlayLine:
    return MapOverlayLine(
        overlay_id=f"monitoring-line:{line.line_id}",
        label=f"{line.from_bus_name} -> {line.to_bus_name}",
        kind="line",
        from_point=from_point,
        to_point=to_point,
        status=line.status,
        risk_level=line.risk_level,
        source=source,
        metadata={
            "line_id": line.line_id,
            "from_bus": line.from_bus,
            "to_bus": line.to_bus,
            "flow_mw": line.flow_mw,
            "capacity_mw": line.capacity_mw,
            "utilization": line.utilization,
            "loss_mw": line.loss_mw,
        },
    )


def _prediction_risk_line_overlay(
    risk_line: RiskLine,
    from_point: MapOverlayPoint,
    to_point: MapOverlayPoint,
    source: ResultSource,
) -> MapOverlayLine:
    return MapOverlayLine(
        overlay_id=f"prediction-risk-line:{risk_line.line_id}",
        label=f"{risk_line.from_bus_name} -> {risk_line.to_bus_name}",
        kind="risk_line",
        from_point=from_point,
        to_point=to_point,
        status=_status_from_risk(risk_line.risk_level),
        risk_level=risk_line.risk_level,
        source=source,
        metadata={
            "line_id": risk_line.line_id,
            "from_bus": risk_line.from_bus,
            "to_bus": risk_line.to_bus,
            "predicted_utilization": risk_line.predicted_utilization,
            "peak_risk_hour": risk_line.peak_risk_hour,
            "explanation": risk_line.explanation,
        },
    )


def _prediction_selected_node_point(
    point: MapOverlayPoint,
    *,
    node_id: str,
) -> MapOverlayPoint:
    metadata = dict(point.metadata)
    metadata.update(
        {
            "node_id": node_id,
            "selected_for": "prediction_chart",
            "selection_source": "prediction_selected_bus_ids",
        }
    )
    return MapOverlayPoint(
        overlay_id=point.overlay_id,
        label=point.label,
        kind=point.kind,
        latitude=point.latitude,
        longitude=point.longitude,
        elevation_m=point.elevation_m,
        coordinate_system=point.coordinate_system,
        elevation_source=point.elevation_source,
        status="selected",
        risk_level=point.risk_level,
        source=point.source,
        metadata=metadata,
    )


def _route_overlay_from_recommendation(
    recommendation: RecommendationResult,
    source: ResultSource,
) -> MapOverlayRoute | None:
    route = recommendation.route
    if route is None:
        return None

    points = [
        _point_from_route_point(point, source=source)
        for point in route.waypoints
    ]
    score = recommendation.score
    is_user_candidate = _is_user_grid_candidate_id(recommendation.candidate_id)
    return MapOverlayRoute(
        overlay_id=f"simulation-route:{route.route_id}",
        label=f"{recommendation.rank}순위 {recommendation.candidate_label}",
        route_id=route.route_id,
        candidate_id=recommendation.candidate_id,
        rank=recommendation.rank,
        points=points,
        total_distance_km=route.total_distance_km,
        estimated_cost=route.estimated_cost,
        source=source,
        metadata={
            "candidate_id": recommendation.candidate_id,
            "installation_id": recommendation.candidate_id if is_user_candidate else None,
            "candidate_source": "landing_installation" if is_user_candidate else "service_candidate",
            "candidate_label": recommendation.candidate_label,
            "path_node_ids": list(route.path_node_ids),
            "score_total": score.total_score if score is not None else None,
            "distance_cost": score.distance_cost if score is not None else None,
            "construction_cost": score.construction_cost if score is not None else None,
            "congestion_relief": score.congestion_relief if score is not None else None,
            "environmental_risk": score.environmental_risk if score is not None else None,
            "policy_risk": score.policy_risk if score is not None else None,
            "rationale": recommendation.rationale,
            "route_summary": route.summary,
        },
    )


def _find_route_point(
    recommendation: RecommendationResult,
    point_id: str,
) -> RoutePoint | None:
    if recommendation.route is None:
        return None
    return next(
        (point for point in recommendation.route.waypoints if point.point_id == point_id),
        None,
    )


def _is_user_grid_candidate_id(candidate_id: str) -> bool:
    return candidate_id.startswith(("USER_TOWER_", "USER_PLANT_"))


def _point_from_route_point(
    point: RoutePoint,
    *,
    source: ResultSource,
) -> MapOverlayPoint:
    return MapOverlayPoint(
        overlay_id=f"route-point:{point.point_id}",
        label=point.label,
        kind="route_point",
        latitude=point.latitude,
        longitude=point.longitude,
        elevation_m=None,
        elevation_source="not_queried",
        source=source,
        metadata={"point_id": point.point_id},
    )


def _status_from_risk(risk_level: RiskLevel) -> str:
    if risk_level == "critical":
        return "critical"
    if risk_level in {"high", "medium"}:
        return "warning"
    return "normal"


def _build_overlay_result(
    *,
    scenario: ScenarioContext,
    created_at: datetime,
    source: ResultSource,
    points: list[MapOverlayPoint],
    lines: list[MapOverlayLine],
    routes: list[MapOverlayRoute],
    summary: str,
    source_warnings: list[str],
    local_warnings: list[str],
    source_fallback: FallbackInfo,
    map_capability: MapCapability,
) -> MapOverlayResult:
    fallback = _resolve_overlay_fallback(source_fallback, map_capability)
    headline_warning = (
        build_fallback_warning("MapOverlayService", fallback.mode)
        if fallback.enabled
        else build_source_warning("MapOverlayService", source)
    )
    warnings = _dedupe_warnings([
        headline_warning,
        *source_warnings,
        *map_capability.warnings,
        *local_warnings,
        _ELEVATION_WARNING,
    ])

    return MapOverlayResult(
        scenario=scenario,
        created_at=created_at,
        source=source,
        points=points,
        lines=lines,
        routes=routes,
        summary=summary,
        warnings=warnings,
        fallback=fallback,
        metadata={
            "rendering_mode": map_capability.rendering_mode,
            "vworld_available": map_capability.vworld_available,
            "coordinate_system": "EPSG:4326",
            "elevation_source": "not_queried",
            "source_fallback_mode": source_fallback.mode,
            "point_count": len(points),
            "line_count": len(lines),
            "route_count": len(routes),
        },
    )


def _resolve_overlay_fallback(
    source_fallback: FallbackInfo,
    map_capability: MapCapability,
) -> FallbackInfo:
    if map_capability.fallback.enabled:
        return map_capability.fallback
    if source_fallback.enabled:
        return source_fallback
    return build_no_fallback_info()


def _resolve_map_capability(
    map_capability: MapCapability | None,
) -> MapCapability:
    if map_capability is not None:
        return map_capability
    return get_map_capability(prefer_webgl=False)


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if not warning or warning in seen:
            continue
        deduped.append(warning)
        seen.add(warning)
    return deduped
