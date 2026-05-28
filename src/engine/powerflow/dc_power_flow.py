# 송전 네트워크에 대한 DC 전력 흐름 계산을 수행한다.
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ── 기본 상수 ──────────────────────────────────────────────────────────────────

BASE_MVA: float = 100.0  # 시스템 기준 용량 (MVA)

# ── 입출력 데이터클래스 ────────────────────────────────────────────────────────

@dataclass
class BusInput:
    """단일 버스의 발전·부하 입력."""

    bus_id: str
    p_gen_mw: float    # 발전량 (MW)
    p_load_mw: float   # 부하량 (MW)
    is_slack: bool = False

    @property
    def p_inject_mw(self) -> float:
        """순 주입 전력 (MW) = 발전 - 부하."""
        return self.p_gen_mw - self.p_load_mw


@dataclass
class LineInput:
    """단일 선로의 임피던스·용량 입력."""

    line_id: str
    from_bus: str
    to_bus: str
    reactance_pu: float   # 직렬 리액턴스 (per-unit)
    capacity_mw: float    # 열적 한계 용량 (MW)


@dataclass
class DCFlowResult:
    """DC Power Flow 계산 결과."""

    line_flows: dict[str, float]       # line_id → flow_mw (양수=정방향)
    bus_angles_deg: dict[str, float]   # bus_id → 전압각 (degree)
    converged: bool = True
    error: str = ""
    line_inputs: list[LineInput] = field(default_factory=list)


# ── B 행렬 빌더 ───────────────────────────────────────────────────────────────

def _build_b_matrix(
    bus_ids: list[str],
    lines: list[LineInput],
) -> np.ndarray:
    """서셉턴스 행렬 B (n×n, per-unit)를 생성한다."""
    n = len(bus_ids)
    idx = {bid: i for i, bid in enumerate(bus_ids)}
    B = np.zeros((n, n), dtype=float)
    for ln in lines:
        i, j = idx[ln.from_bus], idx[ln.to_bus]
        b = 1.0 / ln.reactance_pu
        B[i, i] += b
        B[j, j] += b
        B[i, j] -= b
        B[j, i] -= b
    return B


# ── 핵심 솔버 ─────────────────────────────────────────────────────────────────

def solve(
    buses: list[BusInput],
    lines: list[LineInput],
) -> DCFlowResult:
    """DC Power Flow를 풀어 DCFlowResult를 반환한다.

    알고리즘
    --------
    1. B 행렬 구성 (n×n)
    2. 슬랙 버스 행·열 제거 → B_red (n-1 × n-1)
    3. θ_red = B_red⁻¹ · P_red  (numpy.linalg.solve)
    4. P_ij = (θ_i - θ_j) / x_ij × BASE_MVA  (MW)
    """
    bus_ids = [b.bus_id for b in buses]
    slack_ids = [b.bus_id for b in buses if b.is_slack]

    if len(slack_ids) != 1:
        return DCFlowResult(
            line_flows={},
            bus_angles_deg={},
            converged=False,
            error=f"슬랙 버스는 정확히 1개여야 합니다. 현재: {slack_ids}",
            line_inputs=lines,
        )

    slack_id = slack_ids[0]
    slack_idx = bus_ids.index(slack_id)

    B = _build_b_matrix(bus_ids, lines)

    # 슬랙 버스 행·열 제거
    non_slack = [i for i in range(len(bus_ids)) if i != slack_idx]
    B_red = B[np.ix_(non_slack, non_slack)]

    # 순 주입 전력 벡터 (per-unit)
    p_inject = np.array(
        [b.p_inject_mw / BASE_MVA for b in buses], dtype=float
    )
    P_red = p_inject[non_slack]

    # 선형 방정식 풀기: θ = B_red⁻¹ · P  (radian)
    try:
        cond = np.linalg.cond(B_red)
        if cond > 1e10:
            return DCFlowResult(
                line_flows={},
                bus_angles_deg={},
                converged=False,
                error=f"B 행렬이 특이(singular)에 가깝습니다. 조건수={cond:.2e}",
                line_inputs=lines,
            )
        theta_red = np.linalg.solve(B_red, P_red)
    except np.linalg.LinAlgError as exc:
        return DCFlowResult(
            line_flows={},
            bus_angles_deg={},
            converged=False,
            error=f"선형 시스템 풀기 실패: {exc}",
            line_inputs=lines,
        )

    # 전압각 복원 (슬랙 버스 = 0)
    theta_full = np.zeros(len(bus_ids), dtype=float)
    for pos, orig_idx in enumerate(non_slack):
        theta_full[orig_idx] = theta_red[pos]

    bus_angles_deg = {
        bid: float(np.degrees(theta_full[i]))
        for i, bid in enumerate(bus_ids)
    }

    # 선로 조류: P_ij = (θ_i - θ_j) / x_ij × BASE_MVA
    idx_map = {bid: i for i, bid in enumerate(bus_ids)}
    line_flows: dict[str, float] = {}
    for ln in lines:
        i, j = idx_map[ln.from_bus], idx_map[ln.to_bus]
        flow_pu = (theta_full[i] - theta_full[j]) / ln.reactance_pu
        line_flows[ln.line_id] = round(float(flow_pu) * BASE_MVA, 1)

    return DCFlowResult(
        line_flows=line_flows,
        bus_angles_deg=bus_angles_deg,
        converged=True,
        line_inputs=lines,
    )


def build_default_line_inputs() -> list[LineInput]:
    """현재 기본 GridDataset으로부터 LineInput 목록을 반환한다."""
    from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
    from src.data.loaders import load_grid_dataset_or_default

    dataset = load_grid_dataset_or_default()
    return build_powerflow_inputs_from_grid(dataset).lines


def build_default_buses(load_scale: float = 1.0) -> list[BusInput]:
    """현재 기본 GridDataset으로부터 부하 배율이 적용된 BusInput 목록을 반환한다."""
    from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
    from src.data.loaders import load_grid_dataset_or_default

    dataset = load_grid_dataset_or_default(load_scale=load_scale)
    return build_powerflow_inputs_from_grid(dataset).buses

