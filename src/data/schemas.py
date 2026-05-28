# SGOP의 입력과 출력에 쓰이는 공통 데이터 스키마를 정의한다.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


# ── 공통 타입 별칭 ─────────────────────────────────────────────────────────────

CongestionStatus = Literal["normal", "warning", "critical", "overload"]
"""
이용률 기반 혼잡 상태
---------------------
normal   : 이용률 < 70%
warning  : 70% <= 이용률 < 90%
critical : 90% <= 이용률 < 100%
overload : 이용률 >= 100%
"""

RiskLevel = Literal["low", "medium", "high", "critical"]
"""
위험도 레이블 (예측·추천 공통)
------------------------------
low      : 이용률 < 55%
medium   : 55% <= 이용률 < 75%
high     : 75% <= 이용률 < 90%
critical : 이용률 >= 90%
"""

ResultSource = Literal[
    "mock",
    "baseline",
    "lstm",
    "gnn",
    "hybrid",
    "dc_power_flow",
    "heuristic",
    "astar",
    "manual",
]

FallbackMode = Literal[
    "none",
    "mock_data",
    "baseline_model",
    "cached_result",
    "manual_override",
    "map_2_5d",
]

MapOverlayKind = Literal[
    "bus",
    "line",
    "power_plant",
    "transmission_tower",
    "start_point",
    "end_point",
    "install_point",
    "tower_candidate",
    "route",
    "route_point",
    "risk_line",
]

MapOverlayStatus = Literal[
    "normal",
    "warning",
    "critical",
    "overload",
    "unknown",
    "selected",
]

InstallationTargetKind = Literal[
    "power_plant",
    "transmission_tower",
    "start_point",
    "end_point",
]

InstallationMode = Literal[
    "new",
    "replace",
    "review",
]

GridNodeType = Literal[
    "power_plant",
    "transmission_tower",
    "user_power_plant",
    "user_transmission_tower",
]

GridDataSource = Literal[
    "default_asset",
    "user_installation",
    "csv",
    "fallback_mock",
    "legacy",
]

GridLineStatus = Literal[
    "active",
    "planned",
    "candidate",
    "out_of_service",
]


# ── 공통 메타데이터 ────────────────────────────────────────────────────────────

@dataclass
class FallbackInfo:
    """주 경로가 실패했을 때 어떤 fallback 을 사용했는지 기록한다."""

    enabled: bool
    mode: FallbackMode = "none"
    reason: str = ""
    primary_path: str = ""
    active_path: str = ""


@dataclass
class ScenarioContext:
    """Monitoring, Simulation, Prediction 이 공유하는 시나리오 식별자."""

    scenario_id: str
    title: str = ""
    description: str = ""
    region: str = ""
    created_at: datetime | None = None
    created_by: str = ""


@dataclass
class TimeSeriesPoint:
    """페이지 차트에서 공통으로 쓰는 단일 시계열 포인트."""

    timestamp: datetime
    value: float
    label: str = ""


# ── 지도/오버레이 공통 계약 ───────────────────────────────────────────────────

@dataclass
class MapOverlayPoint:
    """지도 위에 표시할 단일 지점.

    latitude/longitude는 화면 표시용 좌표이고, elevation_m은 고도 또는 지형
    높이 조회 결과를 담기 위한 3축 좌표 슬롯이다. 고도 조회 전에는 None으로
    두고 warnings/fallback에 단순화 여부를 남긴다.
    """

    overlay_id: str
    label: str
    kind: MapOverlayKind
    latitude: float
    longitude: float
    elevation_m: float | None = None
    coordinate_system: str = "EPSG:4326"
    elevation_source: str = ""
    status: MapOverlayStatus = "unknown"
    risk_level: RiskLevel | None = None
    source: ResultSource = "manual"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class MapOverlayLine:
    """지도 위에 표시할 선로 또는 예측 위험 선."""

    overlay_id: str
    label: str
    kind: MapOverlayKind
    from_point: MapOverlayPoint
    to_point: MapOverlayPoint
    status: MapOverlayStatus = "unknown"
    risk_level: RiskLevel | None = None
    source: ResultSource = "manual"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class MapOverlayRoute:
    """A* 추천 경로를 지도 계층에 넘기기 위한 공통 형식."""

    overlay_id: str
    label: str
    route_id: str
    candidate_id: str = ""
    rank: int | None = None
    points: list[MapOverlayPoint] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_cost: float = 0.0
    source: ResultSource = "manual"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class MapOverlayResult:
    """지도/표 동기화 계층이 공통으로 소비하는 overlay 묶음."""

    scenario: ScenarioContext
    created_at: datetime
    source: ResultSource
    points: list[MapOverlayPoint] = field(default_factory=list)
    lines: list[MapOverlayLine] = field(default_factory=list)
    routes: list[MapOverlayRoute] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback: FallbackInfo = field(default_factory=lambda: FallbackInfo(enabled=False))
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class InstallationPoint:
    """사용자가 지도에서 선택한 설치 대상 지점.

    longitude/latitude는 화면에서 x/y로 표시하고, elevation_m은 후속 정밀 지형
    조회 결과를 담기 위한 슬롯이다. 현재 2.5D 경로에서는 elevation_m=None과
    elevation_source="not_queried"를 유지한다.
    """

    installation_id: str
    label: str
    kind: InstallationTargetKind
    latitude: float
    longitude: float
    mode: InstallationMode = "new"
    elevation_m: float | None = None
    coordinate_system: str = "EPSG:4326"
    elevation_source: str = "not_queried"
    capacity_mw: float | None = None
    voltage_kv: float | None = None
    notes: str = ""
    created_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


# ── Grid 공통 계약 ────────────────────────────────────────────────────────────

@dataclass
class GridNode:
    """발전소와 송전탑을 함께 다루는 전력망 노드 계약.

    현재 Grid 전환 작업의 기준 노드다. legacy `BUS_*` 또는 `B*` ID를
    확장하지 않고, 기본 발전소/송전탑과 사용자 추가 지점을 같은 그래프
    노드로 표현한다.
    """

    node_id: str
    node_name: str
    node_type: GridNodeType
    latitude: float
    longitude: float
    voltage_kv: float
    region: str = ""
    base_load_mw: float = 0.0
    elevation_m: float | None = None
    coordinate_system: str = "EPSG:4326"
    elevation_source: str = "not_queried"
    source: GridDataSource = "default_asset"
    source_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class GridLine:
    """GridNode 사이의 송전망 연결 계약.

    데이터 의미는 양방향을 기본으로 하고, DC Power Flow 같은 계산 엔진에
    넘길 때만 from/to 방향 입력으로 변환한다.
    """

    line_id: str
    from_node_id: str
    to_node_id: str
    voltage_kv: float
    capacity_mw: float
    reactance_pu: float
    distance_km: float
    resistance_pu: float = 0.0
    loss_factor: float = 0.0
    terrain_risk: float = 0.0
    is_bidirectional: bool = True
    status: GridLineStatus = "active"
    source: GridDataSource = "default_asset"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class PowerPlantSpec:
    """GridNode에 연결되는 발전소 상세 계약."""

    plant_id: str
    plant_name: str
    node_id: str
    capacity_mw: float
    fuel_type: str
    min_output_mw: float
    max_output_mw: float
    ramp_rate_mw_per_h: float | None = None
    availability: float = 1.0
    operating_cost: float | None = None
    emission_factor: float | None = None
    source: GridDataSource = "default_asset"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class TransmissionTowerSpec:
    """GridNode에 연결되는 송전탑 또는 송전탑 후보 상세 계약."""

    tower_id: str
    tower_name: str
    node_id: str
    voltage_kv: float
    elevation_m: float | None = None
    height_m: float | None = None
    terrain_slope_deg: float | None = None
    install_cost_billion: float | None = None
    land_type: str = ""
    environment_risk: float = 0.0
    policy_risk: float = 0.0
    accessibility_score: float | None = None
    nearest_node_id: str = ""
    source: GridDataSource = "default_asset"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class GridPowerProfile:
    """GridNode별 발전/부하/순주입 프로필.

    후속 단계에서 KPX 전국 수요나 발전소 출력값을 node_id 기준으로 배분할
    때 사용한다. `net_injection_mw`는 `generation_mw - load_mw` 기준이다.
    """

    node_id: str
    timestamp: datetime | None = None
    generation_mw: float = 0.0
    load_mw: float = 0.0
    net_injection_mw: float = 0.0
    load_weight: float = 0.0
    generation_weight: float = 0.0
    is_slack_candidate: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class GridDataset:
    """새 Grid 전환의 공통 데이터 묶음.

    CSV, 기본 asset, 사용자 설치 지점, fallback mock을 같은 형태로 담는다.
    Monitoring/Simulation/Prediction은 후속 단계에서 이 계약을 각 엔진 입력으로
    변환해 사용한다.
    """

    nodes: list[GridNode] = field(default_factory=list)
    lines: list[GridLine] = field(default_factory=list)
    plants: list[PowerPlantSpec] = field(default_factory=list)
    tower_candidates: list[TransmissionTowerSpec] = field(default_factory=list)
    power_profiles: list[GridPowerProfile] = field(default_factory=list)
    created_at: datetime | None = None
    source: GridDataSource = "fallback_mock"
    warnings: list[str] = field(default_factory=list)
    fallback: FallbackInfo = field(default_factory=lambda: FallbackInfo(enabled=False))
    metadata: dict[str, object] = field(default_factory=dict)


# ── 시나리오 저장 상태 ────────────────────────────────────────────────────────

@dataclass
class ScenarioPageState:
    """시나리오와 함께 저장할 페이지 입력 상태.

    계산 결과 자체는 저장하지 않는다. 저장 대상은 사용자가 다시 같은 조건으로
    Monitoring, Simulation, Prediction을 실행할 수 있게 하는 입력값과 랜딩 지도
    설치 지점 목록이다.
    """

    landing_installations: list[InstallationPoint] = field(default_factory=list)
    monitoring_load_scale: float = 1.0
    monitoring_data_source: str = "DC Power Flow"
    simulation_start_bus_id: str = "PLANT_INCHEON"
    simulation_end_bus_id: str = "TOWER_DAEGU"
    simulation_candidate_site_ids: list[str] = field(default_factory=list)
    simulation_load_scale: float = 1.0
    prediction_load_scale: float = 1.0
    prediction_model_source: str = "Mock"
    prediction_selected_bus_ids: list[str] = field(default_factory=list)
    prediction_retrain: bool = False
    prediction_epochs: int = 20
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class SavedScenarioState:
    """ScenarioService가 저장소에 기록하는 전체 시나리오 상태."""

    scenario: ScenarioContext
    page_state: ScenarioPageState = field(default_factory=ScenarioPageState)
    schema_version: int = 1


# ── 모니터링 ──────────────────────────────────────────────────────────────────

@dataclass
class MonitoringKpi:
    """모니터링 상단 KPI 카드의 단일 항목."""

    metric_id: str
    label: str
    value: float
    unit: str                                           # "%", "MW", "lines" 등
    status: Literal["normal", "warning", "critical"] = "normal"
    delta: float | None = None


@dataclass
class LineStatus:
    """단일 송전선의 실시간 혼잡 상태.

    입력 계약
    ---------
    DC Power Flow 계산 결과 또는 mock 데이터로부터 생성된다.

    출력 계약
    ---------
    MonitoringResult.line_statuses 리스트의 원소로 사용된다.
    """

    line_id: str
    from_bus: str
    to_bus: str
    from_bus_name: str
    to_bus_name: str
    flow_mw: float          # 실제 전력 흐름 (MW)
    capacity_mw: float      # 열적 한계 용량 (MW)
    utilization: float      # flow_mw / capacity_mw (0.0 ~ 1.0+)
    status: CongestionStatus
    risk_level: RiskLevel   # 예측·추천 서비스와 공유하는 위험도 레이블
    loss_mw: float          # 추정 저항 손실 (MW)


@dataclass
class CongestionSummary:
    """전체 선로에 대한 혼잡도 요약 통계.

    MonitoringService 가 LineStatus 목록을 집계하여 생성한다.
    """

    total_lines: int
    normal_count: int
    warning_count: int
    critical_count: int
    overload_count: int
    avg_utilization: float          # 전체 평균 이용률 (0.0 ~ 1.0)
    total_loss_mw: float            # 전체 추정 손실 합계 (MW)
    max_utilization: float          # 최대 이용률 (0.0 ~ 1.0+)
    max_utilization_line_id: str    # 최대 이용률 선로 ID


@dataclass
class MonitoringResult:
    """MonitoringService 의 공통 반환 형식.

    source 값
    ----------
    "mock"         : 합성 고정값 (1주차 기본값)
    "dc_power_flow": DC Power Flow 계산 결과 (3단계 이후)
    """

    scenario: ScenarioContext
    created_at: datetime
    source: ResultSource
    load_scale: float
    line_statuses: list[LineStatus]
    congestion_summary: CongestionSummary
    kpis: list[MonitoringKpi] = field(default_factory=list)
    trend_points: list[TimeSeriesPoint] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback: FallbackInfo = field(default_factory=lambda: FallbackInfo(enabled=False))
    metadata: dict[str, object] = field(default_factory=dict)


# ── 시뮬레이션 ────────────────────────────────────────────────────────────────

@dataclass
class RoutePoint:
    """지도 오버레이와 경로 표시에 공통으로 쓰는 경유점."""

    point_id: str
    label: str
    latitude: float
    longitude: float


@dataclass
class RouteResult:
    """A* 또는 휴리스틱 탐색 결과의 최소 공통 형식."""

    route_id: str
    start_bus_id: str
    end_bus_id: str
    path_node_ids: list[str] = field(default_factory=list)
    waypoints: list[RoutePoint] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_cost: float = 0.0
    source: ResultSource = "mock"
    summary: str = ""


@dataclass
class ScoreBreakdown:
    """추천 결과 점수화를 구성하는 비용/보상 요소 묶음."""

    total_score: float
    distance_cost: float = 0.0
    construction_cost: float = 0.0
    congestion_relief: float = 0.0
    environmental_risk: float = 0.0
    policy_risk: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class RecommendationResult:
    """후보지별 추천 결과를 정렬 가능한 형식으로 표현한다."""

    candidate_id: str
    candidate_label: str
    rank: int = 0
    route: RouteResult | None = None
    score: ScoreBreakdown | None = None
    rationale: str = ""


@dataclass
class SimulationDelta:
    """설치 전후 비교 표에 들어갈 단일 변화량."""

    metric_id: str
    label: str
    before_value: float
    after_value: float
    unit: str
    improvement: float
    status: Literal["improved", "unchanged", "worsened"] = "unchanged"


@dataclass
class SimulationInput:
    """Simulation 페이지와 서비스가 공유하는 입력 계약."""

    scenario: ScenarioContext
    start_bus_id: str = ""
    end_bus_id: str = ""
    candidate_site_ids: list[str] = field(default_factory=list)
    user_candidate_points: list[InstallationPoint] = field(default_factory=list)
    user_grid_installations: list[InstallationPoint] = field(default_factory=list)
    load_scale: float = 1.0
    notes: str = ""


@dataclass
class SimulationResult:
    """SimulationService 의 공통 반환 형식."""

    scenario: ScenarioContext
    created_at: datetime
    source: ResultSource
    simulation_input: SimulationInput
    selected_route: RouteResult | None = None
    recommendations: list[RecommendationResult] = field(default_factory=list)
    deltas: list[SimulationDelta] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback: FallbackInfo = field(default_factory=lambda: FallbackInfo(enabled=False))
    metadata: dict[str, object] = field(default_factory=dict)


# ── 예측 피처 ─────────────────────────────────────────────────────────────────

@dataclass
class ForecastFeatureVector:
    """DC Power Flow 이후 예측 모델에 투입되는 단일 타임스텝 피처 벡터.

    입력 계약
    ---------
    - 과거 부하 lag: 1h / 6h / 12h / 24h / 48h / 72h (MW, 없으면 0.0)
    - 시간 특성: hour (0-23), day_of_week (0=월 … 6=일), is_weekend, is_holiday, month
    - 계통 특성: total_generation_mw, regional_demand_ratio (해당 노드 / 전체)

    출력 계약
    ---------
    ForecastFeatureVector 인스턴스 (lstm_forecaster / baseline 양쪽에서 공통 사용)
    """

    timestamp: datetime
    bus_id: str

    # 과거 부하 이력 (MW)
    load_lag_1h: float
    load_lag_6h: float
    load_lag_12h: float
    load_lag_24h: float
    load_lag_48h: float
    load_lag_72h: float

    # 시간 특성
    hour: int            # 0-23
    day_of_week: int     # 0=월 … 6=일
    is_weekend: bool
    is_holiday: bool
    month: int           # 1-12

    # 계통 특성
    total_generation_mw: float
    regional_demand_ratio: float  # 해당 노드 부하 / 전체 부하 (0.0-1.0)


# ── 예측 결과 ─────────────────────────────────────────────────────────────────

@dataclass
class HourlyLoadPrediction:
    """단일 노드·단일 시각의 예측값과 신뢰구간."""

    timestamp: datetime
    bus_id: str
    predicted_load_mw: float
    confidence_lower_mw: float
    confidence_upper_mw: float


@dataclass
class RiskLine:
    """24시간 예측 구간 중 혼잡 위험이 높은 선로 정보.

    risk_level 기준
    ---------------
    critical : 이용률 >= 90%  (즉각 대응 필요)
    high     : 이용률 >= 75%  (모니터링 강화)
    medium   : 이용률 >= 55%  (주의 관찰)
    low      : 이용률 < 55%   (정상)
    """

    line_id: str
    from_bus: str
    to_bus: str
    from_bus_name: str
    to_bus_name: str
    peak_risk_hour: int           # 위험 피크 시각 (0-23)
    predicted_utilization: float  # 0.0-1.0+ (1.0 = 열적한계 100%)
    risk_level: RiskLevel
    explanation: str              # xAI 규칙 기반 설명 문장


@dataclass
class PredictionResult:
    """PredictionService.run_mock_prediction() 의 최종 반환값.

    source 값
    ----------
    "mock"     : 합성 sinusoidal 데이터 (1주차 기본값)
    "baseline" : 이동평균 / 계절성 분해 baseline 모델
    "lstm"     : 훈련된 LSTM 모델
    "gnn"      : 그래프 기반 예측 모델
    "hybrid"   : LSTM + GNN 병렬 조합 모델
    """

    scenario_id: str
    created_at: datetime
    load_scale: float
    forecast_horizon_h: int           # 예측 시간 수 (기본 24)
    predictions: list[HourlyLoadPrediction]
    risk_lines: list[RiskLine]        # risk_level != "low" 인 선로만 포함, 이용률 내림차순
    summary: str
    source: ResultSource
    scenario: ScenarioContext | None = None
    warnings: list[str] = field(default_factory=list)
    fallback: FallbackInfo = field(default_factory=lambda: FallbackInfo(enabled=False))
    metadata: dict[str, object] = field(default_factory=dict)
