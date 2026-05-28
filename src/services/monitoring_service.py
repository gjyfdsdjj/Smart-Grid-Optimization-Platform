# 모니터링 흐름과 혼잡 요약 생성을 조율한다.
from __future__ import annotations

import math
from datetime import datetime, timedelta

from src.data.schemas import (
    CongestionSummary,
    GridDataset,
    InstallationPoint,
    LineStatus,
    MonitoringKpi,
    MonitoringResult,
    ScenarioContext,
    TimeSeriesPoint,
)
from src.data.loaders import load_grid_dataset_or_default
from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
from src.engine.powerflow import dc_power_flow as _dcpf
from src.engine.powerflow.congestion_metrics import (
    compute_congestion_summary,
    compute_line_statuses,
)
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)

# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _round_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _congestion_status(util: float) -> str:
    if util >= 1.0:
        return "overload"
    if util >= 0.9:
        return "critical"
    if util >= 0.7:
        return "warning"
    return "normal"


def _classify_risk(util: float) -> str:
    if util >= 0.9:
        return "critical"
    if util >= 0.75:
        return "high"
    if util >= 0.55:
        return "medium"
    return "low"


def _kpi_status_from_risk(risk_level: str) -> str:
    if risk_level == "critical":
        return "critical"
    if risk_level == "high":
        return "warning"
    return "normal"


def _build_lines_from_grid(dataset: GridDataset) -> list[LineStatus]:
    node_by_id = {
        node.node_id: node
        for node in dataset.nodes
    }
    profile_by_node_id = {
        profile.node_id: profile
        for profile in dataset.power_profiles
    }
    lines: list[LineStatus] = []

    for grid_line in dataset.lines:
        if grid_line.status == "out_of_service":
            continue
        from_node = node_by_id.get(grid_line.from_node_id)
        to_node = node_by_id.get(grid_line.to_node_id)
        if from_node is None or to_node is None:
            continue
        from_profile = profile_by_node_id.get(from_node.node_id)
        to_profile = profile_by_node_id.get(to_node.node_id)
        from_load = from_profile.load_mw if from_profile is not None else from_node.base_load_mw
        to_load = to_profile.load_mw if to_profile is not None else to_node.base_load_mw
        endpoint_pressure = max(0.0, from_load, to_load)
        imbalance = abs(from_load - to_load)
        terrain_factor = 1.0 + (grid_line.terrain_risk * 0.04)
        flow = round(((endpoint_pressure * 0.95) + (imbalance * 0.20)) * terrain_factor, 1)
        util = round(flow / grid_line.capacity_mw, 4) if grid_line.capacity_mw > 0.0 else 0.0
        loss = round(flow * max(0.004, grid_line.loss_factor) * util, 2)
        lines.append(
            LineStatus(
                line_id=grid_line.line_id,
                from_bus=from_node.node_id,
                to_bus=to_node.node_id,
                from_bus_name=from_node.node_name,
                to_bus_name=to_node.node_name,
                flow_mw=flow,
                capacity_mw=grid_line.capacity_mw,
                utilization=util,
                status=_congestion_status(util),      # type: ignore[arg-type]
                risk_level=_classify_risk(util),      # type: ignore[arg-type]
                loss_mw=loss,
            )
        )
    return lines


def _build_congestion_summary(lines: list[LineStatus]) -> CongestionSummary:
    counts: dict[str, int] = {"normal": 0, "warning": 0, "critical": 0, "overload": 0}
    for line in lines:
        counts[line.status] += 1
    avg_util = sum(l.utilization for l in lines) / len(lines)
    total_loss = sum(l.loss_mw for l in lines)
    max_line = max(lines, key=lambda l: l.utilization)
    return CongestionSummary(
        total_lines=len(lines),
        normal_count=counts["normal"],
        warning_count=counts["warning"],
        critical_count=counts["critical"],
        overload_count=counts["overload"],
        avg_utilization=round(avg_util, 4),
        total_loss_mw=round(total_loss, 2),
        max_utilization=round(max_line.utilization, 4),
        max_utilization_line_id=max_line.line_id,
    )


def _build_kpis(
    cs: CongestionSummary,
    trend_points: list[TimeSeriesPoint],
) -> list[MonitoringKpi]:
    latest_load = trend_points[-1].value if trend_points else 0.0
    previous_load = trend_points[-2].value if len(trend_points) >= 2 else latest_load
    danger = cs.critical_count + cs.overload_count
    operating_margin = round(max(0.0, 1.0 - cs.max_utilization) * 100.0, 1)
    return [
        MonitoringKpi(
            metric_id="current_load",
            label="현재 총부하",
            value=latest_load,
            unit="MW",
            status="critical" if latest_load >= 40_000 else "warning" if latest_load >= 35_000 else "normal",
            delta=round(latest_load - previous_load, 1),
        ),
        MonitoringKpi(
            metric_id="peak_utilization",
            label="최대 이용률",
            value=round(cs.max_utilization * 100, 1),
            unit="%",
            status=_kpi_status_from_risk(_classify_risk(cs.max_utilization)),
        ),
        MonitoringKpi(
            metric_id="danger_lines",
            label="위험·과부하 선로",
            value=float(danger),
            unit="lines",
            status="critical" if danger > 0 else "normal",
            delta=float(cs.warning_count),
        ),
        MonitoringKpi(
            metric_id="operating_margin",
            label="운영 여유도",
            value=operating_margin,
            unit="%",
            status="critical" if operating_margin < 10.0 else "warning" if operating_margin < 25.0 else "normal",
        ),
    ]


def _build_trend_points(
    load_scale: float,
    base_time: datetime,
    *,
    base_load_mw: float = 35_000.0,
) -> list[TimeSeriesPoint]:
    """과거 12시간 총부하 mock 추세 (sinusoidal 패턴)."""
    base_hour = _round_to_hour(base_time)
    points: list[TimeSeriesPoint] = []
    for offset in range(-11, 1):
        t = base_hour + timedelta(hours=offset)
        wave = math.sin((t.hour / 24.0) * 2 * math.pi) * 0.15
        load = base_load_mw * load_scale * (1.0 + wave)
        points.append(TimeSeriesPoint(timestamp=t, value=round(load, 0), label=f"{t:%H}:00"))
    return points


def _build_summary_text(cs: CongestionSummary, lines: list[LineStatus]) -> str:
    danger = cs.critical_count + cs.overload_count
    if danger == 0 and cs.warning_count == 0:
        return f"전체 {cs.total_lines}개 선로 정상 운영 중. 평균 이용률 {cs.avg_utilization*100:.1f}%."
    busiest = max(lines, key=lambda l: l.utilization)
    parts = []
    if danger > 0:
        parts.append(f"위험·과부하 {danger}개")
    if cs.warning_count > 0:
        parts.append(f"경고 {cs.warning_count}개")
    return (
        f"{', '.join(parts)} 선로 감지. "
        f"{busiest.from_bus_name}→{busiest.to_bus_name}({busiest.line_id}) "
        f"이용률 {busiest.utilization*100:.1f}%로 최대. 즉각 점검 권고."
    )


def _build_warnings(lines: list[LineStatus]) -> list[str]:
    warnings = [build_fallback_warning("MonitoringService", "mock_data")]
    critical = [l.line_id for l in lines if l.risk_level == "critical"]
    high = [l.line_id for l in lines if l.risk_level == "high"]
    if critical:
        warnings.append(f"즉시 확인이 필요한 critical 선로: {', '.join(critical)}")
    elif high:
        warnings.append(f"혼잡 임계치에 근접한 high 선로: {', '.join(high)}")
    return warnings


# ── 공개 함수 (하위 호환) ──────────────────────────────────────────────────────

def run_mock_monitoring(load_scale: float = 1.0) -> MonitoringResult:
    """mock 선로 데이터로 MonitoringResult 를 생성한다 (하위 호환 함수).

    Parameters
    ----------
    load_scale:
        전체 부하 배율. 1.0 = 기준 부하.
    """
    scenario = ScenarioContext(
        scenario_id="mock-001",
        title="Mock Scenario",
        created_at=datetime.now(),
        created_by="run_mock_monitoring",
    )
    return MonitoringService().run_mock_monitoring(scenario=scenario, load_scale=load_scale)


# ── MonitoringService 클래스 ───────────────────────────────────────────────────

class MonitoringService:
    """모니터링 흐름을 조율하는 서비스 클래스.

    1주차: run_mock_monitoring() 만 구현.
    3단계 이후: run_dc_power_flow() 로 교체 예정.
    """

    def run_mock_monitoring(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
    ) -> MonitoringResult:
        """mock 데이터로 MonitoringResult 를 생성한다.

        Parameters
        ----------
        scenario:
            Monitoring, Simulation, Prediction 이 공유하는 시나리오 컨텍스트.
            None 이면 기본 mock 시나리오를 생성한다.
        load_scale:
            전체 부하 배율. 1.0 = 기준 부하.
        created_at:
            결과 기준 시각. None 이면 현재 시각을 사용한다.
        """
        validated_load_scale, input_warnings = self._validate_load_scale(load_scale)
        now = self._resolve_created_at(created_at)
        resolved_scenario = self._resolve_scenario(scenario, now)
        dataset = load_grid_dataset_or_default(
            created_at=now,
            load_scale=validated_load_scale,
        )
        lines = _build_lines_from_grid(dataset)
        cs = _build_congestion_summary(lines)
        trend = _build_trend_points(
            validated_load_scale,
            now,
            base_load_mw=float(dataset.metadata.get("default_total_load_mw", 35_000.0)),
        )

        return MonitoringResult(
            scenario=resolved_scenario,
            created_at=now,
            source="mock",
            load_scale=validated_load_scale,
            line_statuses=lines,
            congestion_summary=cs,
            kpis=_build_kpis(cs, trend),
            trend_points=trend,
            summary=_build_summary_text(cs, lines),
            warnings=input_warnings + _build_warnings(lines),
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 dc_power_flow 엔진 대신 GridDataset 기반 mock 결과를 사용합니다.",
                primary_path="src.engine.powerflow.dc_power_flow",
                active_path="src.services.monitoring_service.MonitoringService.run_mock_monitoring",
            ),
            metadata={
                "grid_dataset": dataset,
                "grid_node_count": len(dataset.nodes),
                "grid_line_count": len(dataset.lines),
                "legacy_bus_source": False,
            },
        )

    def run_dc_power_flow(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
        grid_dataset: GridDataset | None = None,
        user_installations: list[InstallationPoint] | None = None,
    ) -> MonitoringResult:
        """DC Power Flow 계산으로 MonitoringResult 를 생성한다.

        GridDataset 기반 DC 계산이 실패하면 자동으로 run_mock_monitoring() 으로
        fallback 한다.

        Parameters
        ----------
        scenario:
            공유 시나리오 컨텍스트. None 이면 기본 시나리오를 생성한다.
        load_scale:
            전체 부하 배율. 1.0 = 기준 부하.
        created_at:
            결과 기준 시각. None 이면 현재 시각을 사용한다.
        grid_dataset:
            이미 조립된 GridDataset. None 이면 기본 발전소/송전탑과 사용자 설치
            지점으로 GridDataset을 생성한다.
        user_installations:
            grid_dataset이 없을 때 GridNode로 반영할 랜딩 설치 지점 목록.
        """
        validated_load_scale, input_warnings = self._validate_load_scale(load_scale)
        now = self._resolve_created_at(created_at)
        resolved_scenario = self._resolve_scenario(scenario, now)

        try:
            dataset = grid_dataset or load_grid_dataset_or_default(
                user_installations=user_installations or [],
                created_at=now,
                load_scale=validated_load_scale,
            )
            powerflow_inputs = build_powerflow_inputs_from_grid(dataset)
            dc_result = _dcpf.solve(
                powerflow_inputs.buses,
                powerflow_inputs.lines,
            )

            if not dc_result.converged:
                raise RuntimeError(dc_result.error)

            line_statuses = compute_line_statuses(
                dc_result,
                bus_names=powerflow_inputs.bus_names,
            )
            cs = compute_congestion_summary(line_statuses)
            trend = _build_trend_points(
                validated_load_scale,
                now,
                base_load_mw=float(dataset.metadata.get("default_total_load_mw", 35_000.0)),
            )

            return MonitoringResult(
                scenario=resolved_scenario,
                created_at=now,
                source="dc_power_flow",
                load_scale=validated_load_scale,
                line_statuses=line_statuses,
                congestion_summary=cs,
                kpis=_build_kpis(cs, trend),
                trend_points=trend,
                summary=_build_summary_text(cs, line_statuses),
                warnings=[
                    *input_warnings,
                    build_source_warning("MonitoringService", "dc_power_flow"),
                    *dataset.warnings,
                    *powerflow_inputs.warnings,
                ],
                fallback=build_no_fallback_info(),
                metadata={
                    "grid_dataset": dataset,
                    "grid_node_count": len(dataset.nodes),
                    "grid_line_count": len(dataset.lines),
                    "powerflow_line_count": len(powerflow_inputs.lines),
                    "powerflow_line_policy": "non_outage",
                    "slack_bus_id": powerflow_inputs.slack_bus_id,
                    "included_line_ids": list(powerflow_inputs.included_line_ids),
                    "excluded_line_ids": list(powerflow_inputs.excluded_line_ids),
                    "legacy_bus_source": False,
                },
            )

        except Exception as exc:  # noqa: BLE001
            fallback_result = self.run_mock_monitoring(
                scenario=resolved_scenario,
                load_scale=validated_load_scale,
                created_at=created_at,
            )
            fallback_result.warnings.insert(
                1,
                f"DC Power Flow 실패 → mock fallback 전환. 원인: {exc}",
            )
            fallback_result.fallback = build_fallback_info(
                mode="mock_data",
                reason=str(exc),
                primary_path="src.data.grid_powerflow_adapter -> src.engine.powerflow.dc_power_flow.solve",
                active_path="src.services.monitoring_service.MonitoringService.run_mock_monitoring",
            )
            return fallback_result

    def get_monitoring_result(
        self,
        scenario: ScenarioContext | None = None,
        load_scale: float = 1.0,
        *,
        created_at: datetime | None = None,
    ) -> MonitoringResult:
        """기존 호출부 호환용 wrapper."""
        return self.run_dc_power_flow(
            scenario=scenario,
            load_scale=load_scale,
            created_at=created_at,
        )

    def _resolve_scenario(
        self,
        scenario: ScenarioContext | None,
        created_at: datetime,
    ) -> ScenarioContext:
        if scenario is not None and not isinstance(scenario, ScenarioContext):
            raise TypeError("scenario는 ScenarioContext여야 합니다.")
        if scenario is not None:
            if scenario.created_at is None:
                scenario.created_at = created_at
            return scenario
        return ScenarioContext(
            scenario_id="monitoring-mock",
            title="Monitoring Mock Scenario",
            description="모니터링 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="MonitoringService",
        )

    def _resolve_created_at(self, created_at: datetime | None) -> datetime:
        if created_at is None:
            return _round_to_hour(datetime.now())
        if not isinstance(created_at, datetime):
            raise TypeError("created_at는 datetime 인스턴스여야 합니다.")
        return _round_to_hour(created_at)

    def _validate_load_scale(self, load_scale: float) -> tuple[float, list[str]]:
        if isinstance(load_scale, bool):
            raise ValueError("load_scale는 bool이 아닌 숫자여야 합니다.")

        try:
            resolved_scale = float(load_scale)
        except (TypeError, ValueError) as exc:
            raise ValueError("load_scale는 숫자여야 합니다.") from exc

        if not math.isfinite(resolved_scale):
            raise ValueError("load_scale는 NaN 또는 무한대가 아닌 유한한 숫자여야 합니다.")
        if resolved_scale <= 0:
            raise ValueError("load_scale는 0보다 커야 합니다.")

        warnings: list[str] = []
        if resolved_scale < 0.5:
            warnings.append(
                f"입력 부하 배율 {resolved_scale:.2f}×가 권장 하한 0.50×보다 낮아 0.50×로 보정했습니다."
            )
            resolved_scale = 0.5
        elif resolved_scale > 1.5:
            warnings.append(
                f"입력 부하 배율 {resolved_scale:.2f}×가 권장 상한 1.50×보다 높아 1.50×로 보정했습니다."
            )
            resolved_scale = 1.5

        return round(resolved_scale, 2), warnings
