# Monitoring, Simulation, Prediction 결과를 지도/표 공통 overlay 계약으로 변환한다.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.data.adapters.vworld_adapter import MapCapability, get_map_capability
from src.data.schemas import (
    FallbackInfo,
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


@dataclass(frozen=True)
class _CoordinateSpec:
    point_id: str
    label: str
    latitude: float
    longitude: float


_SIMULATION_BUS_COORDINATES: dict[str, _CoordinateSpec] = {
    "BUS_001": _CoordinateSpec("BUS_001", "서울", 37.5665, 126.9780),
    "BUS_002": _CoordinateSpec("BUS_002", "인천", 37.4563, 126.7052),
    "BUS_003": _CoordinateSpec("BUS_003", "수원", 37.2636, 127.0286),
    "BUS_004": _CoordinateSpec("BUS_004", "춘천", 37.8813, 127.7298),
    "BUS_005": _CoordinateSpec("BUS_005", "강릉", 37.7519, 128.8761),
    "BUS_006": _CoordinateSpec("BUS_006", "원주", 37.3422, 127.9202),
    "BUS_007": _CoordinateSpec("BUS_007", "대전", 36.3504, 127.3845),
    "BUS_008": _CoordinateSpec("BUS_008", "청주", 36.6424, 127.4890),
    "BUS_009": _CoordinateSpec("BUS_009", "광주", 35.1595, 126.8526),
    "BUS_010": _CoordinateSpec("BUS_010", "전주", 35.8242, 127.1480),
    "BUS_011": _CoordinateSpec("BUS_011", "대구", 35.8714, 128.6014),
    "BUS_012": _CoordinateSpec("BUS_012", "울산", 35.5384, 129.3114),
    "BUS_013": _CoordinateSpec("BUS_013", "부산", 35.1796, 129.0756),
}

_MONITORING_BUS_COORDINATES: dict[str, _CoordinateSpec] = {
    "B01": _CoordinateSpec("B01", "신가평", 37.8350, 127.5110),
    "B02": _CoordinateSpec("B02", "양주", 37.7850, 126.9870),
    "B03": _CoordinateSpec("B03", "신용인", 37.2400, 127.1770),
    "B04": _CoordinateSpec("B04", "신안성", 37.0070, 127.2700),
    "B05": _CoordinateSpec("B05", "신평택", 36.9920, 127.1120),
    "B06": _CoordinateSpec("B06", "서울동", 37.5450, 127.1900),
    "B07": _CoordinateSpec("B07", "분당", 37.3820, 127.1200),
    "B08": _CoordinateSpec("B08", "동서울", 37.5380, 127.2140),
    "B09": _CoordinateSpec("B09", "수원", 37.2640, 127.0290),
    "B10": _CoordinateSpec("B10", "신시흥", 37.3800, 126.8030),
    "B11": _CoordinateSpec("B11", "인천북", 37.5400, 126.7050),
    "B12": _CoordinateSpec("B12", "신강남", 37.4900, 127.0700),
    "B13": _CoordinateSpec("B13", "신서울", 37.6500, 126.8700),
}

_CANDIDATE_COORDINATES: dict[str, _CoordinateSpec] = {
    "SITE_NORTH": _CoordinateSpec("SITE_NORTH", "북부 우회안", 36.9300, 127.5200),
    "SITE_CENTRAL": _CoordinateSpec("SITE_CENTRAL", "중앙 균형안", 36.2800, 127.7600),
    "SITE_SOUTH": _CoordinateSpec("SITE_SOUTH", "남부 확장안", 35.9800, 128.0500),
}


class MapOverlayService:
    """서비스 결과를 지도 UI가 아닌 공통 overlay 데이터로 변환한다."""

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

        for line in result.line_statuses:
            from_point = self._monitoring_bus_point(
                line.from_bus,
                fallback_label=line.from_bus_name,
                source=result.source,
                warnings=warnings,
            )
            to_point = self._monitoring_bus_point(
                line.to_bus,
                fallback_label=line.to_bus_name,
                source=result.source,
                warnings=warnings,
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
                f"{len(points_by_id)}개 버스 지점을 제공합니다."
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
            for line in baseline_monitoring.line_statuses:
                from_point = self._monitoring_bus_point(
                    line.from_bus,
                    fallback_label=line.from_bus_name,
                    source=baseline_monitoring.source,
                    warnings=warnings,
                )
                to_point = self._monitoring_bus_point(
                    line.to_bus,
                    fallback_label=line.to_bus_name,
                    source=baseline_monitoring.source,
                    warnings=warnings,
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

        for risk_line in result.risk_lines:
            from_point = self._simulation_bus_point(
                risk_line.from_bus,
                fallback_label=risk_line.from_bus_name,
                source=result.source,
                warnings=warnings,
            )
            to_point = self._simulation_bus_point(
                risk_line.to_bus,
                fallback_label=risk_line.to_bus_name,
                source=result.source,
                warnings=warnings,
            )
            if from_point is None or to_point is None:
                continue

            points_by_id.setdefault(from_point.overlay_id, from_point)
            points_by_id.setdefault(to_point.overlay_id, to_point)
            lines.append(_prediction_risk_line_overlay(risk_line, from_point, to_point, result.source))

        return _build_overlay_result(
            scenario=scenario,
            created_at=result.created_at,
            source=result.source,
            points=list(points_by_id.values()),
            lines=lines,
            routes=[],
            summary=(
                f"Prediction overlay: 예측 위험 선로 {len(lines)}개와 "
                f"{len(points_by_id)}개 버스 지점을 제공합니다."
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
    ) -> MapOverlayPoint | None:
        coordinate = _MONITORING_BUS_COORDINATES.get(bus_id)
        if coordinate is None:
            warnings.append(f"{bus_id} 버스 좌표가 없어 monitoring overlay에서 제외했습니다.")
            return None
        return _point_from_coordinate(
            coordinate,
            kind="bus",
            source=source,
            metadata={"bus_id": bus_id, "bus_name": fallback_label, "coordinate_precision": "mock_substation"},
        )

    def _simulation_bus_point(
        self,
        bus_id: str,
        *,
        fallback_label: str,
        source: ResultSource,
        warnings: list[str],
    ) -> MapOverlayPoint | None:
        coordinate = _SIMULATION_BUS_COORDINATES.get(bus_id)
        if coordinate is None:
            warnings.append(f"{bus_id} 버스 좌표가 없어 prediction overlay에서 제외했습니다.")
            return None
        return _point_from_coordinate(
            coordinate,
            kind="bus",
            source=source,
            metadata={"bus_id": bus_id, "bus_name": fallback_label, "coordinate_precision": "city_centroid"},
        )

    def _candidate_point_from_recommendation(
        self,
        recommendation: RecommendationResult,
        *,
        source: ResultSource,
    ) -> MapOverlayPoint | None:
        route_point = _find_route_point(recommendation, recommendation.candidate_id)
        coordinate = (
            _CoordinateSpec(
                route_point.point_id,
                route_point.label,
                route_point.latitude,
                route_point.longitude,
            )
            if route_point is not None
            else _CANDIDATE_COORDINATES.get(recommendation.candidate_id)
        )
        if coordinate is None:
            return None

        score = recommendation.score
        return _point_from_coordinate(
            coordinate,
            kind="tower_candidate",
            status="selected" if recommendation.rank == 1 else "normal",
            source=source,
            metadata={
                "candidate_id": recommendation.candidate_id,
                "rank": recommendation.rank,
                "score_total": score.total_score if score is not None else None,
                "congestion_relief": score.congestion_relief if score is not None else None,
                "rationale": recommendation.rationale,
            },
        )


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


def _point_from_coordinate(
    coordinate: _CoordinateSpec,
    *,
    kind: str,
    source: ResultSource,
    status: str = "unknown",
    metadata: dict[str, object] | None = None,
) -> MapOverlayPoint:
    return MapOverlayPoint(
        overlay_id=f"{kind}:{coordinate.point_id}",
        label=coordinate.label,
        kind=kind,  # type: ignore[arg-type]
        latitude=coordinate.latitude,
        longitude=coordinate.longitude,
        elevation_m=None,
        elevation_source="not_queried",
        status=status,  # type: ignore[arg-type]
        source=source,
        metadata=metadata or {},
    )


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
