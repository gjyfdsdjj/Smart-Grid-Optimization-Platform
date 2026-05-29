# 원시 데이터를 애플리케이션에서 사용할 수 있는 형태로 정제하고 변환한다.
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from src.data.adapters.public_data_adapter import load_kpx_national_hourly
from src.data.grid_builder import DEFAULT_GRID_TOTAL_LOAD_MW
from src.data.grid_powerflow_adapter import build_powerflow_inputs_from_grid
from src.data.loaders import DEFAULT_GRID_CSV_DIR, load_grid_dataset_or_default
from src.data.schemas import (
    GridDataset,
    GridNode,
    GridPowerProfile,
    InstallationPoint,
    PowerPlantSpec,
)
from src.engine.powerflow import dc_power_flow as _dcpf
from src.engine.powerflow.congestion_metrics import compute_line_statuses


NATIONAL_LOAD_HOURLY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "demand_mw",
    "supply_mw",
    "source_file",
)
DEFAULT_NATIONAL_LOAD_SOURCE = "KPX_public_sukub_csv"
GRID_NODE_WEIGHT_COLUMNS: tuple[str, ...] = (
    "node_id",
    "node_name",
    "node_type",
    "region",
    "source",
    "source_id",
    "base_load_mw",
    "load_weight",
    "generation_capacity_mw",
    "generation_weight",
    "is_load_node",
    "is_generation_node",
    "calibration_reason",
)
GRID_NODE_LOAD_HISTORY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "node_id",
    "node_name",
    "node_type",
    "region",
    "load_mw",
    "generation_mw",
    "net_injection_mw",
    "load_weight",
    "generation_weight",
    "national_demand_mw",
    "national_supply_mw",
    "grid_total_load_mw",
    "grid_total_generation_mw",
    "scale_to_grid",
    "source",
)
GRID_LINE_FLOW_HISTORY_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "line_id",
    "from_node_id",
    "to_node_id",
    "from_node_name",
    "to_node_name",
    "flow_mw",
    "abs_flow_mw",
    "capacity_mw",
    "utilization",
    "status",
    "risk_level",
    "loss_mw",
    "from_angle_deg",
    "to_angle_deg",
    "angle_delta_deg",
    "slack_bus_id",
    "reactance_pu",
    "line_status_source",
    "source",
)
LOAD_WEIGHT_TOLERANCE = 1e-6
GRID_NODE_LOAD_HISTORY_TOLERANCE_MW = 1e-3
GRID_LINE_FLOW_HISTORY_TOLERANCE = 1e-4
DEFAULT_GRID_NODE_LOAD_HISTORY_SOURCE = "KPX_public_sukub_csv + SGOP_grid_node_weights"
DEFAULT_GRID_LINE_FLOW_HISTORY_SOURCE = "SGOP_grid_node_load_history + DC_power_flow_balanced_dispatch"


def build_national_load_hourly(
    raw_dir: str | Path = "data/raw",
    output_path: str | Path = "data/processed/national_load_hourly.csv",
    *,
    source_file: str = DEFAULT_NATIONAL_LOAD_SOURCE,
) -> pd.DataFrame:
    """KPX raw CSV를 SGOP 공식 hourly national load 파일로 저장한다."""

    national = load_kpx_national_hourly(raw_dir)
    processed = normalize_national_load_hourly(
        national,
        source_file=source_file,
    )

    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    processed.to_csv(
        resolved_output_path,
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )
    return processed


def normalize_national_load_hourly(
    national_df: pd.DataFrame,
    *,
    source_file: str = DEFAULT_NATIONAL_LOAD_SOURCE,
) -> pd.DataFrame:
    """공공 수급 데이터를 고정 스키마와 검증 규칙에 맞게 정규화한다."""

    required = {"timestamp", "demand_mw", "supply_mw"}
    missing = required - set(national_df.columns)
    if missing:
        raise ValueError(f"national load 입력 컬럼이 부족합니다: {sorted(missing)}")

    df = national_df.loc[:, ["timestamp", "demand_mw", "supply_mw"]].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["demand_mw"] = pd.to_numeric(df["demand_mw"], errors="coerce")
    df["supply_mw"] = pd.to_numeric(df["supply_mw"], errors="coerce")
    df = df.dropna(subset=["timestamp", "demand_mw", "supply_mw"])

    if df.empty:
        raise ValueError("정규화할 national load 데이터가 없습니다.")

    df = (
        df.groupby("timestamp", as_index=False)
        .agg(
            demand_mw=("demand_mw", "mean"),
            supply_mw=("supply_mw", "mean"),
        )
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    df["timestamp"] = df["timestamp"].dt.floor("h")
    df = (
        df.groupby("timestamp", as_index=False)
        .agg(
            demand_mw=("demand_mw", "mean"),
            supply_mw=("supply_mw", "mean"),
        )
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    df["demand_mw"] = df["demand_mw"].round(6)
    df["supply_mw"] = df["supply_mw"].round(6)
    df["source_file"] = source_file

    _validate_national_load_hourly(df)
    return df.loc[:, list(NATIONAL_LOAD_HOURLY_COLUMNS)]


def build_grid_node_weights(
    grid_dir: str | Path | None = DEFAULT_GRID_CSV_DIR,
    output_path: str | Path = "data/processed/grid_node_weights.csv",
    *,
    user_installations: Iterable[InstallationPoint] | None = None,
) -> pd.DataFrame:
    """SGOP GridNode별 부하/발전 배분 가중치를 CSV로 저장한다.

    공식 processed 파일은 기본 enhanced grid 기준으로 생성한다. app 실행 중
    사용자가 추가했거나 xAI가 제안 후 승인한 노드는 `user_installations`로
    넘겨 동적 가중치표를 만들 수 있다. 신규 송전탑은 기본적으로 경로 보강
    노드이므로 load/generation weight를 0으로 둔다.
    """

    dataset = load_grid_dataset_or_default(
        grid_dir,
        user_installations=user_installations,
    )
    weights = normalize_grid_node_weights(dataset)

    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    weights.to_csv(resolved_output_path, index=False)
    return weights


def normalize_grid_node_weights(dataset: GridDataset) -> pd.DataFrame:
    """GridDataset을 노드별 부하/발전 가중치 표로 변환한다."""

    if not dataset.nodes:
        raise ValueError("Grid node weight를 만들 GridNode가 없습니다.")

    node_by_id = {node.node_id: node for node in dataset.nodes}
    if len(node_by_id) != len(dataset.nodes):
        raise ValueError("GridDataset.nodes에 중복 node_id가 있습니다.")

    load_node_ids = {
        node.node_id
        for node in dataset.nodes
        if _is_static_load_node(node)
    }
    total_base_load_mw = sum(
        max(0.0, node.base_load_mw)
        for node in dataset.nodes
        if node.node_id in load_node_ids
    )
    if total_base_load_mw <= 0.0:
        raise ValueError("load_weight를 계산할 기본 부하 노드가 없습니다.")

    generation_capacity_by_node_id = _generation_capacity_by_node_id(dataset.plants)
    total_generation_capacity_mw = sum(generation_capacity_by_node_id.values())
    if total_generation_capacity_mw <= 0.0:
        raise ValueError("generation_weight를 계산할 발전소 용량이 없습니다.")

    rows: list[dict[str, object]] = []
    for node in sorted(dataset.nodes, key=lambda item: item.node_id):
        is_load_node = node.node_id in load_node_ids
        generation_capacity_mw = generation_capacity_by_node_id.get(node.node_id, 0.0)
        is_generation_node = generation_capacity_mw > 0.0
        load_weight = (
            max(0.0, node.base_load_mw) / total_base_load_mw
            if is_load_node
            else 0.0
        )
        generation_weight = (
            generation_capacity_mw / total_generation_capacity_mw
            if is_generation_node
            else 0.0
        )
        rows.append(
            {
                "node_id": node.node_id,
                "node_name": node.node_name,
                "node_type": node.node_type,
                "region": node.region,
                "source": node.source,
                "source_id": node.source_id,
                "base_load_mw": round(max(0.0, node.base_load_mw), 6),
                "load_weight": round(load_weight, 10),
                "generation_capacity_mw": round(generation_capacity_mw, 6),
                "generation_weight": round(generation_weight, 10),
                "is_load_node": bool(is_load_node),
                "is_generation_node": bool(is_generation_node),
                "calibration_reason": _grid_node_calibration_reason(
                    node,
                    is_load_node=is_load_node,
                    is_generation_node=is_generation_node,
                ),
            }
        )

    result = pd.DataFrame(rows, columns=list(GRID_NODE_WEIGHT_COLUMNS))
    _validate_grid_node_weights(result)
    return result


def build_grid_node_load_history(
    national_load_path: str | Path = "data/processed/national_load_hourly.csv",
    node_weights_path: str | Path = "data/processed/grid_node_weights.csv",
    output_path: str | Path = "data/processed/grid_node_load_history.csv",
    *,
    default_grid_total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
    source: str = DEFAULT_GRID_NODE_LOAD_HISTORY_SOURCE,
) -> pd.DataFrame:
    """전국 hourly 부하를 SGOP GridNode별 시간대 부하/발전으로 재분배한다."""

    national = pd.read_csv(national_load_path)
    node_weights = pd.read_csv(node_weights_path)
    history = normalize_grid_node_load_history(
        national_load_df=national,
        node_weights_df=node_weights,
        default_grid_total_load_mw=default_grid_total_load_mw,
        source=source,
    )

    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(
        resolved_output_path,
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )
    return history


def normalize_grid_node_load_history(
    *,
    national_load_df: pd.DataFrame,
    node_weights_df: pd.DataFrame,
    default_grid_total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
    source: str = DEFAULT_GRID_NODE_LOAD_HISTORY_SOURCE,
) -> pd.DataFrame:
    """전국 부하 시계열과 GridNode weight를 결합해 node load history를 만든다."""

    national = normalize_national_load_hourly(
        national_load_df,
        source_file=str(
            national_load_df["source_file"].iloc[0]
            if "source_file" in national_load_df.columns and not national_load_df.empty
            else DEFAULT_NATIONAL_LOAD_SOURCE
        ),
    )
    weights = node_weights_df.copy()
    _validate_grid_node_weights(weights)

    resolved_total_load = float(default_grid_total_load_mw)
    if resolved_total_load <= 0.0:
        raise ValueError("default_grid_total_load_mw는 0보다 커야 합니다.")

    national["demand_mw"] = pd.to_numeric(national["demand_mw"], errors="coerce")
    national["supply_mw"] = pd.to_numeric(national["supply_mw"], errors="coerce")
    median_demand_mw = float(national["demand_mw"].median())
    if median_demand_mw <= 0.0:
        raise ValueError("national demand_mw 중앙값이 0보다 커야 합니다.")
    scale_to_grid = resolved_total_load / median_demand_mw

    weights = weights.loc[:, list(GRID_NODE_WEIGHT_COLUMNS)].copy()
    for column in (
        "load_weight",
        "generation_weight",
    ):
        weights[column] = pd.to_numeric(weights[column], errors="coerce").fillna(0.0)

    national = national.rename(
        columns={
            "demand_mw": "national_demand_mw",
            "supply_mw": "national_supply_mw",
        }
    )
    national["grid_total_load_mw"] = national["national_demand_mw"] * scale_to_grid
    national["grid_total_generation_mw"] = national["national_supply_mw"] * scale_to_grid
    national["scale_to_grid"] = scale_to_grid

    national["_join_key"] = 1
    weights["_join_key"] = 1
    history = national.merge(weights, on="_join_key", how="inner").drop(columns=["_join_key"])

    history["load_mw"] = history["grid_total_load_mw"] * history["load_weight"]
    history["generation_mw"] = history["grid_total_generation_mw"] * history["generation_weight"]
    history["net_injection_mw"] = history["generation_mw"] - history["load_mw"]
    history["source"] = source

    for column in (
        "load_mw",
        "generation_mw",
        "net_injection_mw",
        "national_demand_mw",
        "national_supply_mw",
        "grid_total_load_mw",
        "grid_total_generation_mw",
        "scale_to_grid",
    ):
        history[column] = pd.to_numeric(history[column], errors="coerce").round(6)

    result = history.loc[:, list(GRID_NODE_LOAD_HISTORY_COLUMNS)].copy()
    _validate_grid_node_load_history(result)
    return result


def build_grid_line_flow_history(
    grid_node_load_history_path: str | Path = "data/processed/grid_node_load_history.csv",
    output_path: str | Path = "data/processed/grid_line_flow_history.csv",
    *,
    grid_dir: str | Path | None = DEFAULT_GRID_CSV_DIR,
    grid_dataset: GridDataset | None = None,
    source: str = DEFAULT_GRID_LINE_FLOW_HISTORY_SOURCE,
) -> pd.DataFrame:
    """GridNode load history를 시간별 DC Power Flow 선로 라벨로 저장한다."""

    node_history = pd.read_csv(grid_node_load_history_path)
    dataset = grid_dataset or load_grid_dataset_or_default(grid_dir)
    line_history = normalize_grid_line_flow_history(
        node_load_history_df=node_history,
        grid_dataset=dataset,
        source=source,
    )

    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    line_history.to_csv(
        resolved_output_path,
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )
    return line_history


def normalize_grid_line_flow_history(
    *,
    node_load_history_df: pd.DataFrame,
    grid_dataset: GridDataset,
    source: str = DEFAULT_GRID_LINE_FLOW_HISTORY_SOURCE,
) -> pd.DataFrame:
    """노드별 시간대 부하 이력을 선로별 DC Power Flow 이력으로 변환한다.

    `grid_node_load_history.csv`의 generation_mw는 KPX 공급능력 proxy다.
    선로 조류 라벨은 timestamp별 부하를 만족시키는 dispatch 기준이므로
    `grid_total_load_mw x generation_weight`로 발전량을 재분배해 계산한다.
    """

    if not isinstance(grid_dataset, GridDataset):
        raise TypeError("grid_dataset은 GridDataset이어야 합니다.")
    if not grid_dataset.nodes:
        raise ValueError("grid line flow history를 만들 GridNode가 없습니다.")
    if not grid_dataset.lines:
        raise ValueError("grid line flow history를 만들 GridLine이 없습니다.")

    history = node_load_history_df.loc[:, list(GRID_NODE_LOAD_HISTORY_COLUMNS)].copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
    _validate_node_history_matches_grid(history, grid_dataset)
    _validate_grid_node_load_history(history)

    node_names = {
        node.node_id: node.node_name
        for node in grid_dataset.nodes
    }
    rows: list[dict[str, object]] = []

    for timestamp, group in history.groupby("timestamp", sort=True):
        timestamp_group = group.copy()
        profiles = _build_dispatch_profiles_for_timestamp(timestamp_group)
        timestamp_dataset = GridDataset(
            nodes=list(grid_dataset.nodes),
            lines=list(grid_dataset.lines),
            plants=list(grid_dataset.plants),
            tower_candidates=list(grid_dataset.tower_candidates),
            power_profiles=profiles,
            created_at=timestamp.to_pydatetime(),
            source=grid_dataset.source,
            warnings=list(grid_dataset.warnings),
            fallback=grid_dataset.fallback,
            metadata=dict(grid_dataset.metadata),
        )
        powerflow_inputs = build_powerflow_inputs_from_grid(timestamp_dataset)
        dc_result = _dcpf.solve(
            powerflow_inputs.buses,
            powerflow_inputs.lines,
        )
        if not dc_result.converged:
            raise RuntimeError(f"{timestamp} DC Power Flow 실패: {dc_result.error}")

        line_statuses = compute_line_statuses(
            dc_result,
            bus_names=powerflow_inputs.bus_names,
        )
        line_input_by_id = {
            line.line_id: line
            for line in powerflow_inputs.lines
        }
        for status in line_statuses:
            line_input = line_input_by_id[status.line_id]
            from_angle = dc_result.bus_angles_deg.get(status.from_bus, 0.0)
            to_angle = dc_result.bus_angles_deg.get(status.to_bus, 0.0)
            flow_mw = float(status.flow_mw)
            abs_flow_mw = abs(flow_mw)
            rows.append(
                {
                    "timestamp": timestamp,
                    "line_id": status.line_id,
                    "from_node_id": status.from_bus,
                    "to_node_id": status.to_bus,
                    "from_node_name": node_names.get(status.from_bus, status.from_bus),
                    "to_node_name": node_names.get(status.to_bus, status.to_bus),
                    "flow_mw": round(flow_mw, 6),
                    "abs_flow_mw": round(abs_flow_mw, 6),
                    "capacity_mw": round(float(status.capacity_mw), 6),
                    "utilization": round(float(status.utilization), 6),
                    "status": status.status,
                    "risk_level": status.risk_level,
                    "loss_mw": round(float(status.loss_mw), 6),
                    "from_angle_deg": round(float(from_angle), 6),
                    "to_angle_deg": round(float(to_angle), 6),
                    "angle_delta_deg": round(float(from_angle - to_angle), 6),
                    "slack_bus_id": powerflow_inputs.slack_bus_id,
                    "reactance_pu": round(float(line_input.reactance_pu), 8),
                    "line_status_source": "dc_power_flow_balanced_dispatch",
                    "source": source,
                }
            )

    result = pd.DataFrame(rows, columns=list(GRID_LINE_FLOW_HISTORY_COLUMNS))
    _validate_grid_line_flow_history(result)
    return result


def _validate_national_load_hourly(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("national load 결과가 비어 있습니다.")

    missing = set(NATIONAL_LOAD_HOURLY_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"national load 결과 컬럼이 부족합니다: {sorted(missing)}")

    if df["timestamp"].isna().any():
        raise ValueError("national load timestamp에 결측값이 있습니다.")
    if not df["timestamp"].is_monotonic_increasing:
        raise ValueError("national load timestamp가 오름차순이 아닙니다.")
    if df["timestamp"].duplicated().any():
        raise ValueError("national load timestamp가 중복되었습니다.")
    if (df["demand_mw"] <= 0.0).any():
        raise ValueError("national load demand_mw는 0보다 커야 합니다.")
    if (df["supply_mw"] <= 0.0).any():
        raise ValueError("national load supply_mw는 0보다 커야 합니다.")


def _validate_grid_node_weights(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("grid node weight 결과가 비어 있습니다.")

    missing = set(GRID_NODE_WEIGHT_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"grid node weight 결과 컬럼이 부족합니다: {sorted(missing)}")

    if df["node_id"].isna().any() or (df["node_id"].astype(str).str.strip() == "").any():
        raise ValueError("grid node weight node_id에 결측값이 있습니다.")
    if df["node_id"].duplicated().any():
        raise ValueError("grid node weight node_id가 중복되었습니다.")

    for column in (
        "base_load_mw",
        "load_weight",
        "generation_capacity_mw",
        "generation_weight",
    ):
        if (pd.to_numeric(df[column], errors="coerce") < 0.0).any():
            raise ValueError(f"grid node weight {column}은 음수일 수 없습니다.")

    load_sum = float(pd.to_numeric(df["load_weight"], errors="coerce").sum())
    generation_sum = float(pd.to_numeric(df["generation_weight"], errors="coerce").sum())
    if abs(load_sum - 1.0) > LOAD_WEIGHT_TOLERANCE:
        raise ValueError(f"load_weight 합계가 1.0이 아닙니다: {load_sum}")
    if abs(generation_sum - 1.0) > LOAD_WEIGHT_TOLERANCE:
        raise ValueError(f"generation_weight 합계가 1.0이 아닙니다: {generation_sum}")


def _validate_grid_node_load_history(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("grid node load history 결과가 비어 있습니다.")

    missing = set(GRID_NODE_LOAD_HISTORY_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"grid node load history 결과 컬럼이 부족합니다: {sorted(missing)}")

    if df["timestamp"].isna().any():
        raise ValueError("grid node load history timestamp에 결측값이 있습니다.")
    if df["node_id"].isna().any() or (df["node_id"].astype(str).str.strip() == "").any():
        raise ValueError("grid node load history node_id에 결측값이 있습니다.")
    if df[["timestamp", "node_id"]].duplicated().any():
        raise ValueError("grid node load history timestamp/node_id 조합이 중복되었습니다.")

    numeric_columns = [
        "load_mw",
        "generation_mw",
        "net_injection_mw",
        "load_weight",
        "generation_weight",
        "national_demand_mw",
        "national_supply_mw",
        "grid_total_load_mw",
        "grid_total_generation_mw",
        "scale_to_grid",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[column].isna().any():
            raise ValueError(f"grid node load history {column}에 숫자가 아닌 값이 있습니다.")

    for column in (
        "load_mw",
        "generation_mw",
        "load_weight",
        "generation_weight",
        "national_demand_mw",
        "national_supply_mw",
        "grid_total_load_mw",
        "grid_total_generation_mw",
        "scale_to_grid",
    ):
        if (df[column] < 0.0).any():
            raise ValueError(f"grid node load history {column}은 음수일 수 없습니다.")

    grouped = df.groupby("timestamp", as_index=False).agg(
        load_sum=("load_mw", "sum"),
        generation_sum=("generation_mw", "sum"),
        net_sum=("net_injection_mw", "sum"),
        grid_total_load_mw=("grid_total_load_mw", "first"),
        grid_total_generation_mw=("grid_total_generation_mw", "first"),
    )
    max_load_delta = (grouped["load_sum"] - grouped["grid_total_load_mw"]).abs().max()
    max_generation_delta = (
        grouped["generation_sum"] - grouped["grid_total_generation_mw"]
    ).abs().max()
    expected_net_sum = grouped["grid_total_generation_mw"] - grouped["grid_total_load_mw"]
    max_net_delta = (grouped["net_sum"] - expected_net_sum).abs().max()
    if max_load_delta > GRID_NODE_LOAD_HISTORY_TOLERANCE_MW:
        raise ValueError(f"timestamp별 load_mw 합계가 grid_total_load_mw와 다릅니다: {max_load_delta}")
    if max_generation_delta > GRID_NODE_LOAD_HISTORY_TOLERANCE_MW:
        raise ValueError(
            f"timestamp별 generation_mw 합계가 grid_total_generation_mw와 다릅니다: {max_generation_delta}"
        )
    if max_net_delta > GRID_NODE_LOAD_HISTORY_TOLERANCE_MW:
        raise ValueError(f"timestamp별 net_injection_mw 합계가 맞지 않습니다: {max_net_delta}")


def _validate_grid_line_flow_history(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("grid line flow history 결과가 비어 있습니다.")

    missing = set(GRID_LINE_FLOW_HISTORY_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"grid line flow history 결과 컬럼이 부족합니다: {sorted(missing)}")

    if df["timestamp"].isna().any():
        raise ValueError("grid line flow history timestamp에 결측값이 있습니다.")
    if df["line_id"].isna().any() or (df["line_id"].astype(str).str.strip() == "").any():
        raise ValueError("grid line flow history line_id에 결측값이 있습니다.")
    if df[["timestamp", "line_id"]].duplicated().any():
        raise ValueError("grid line flow history timestamp/line_id 조합이 중복되었습니다.")

    line_counts = df.groupby("timestamp")["line_id"].nunique()
    if line_counts.nunique() != 1:
        raise ValueError("grid line flow history timestamp별 선로 개수가 일정하지 않습니다.")

    numeric_columns = [
        "flow_mw",
        "abs_flow_mw",
        "capacity_mw",
        "utilization",
        "loss_mw",
        "from_angle_deg",
        "to_angle_deg",
        "angle_delta_deg",
        "reactance_pu",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[column].isna().any():
            raise ValueError(f"grid line flow history {column}에 숫자가 아닌 값이 있습니다.")

    for column in (
        "abs_flow_mw",
        "capacity_mw",
        "utilization",
        "loss_mw",
        "reactance_pu",
    ):
        if (df[column] < 0.0).any():
            raise ValueError(f"grid line flow history {column}은 음수일 수 없습니다.")
    if (df["capacity_mw"] <= 0.0).any():
        raise ValueError("grid line flow history capacity_mw는 0보다 커야 합니다.")
    if (df["reactance_pu"] <= 0.0).any():
        raise ValueError("grid line flow history reactance_pu는 0보다 커야 합니다.")

    allowed_status = {"normal", "warning", "critical", "overload"}
    invalid_status = set(df["status"].astype(str)) - allowed_status
    if invalid_status:
        raise ValueError(f"grid line flow history status 값이 올바르지 않습니다: {sorted(invalid_status)}")
    allowed_risk = {"low", "medium", "high", "critical"}
    invalid_risk = set(df["risk_level"].astype(str)) - allowed_risk
    if invalid_risk:
        raise ValueError(f"grid line flow history risk_level 값이 올바르지 않습니다: {sorted(invalid_risk)}")

    max_abs_delta = (df["abs_flow_mw"] - df["flow_mw"].abs()).abs().max()
    expected_utilization = df["abs_flow_mw"] / df["capacity_mw"]
    max_utilization_delta = (df["utilization"] - expected_utilization).abs().max()
    max_angle_delta = (
        df["angle_delta_deg"] - (df["from_angle_deg"] - df["to_angle_deg"])
    ).abs().max()
    if max_abs_delta > GRID_LINE_FLOW_HISTORY_TOLERANCE:
        raise ValueError(f"abs_flow_mw와 abs(flow_mw)가 다릅니다: {max_abs_delta}")
    if max_utilization_delta > GRID_LINE_FLOW_HISTORY_TOLERANCE:
        raise ValueError(f"utilization 계산값이 맞지 않습니다: {max_utilization_delta}")
    if max_angle_delta > GRID_LINE_FLOW_HISTORY_TOLERANCE:
        raise ValueError(f"angle_delta_deg 계산값이 맞지 않습니다: {max_angle_delta}")

    for column in ("line_status_source", "source", "slack_bus_id"):
        if df[column].isna().any() or (df[column].astype(str).str.strip() == "").any():
            raise ValueError(f"grid line flow history {column}에 빈 값이 있습니다.")


def _validate_node_history_matches_grid(
    history: pd.DataFrame,
    grid_dataset: GridDataset,
) -> None:
    expected_node_ids = {
        node.node_id
        for node in grid_dataset.nodes
    }
    actual_node_ids = set(history["node_id"].astype(str))
    missing_node_ids = expected_node_ids - actual_node_ids
    extra_node_ids = actual_node_ids - expected_node_ids
    if missing_node_ids:
        raise ValueError(f"grid node load history에 누락된 GridNode가 있습니다: {sorted(missing_node_ids)}")
    if extra_node_ids:
        raise ValueError(f"grid node load history에 GridDataset에 없는 node_id가 있습니다: {sorted(extra_node_ids)}")

    expected_count = len(expected_node_ids)
    node_counts = history.groupby("timestamp")["node_id"].nunique()
    bad_counts = node_counts[node_counts != expected_count]
    if not bad_counts.empty:
        first_bad_timestamp = bad_counts.index[0]
        raise ValueError(
            "grid node load history timestamp별 node_id 개수가 GridDataset과 다릅니다: "
            f"{first_bad_timestamp}"
        )


def _build_dispatch_profiles_for_timestamp(
    timestamp_group: pd.DataFrame,
) -> list[GridPowerProfile]:
    if timestamp_group.empty:
        raise ValueError("dispatch profile을 만들 timestamp group이 비어 있습니다.")

    timestamp = pd.to_datetime(timestamp_group["timestamp"].iloc[0])
    grid_total_load_mw = float(timestamp_group["grid_total_load_mw"].iloc[0])
    if grid_total_load_mw <= 0.0:
        raise ValueError(f"{timestamp} grid_total_load_mw는 0보다 커야 합니다.")

    generation_weight = pd.to_numeric(
        timestamp_group["generation_weight"],
        errors="coerce",
    ).fillna(0.0)
    total_generation_weight = float(generation_weight.sum())
    if total_generation_weight <= 0.0:
        raise ValueError(f"{timestamp} generation_weight 합계가 0보다 커야 합니다.")

    slack_row = (
        timestamp_group.assign(_generation_weight=generation_weight)
        .sort_values(["_generation_weight", "node_id"], ascending=[False, True])
        .iloc[0]
    )
    slack_node_id = str(slack_row["node_id"])

    profiles: list[GridPowerProfile] = []
    for row in timestamp_group.itertuples(index=False):
        node_id = str(row.node_id)
        load_mw = float(row.load_mw)
        load_weight = float(row.load_weight)
        node_generation_weight = float(row.generation_weight)
        dispatch_generation_mw = grid_total_load_mw * (
            node_generation_weight / total_generation_weight
        )
        profiles.append(
            GridPowerProfile(
                node_id=node_id,
                timestamp=timestamp.to_pydatetime(),
                generation_mw=dispatch_generation_mw,
                load_mw=load_mw,
                net_injection_mw=dispatch_generation_mw - load_mw,
                load_weight=load_weight,
                generation_weight=node_generation_weight,
                is_slack_candidate=(node_id == slack_node_id),
                metadata={
                    "dispatch_strategy": "balance_to_grid_total_load",
                    "source_generation_mw": float(row.generation_mw),
                },
            )
        )
    return profiles


def _is_static_load_node(node: GridNode) -> bool:
    return (
        node.node_type == "transmission_tower"
        and node.source != "user_installation"
        and max(0.0, node.base_load_mw) > 0.0
    )


def _generation_capacity_by_node_id(
    plants: Iterable[PowerPlantSpec],
) -> dict[str, float]:
    capacity_by_node_id: dict[str, float] = {}
    for plant in plants:
        capacity = max(0.0, plant.capacity_mw * plant.availability)
        capacity_by_node_id[plant.node_id] = capacity_by_node_id.get(plant.node_id, 0.0) + capacity
    return capacity_by_node_id


def _grid_node_calibration_reason(
    node: GridNode,
    *,
    is_load_node: bool,
    is_generation_node: bool,
) -> str:
    if node.node_type == "user_transmission_tower":
        return "사용자/xAI 승인 송전탑은 기본적으로 경로 보강 노드로 취급해 부하/발전 가중치를 0으로 둔다."
    if node.node_type == "user_power_plant":
        return "사용자 추가 발전소는 capacity_mw x availability 기준으로 발전 가중치를 계산한다."
    if is_load_node:
        return "enhanced grid base_load_mw 기준으로 공공 전국 수요를 재분배한다."
    if is_generation_node:
        return "발전소 capacity_mw x availability 기준으로 발전량 배분 가중치를 계산한다."
    return "부하 또는 발전 배분 대상이 아닌 연결 노드다."
