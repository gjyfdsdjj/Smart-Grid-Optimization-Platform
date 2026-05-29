# 로컬 또는 외부 소스에서 전력망, 지도, 시나리오 데이터를 불러온다.
from __future__ import annotations

import math
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.data.grid_builder import (
    DEFAULT_GRID_TOTAL_LOAD_MW,
    build_default_grid_dataset,
    build_grid_lines,
    build_grid_power_profiles,
    build_user_grid_assets,
)
from src.data.schemas import (
    FallbackInfo,
    GridDataset,
    GridLine,
    GridNode,
    InstallationPoint,
    PowerPlantSpec,
    TransmissionTowerSpec,
)


DEFAULT_GRID_CSV_DIR = Path(__file__).resolve().parents[2] / "data" / "grid" / "enhanced"
DEFAULT_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
DEFAULT_GRID_NODE_LOAD_HISTORY_PATH = DEFAULT_PROCESSED_DIR / "grid_node_load_history.csv"
DEFAULT_GRID_LINE_FLOW_HISTORY_PATH = DEFAULT_PROCESSED_DIR / "grid_line_flow_history.csv"
DEFAULT_MODEL_EVALUATION_SUMMARY_PATH = DEFAULT_PROCESSED_DIR / "model_evaluation_summary.csv"

_NODES_COLUMNS = [
    "node_id",
    "node_name",
    "node_type",
    "latitude",
    "longitude",
    "voltage_kv",
    "region",
    "base_load_mw",
    "elevation_m",
    "coordinate_system",
    "elevation_source",
    "source",
    "source_id",
]
_LINES_COLUMNS = [
    "line_id",
    "from_node_id",
    "to_node_id",
    "voltage_kv",
    "capacity_mw",
    "reactance_pu",
    "distance_km",
    "resistance_pu",
    "loss_factor",
    "terrain_risk",
    "is_bidirectional",
    "status",
    "source",
]
_PLANTS_COLUMNS = [
    "plant_id",
    "plant_name",
    "node_id",
    "capacity_mw",
    "fuel_type",
    "min_output_mw",
    "max_output_mw",
    "ramp_rate_mw_per_h",
    "availability",
    "operating_cost",
    "emission_factor",
    "source",
]
_TOWER_COLUMNS = [
    "tower_id",
    "tower_name",
    "node_id",
    "voltage_kv",
    "elevation_m",
    "height_m",
    "terrain_slope_deg",
    "install_cost_billion",
    "land_type",
    "environment_risk",
    "policy_risk",
    "accessibility_score",
    "nearest_node_id",
    "source",
]
_GRID_NODE_LOAD_HISTORY_COLUMNS = [
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
]
_GRID_LINE_FLOW_HISTORY_COLUMNS = [
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
]
_MODEL_EVALUATION_REQUIRED_COLUMNS = [
    "model",
    "mae_mw",
    "rmse_mw",
    "mape_pct",
]


def load_grid_dataset_from_csv(
    grid_dir: str | Path,
    *,
    user_installations: Iterable[InstallationPoint] | None = None,
    created_at: datetime | None = None,
    load_scale: float = 1.0,
    total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
) -> GridDataset:
    """Grid CSV 네 파일을 읽어 `GridDataset`으로 변환한다.

    CSV는 노드/선로/발전소/송전탑 상세의 구조 계약이고, 전력 profile은
    로드 시점의 `GridDataset` 기준으로 다시 계산한다.
    """

    resolved_dir = Path(grid_dir)
    resolved_at = _resolve_created_at(created_at)
    node_rows = _read_csv(resolved_dir / "nodes.csv", _NODES_COLUMNS)
    line_rows = _read_csv(resolved_dir / "lines.csv", _LINES_COLUMNS)
    plant_rows = _read_csv(resolved_dir / "plants.csv", _PLANTS_COLUMNS)
    tower_rows = _read_csv(resolved_dir / "tower_candidates.csv", _TOWER_COLUMNS)

    nodes = _parse_nodes(node_rows)
    node_by_id = {node.node_id: node for node in nodes}
    if len(node_by_id) != len(nodes):
        raise ValueError("nodes.csv에 중복 node_id가 있습니다.")

    plants = _parse_plants(plant_rows, node_by_id)
    towers = _parse_towers(tower_rows, node_by_id)
    lines = _parse_lines(line_rows, node_by_id)
    warnings = _connectivity_warnings(nodes, lines)

    user_nodes: list[GridNode] = []
    user_plants: list[PowerPlantSpec] = []
    user_towers: list[TransmissionTowerSpec] = []
    if user_installations is not None:
        user_nodes, user_plants, user_towers, user_warnings = build_user_grid_assets(
            user_installations
        )
        warnings.extend(user_warnings)
        existing_node_ids = {node.node_id for node in nodes}
        for user_node in user_nodes:
            if user_node.node_id in existing_node_ids:
                raise ValueError(f"사용자 설치 지점이 기존 GridNode와 중복됩니다: {user_node.node_id}")
            existing_node_ids.add(user_node.node_id)
        nodes.extend(user_nodes)
        plants.extend(user_plants)
        towers.extend(user_towers)
        if user_nodes:
            lines, generated_warnings = build_grid_lines(nodes, tower_candidates=towers)
            warnings.extend(generated_warnings)

    dataset = GridDataset(
        nodes=nodes,
        lines=lines,
        plants=plants,
        tower_candidates=towers,
        created_at=resolved_at,
        source="csv",
        warnings=warnings,
        metadata={
            "grid_stage": "12",
            "grid_dir": str(resolved_dir),
            "line_generation_status": "generated_for_user_installations" if user_nodes else "csv",
            "csv_file_count": 4,
            "default_total_load_mw": total_load_mw,
            "load_scale": load_scale,
            "sources": ["csv"] + (["user_installation"] if user_nodes else []),
        },
    )
    profiles, profile_warnings = build_grid_power_profiles(
        dataset,
        created_at=resolved_at,
        load_scale=load_scale,
        total_load_mw=total_load_mw,
    )
    dataset.power_profiles = profiles
    dataset.warnings.extend(profile_warnings)
    dataset.metadata.update(
        {
            "node_count": len(dataset.nodes),
            "line_count": len(dataset.lines),
            "plant_count": len(dataset.plants),
            "tower_candidate_count": len(dataset.tower_candidates),
            "profile_count": len(dataset.power_profiles),
        }
    )
    return dataset


def load_grid_dataset_or_default(
    grid_dir: str | Path | None = DEFAULT_GRID_CSV_DIR,
    *,
    user_installations: Iterable[InstallationPoint] | None = None,
    created_at: datetime | None = None,
    load_scale: float = 1.0,
    total_load_mw: float = DEFAULT_GRID_TOTAL_LOAD_MW,
) -> GridDataset:
    """CSV가 있으면 CSV GridDataset을, 실패하면 기본 GridDataset을 반환한다."""

    resolved_at = _resolve_created_at(created_at)
    if grid_dir is not None:
        try:
            return load_grid_dataset_from_csv(
                grid_dir,
                user_installations=user_installations,
                created_at=resolved_at,
                load_scale=load_scale,
                total_load_mw=total_load_mw,
            )
        except Exception as exc:  # noqa: BLE001
            fallback = build_default_grid_dataset(
                user_installations=user_installations,
                created_at=resolved_at,
                load_scale=load_scale,
                total_load_mw=total_load_mw,
            )
            fallback.fallback = FallbackInfo(
                enabled=True,
                mode="mock_data",
                reason=f"Grid CSV를 읽지 못해 기본 발전소/송전탑 graph를 사용합니다. 원인: {exc}",
                primary_path="data/grid/mock/nodes.csv + lines.csv + plants.csv + tower_candidates.csv",
                active_path="src.data.grid_builder.build_default_grid_dataset",
            )
            fallback.source = "fallback_mock"
            fallback.warnings.insert(
                0,
                "Grid CSV 로더는 현재 `mock_data` fallback 결과를 반환합니다.",
            )
            fallback.metadata["csv_loader_error"] = str(exc)
            fallback.metadata["csv_grid_dir"] = str(grid_dir)
            return fallback

    return build_default_grid_dataset(
        user_installations=user_installations,
        created_at=resolved_at,
        load_scale=load_scale,
        total_load_mw=total_load_mw,
    )


def load_processed_grid_node_history(
    path: str | Path = DEFAULT_GRID_NODE_LOAD_HISTORY_PATH,
    *,
    min_timestamps: int = 24,
) -> pd.DataFrame:
    """공식 processed GridNode 부하 이력을 읽고 Prediction 입력 계약으로 검증한다."""

    resolved_path = Path(path)
    _ensure_file_exists(resolved_path)
    df = _load_processed_grid_node_history_cached(
        str(resolved_path.resolve()),
        resolved_path.stat().st_mtime_ns,
        int(min_timestamps),
    ).copy()
    df.attrs["source_path"] = _portable_path(resolved_path)
    return df


def load_processed_grid_line_flow_history(
    path: str | Path = DEFAULT_GRID_LINE_FLOW_HISTORY_PATH,
) -> pd.DataFrame:
    """공식 processed GridLine DC Power Flow 라벨을 읽고 검증한다."""

    resolved_path = Path(path)
    _ensure_file_exists(resolved_path)
    df = _load_processed_grid_line_flow_history_cached(
        str(resolved_path.resolve()),
        resolved_path.stat().st_mtime_ns,
    ).copy()
    df.attrs["source_path"] = _portable_path(resolved_path)
    return df


def summarize_processed_grid_line_flow_history(
    path: str | Path = DEFAULT_GRID_LINE_FLOW_HISTORY_PATH,
) -> dict[str, object]:
    """Prediction metadata에 쓸 GridLine 라벨 파일 요약을 반환한다."""

    resolved_path = Path(path)
    _ensure_file_exists(resolved_path)
    return dict(
        _summarize_processed_grid_line_flow_history_cached(
            str(resolved_path.resolve()),
            resolved_path.stat().st_mtime_ns,
        )
    )


def load_model_evaluation_summary(
    path: str | Path = DEFAULT_MODEL_EVALUATION_SUMMARY_PATH,
) -> pd.DataFrame:
    """모델별 holdout 평가 요약 CSV를 읽고 핵심 비교 컬럼을 검증한다."""

    resolved_path = Path(path)
    _ensure_file_exists(resolved_path)
    df = _load_model_evaluation_summary_cached(
        str(resolved_path.resolve()),
        resolved_path.stat().st_mtime_ns,
    ).copy()
    df.attrs["source_path"] = _portable_path(resolved_path)
    return df


def _read_csv(path: Path, expected_columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} 파일이 없습니다.")
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(df.columns) != expected_columns:
        raise ValueError(
            f"{path.name} 헤더가 Grid CSV 계약과 다릅니다. "
            f"expected={expected_columns}, actual={list(df.columns)}"
        )
    return df


@lru_cache(maxsize=4)
def _load_processed_grid_node_history_cached(
    path: str,
    mtime_ns: int,
    min_timestamps: int,
) -> pd.DataFrame:
    del mtime_ns
    df = pd.read_csv(path)
    _validate_processed_grid_node_history(df, min_timestamps=min_timestamps)
    return df


@lru_cache(maxsize=2)
def _load_processed_grid_line_flow_history_cached(
    path: str,
    mtime_ns: int,
) -> pd.DataFrame:
    del mtime_ns
    df = pd.read_csv(path)
    _validate_processed_grid_line_flow_history(df)
    return df


@lru_cache(maxsize=4)
def _summarize_processed_grid_line_flow_history_cached(
    path: str,
    mtime_ns: int,
) -> tuple[tuple[str, object], ...]:
    del mtime_ns
    df = pd.read_csv(
        path,
        usecols=["timestamp", "line_id", "utilization", "status", "risk_level", "source"],
    )
    if df.empty:
        raise ValueError("processed GridLine flow history가 비어 있습니다.")
    missing = {
        "timestamp",
        "line_id",
        "utilization",
        "status",
        "risk_level",
        "source",
    } - set(df.columns)
    if missing:
        raise ValueError(f"processed GridLine flow history 컬럼이 부족합니다: {sorted(missing)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["utilization"] = pd.to_numeric(df["utilization"], errors="coerce")
    if df["timestamp"].isna().any() or df["utilization"].isna().any():
        raise ValueError("processed GridLine flow history 요약 중 timestamp/utilization 파싱에 실패했습니다.")

    summary = {
        "line_label_source": _portable_path(Path(path)),
        "processed_line_history_used": True,
        "processed_line_history_role": "dc_power_flow_evaluation_label",
        "line_flow_history_rows": int(len(df)),
        "line_flow_history_timestamp_count": int(df["timestamp"].nunique()),
        "line_flow_history_line_count": int(df["line_id"].nunique()),
        "line_flow_history_start": df["timestamp"].min().isoformat(),
        "line_flow_history_end": df["timestamp"].max().isoformat(),
        "line_flow_history_max_utilization": round(float(df["utilization"].max()), 6),
        "line_flow_history_status_counts": {
            str(key): int(value)
            for key, value in df["status"].value_counts().to_dict().items()
        },
        "line_flow_history_risk_counts": {
            str(key): int(value)
            for key, value in df["risk_level"].value_counts().to_dict().items()
        },
        "line_flow_history_generation_dispatch": "grid_total_load_mw x generation_weight",
        "line_flow_history_source": str(df["source"].dropna().iloc[0]),
    }
    return tuple(summary.items())


@lru_cache(maxsize=4)
def _load_model_evaluation_summary_cached(
    path: str,
    mtime_ns: int,
) -> pd.DataFrame:
    del mtime_ns
    df = pd.read_csv(path)
    _validate_model_evaluation_summary(df)
    return df


def _validate_processed_grid_node_history(
    df: pd.DataFrame,
    *,
    min_timestamps: int,
) -> None:
    if df.empty:
        raise ValueError("processed GridNode load history가 비어 있습니다.")
    _validate_columns(
        df,
        _GRID_NODE_LOAD_HISTORY_COLUMNS,
        "processed GridNode load history",
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("processed GridNode load history timestamp에 결측값이 있습니다.")
    if df[["timestamp", "node_id"]].duplicated().any():
        raise ValueError("processed GridNode load history timestamp/node_id 조합이 중복되었습니다.")
    if df["timestamp"].nunique() < int(min_timestamps):
        raise ValueError(
            f"processed GridNode load history는 최소 {min_timestamps}개 timestamp가 필요합니다."
        )
    if df["node_id"].isna().any() or (df["node_id"].astype(str).str.strip() == "").any():
        raise ValueError("processed GridNode load history node_id에 빈 값이 있습니다.")

    for column in (
        "load_mw",
        "generation_mw",
        "net_injection_mw",
        "load_weight",
        "generation_weight",
    ):
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[column].isna().any():
            raise ValueError(f"processed GridNode load history {column}에 숫자가 아닌 값이 있습니다.")
    if (df["load_mw"] < 0.0).any() or (df["generation_mw"] < 0.0).any():
        raise ValueError("processed GridNode load history load/generation은 음수일 수 없습니다.")


def _validate_processed_grid_line_flow_history(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("processed GridLine flow history가 비어 있습니다.")
    _validate_columns(
        df,
        _GRID_LINE_FLOW_HISTORY_COLUMNS,
        "processed GridLine flow history",
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("processed GridLine flow history timestamp에 결측값이 있습니다.")
    if df[["timestamp", "line_id"]].duplicated().any():
        raise ValueError("processed GridLine flow history timestamp/line_id 조합이 중복되었습니다.")
    if df["line_id"].isna().any() or (df["line_id"].astype(str).str.strip() == "").any():
        raise ValueError("processed GridLine flow history line_id에 빈 값이 있습니다.")

    for column in ("flow_mw", "abs_flow_mw", "capacity_mw", "utilization", "loss_mw"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
        if df[column].isna().any():
            raise ValueError(f"processed GridLine flow history {column}에 숫자가 아닌 값이 있습니다.")
    if (df["capacity_mw"] <= 0.0).any():
        raise ValueError("processed GridLine flow history capacity_mw는 0보다 커야 합니다.")
    if (df["utilization"] < 0.0).any():
        raise ValueError("processed GridLine flow history utilization은 음수일 수 없습니다.")


def _validate_model_evaluation_summary(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("model evaluation summary가 비어 있습니다.")
    missing = set(_MODEL_EVALUATION_REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"model evaluation summary 컬럼이 부족합니다: {sorted(missing)}")
    if df["model"].isna().any() or (df["model"].astype(str).str.strip() == "").any():
        raise ValueError("model evaluation summary model에 빈 값이 있습니다.")
    if df["model"].astype(str).duplicated().any():
        raise ValueError("model evaluation summary model 값이 중복되었습니다.")

    for column in (
        "mae_mw",
        "rmse_mw",
        "mape_pct",
        "line_utilization_mae_pp",
        "line_utilization_rmse_pp",
        "sample_count",
        "line_sample_count",
        "forecast_start_count",
    ):
        if column not in df.columns:
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.isna().any():
            raise ValueError(f"model evaluation summary {column}에 숫자가 아닌 값이 있습니다.")
        if (numeric < 0.0).any():
            raise ValueError(f"model evaluation summary {column}은 음수일 수 없습니다.")


def _validate_columns(
    df: pd.DataFrame,
    expected_columns: list[str],
    label: str,
) -> None:
    if list(df.columns) != expected_columns:
        raise ValueError(
            f"{label} 헤더가 계약과 다릅니다. expected={expected_columns}, actual={list(df.columns)}"
        )


def _ensure_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{path} 파일이 없습니다.")


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _parse_nodes(df: pd.DataFrame) -> list[GridNode]:
    nodes: list[GridNode] = []
    for index, row in df.iterrows():
        node_type = _required_str(row, "node_type", index)
        if node_type not in {
            "power_plant",
            "transmission_tower",
            "user_power_plant",
            "user_transmission_tower",
        }:
            raise ValueError(f"nodes.csv {index + 2}행 node_type이 잘못되었습니다: {node_type}")
        nodes.append(
            GridNode(
                node_id=_required_str(row, "node_id", index),
                node_name=_required_str(row, "node_name", index),
                node_type=node_type,  # type: ignore[arg-type]
                latitude=_required_float(row, "latitude", index),
                longitude=_required_float(row, "longitude", index),
                voltage_kv=_positive_float(row, "voltage_kv", index),
                region=_optional_str(row, "region"),
                base_load_mw=_optional_float(row, "base_load_mw", default=0.0) or 0.0,
                elevation_m=_optional_float(row, "elevation_m"),
                coordinate_system=_required_str(row, "coordinate_system", index),
                elevation_source=_required_str(row, "elevation_source", index),
                source=_parse_source(row, index),
                source_id=_optional_str(row, "source_id"),
                metadata={"csv_row": int(index) + 2},
            )
        )
    return nodes


def _parse_lines(df: pd.DataFrame, node_by_id: dict[str, GridNode]) -> list[GridLine]:
    lines: list[GridLine] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for index, row in df.iterrows():
        line_id = _required_str(row, "line_id", index)
        if line_id in seen_ids:
            raise ValueError(f"lines.csv에 중복 line_id가 있습니다: {line_id}")
        from_node_id = _required_str(row, "from_node_id", index)
        to_node_id = _required_str(row, "to_node_id", index)
        if from_node_id not in node_by_id or to_node_id not in node_by_id:
            raise ValueError(f"{line_id}가 존재하지 않는 GridNode를 참조합니다.")
        if from_node_id == to_node_id:
            raise ValueError(f"{line_id}의 from/to 노드가 같습니다.")
        pair = tuple(sorted((from_node_id, to_node_id)))
        if pair in seen_pairs:
            raise ValueError(f"lines.csv에 중복 양방향 선로 쌍이 있습니다: {pair}")
        seen_ids.add(line_id)
        seen_pairs.add(pair)

        status = _required_str(row, "status", index)
        if status not in {"active", "planned", "candidate", "out_of_service"}:
            raise ValueError(f"lines.csv {index + 2}행 status가 잘못되었습니다: {status}")
        lines.append(
            GridLine(
                line_id=line_id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                voltage_kv=_positive_float(row, "voltage_kv", index),
                capacity_mw=_positive_float(row, "capacity_mw", index),
                reactance_pu=_positive_float(row, "reactance_pu", index),
                distance_km=_positive_float(row, "distance_km", index),
                resistance_pu=_optional_float(row, "resistance_pu", default=0.0) or 0.0,
                loss_factor=_optional_float(row, "loss_factor", default=0.0) or 0.0,
                terrain_risk=_bounded_optional_float(row, "terrain_risk", index, default=0.0) or 0.0,
                is_bidirectional=_required_bool(row, "is_bidirectional", index),
                status=status,  # type: ignore[arg-type]
                source=_parse_source(row, index),
                metadata={"csv_row": int(index) + 2, "coordinate_system": "EPSG:4326"},
            )
        )
    return lines


def _parse_plants(df: pd.DataFrame, node_by_id: dict[str, GridNode]) -> list[PowerPlantSpec]:
    plants: list[PowerPlantSpec] = []
    seen_ids: set[str] = set()
    seen_node_ids: set[str] = set()
    for index, row in df.iterrows():
        plant_id = _required_str(row, "plant_id", index)
        node_id = _required_str(row, "node_id", index)
        node = node_by_id.get(node_id)
        if node is None:
            raise ValueError(f"{plant_id}가 존재하지 않는 GridNode를 참조합니다.")
        if node.node_type not in {"power_plant", "user_power_plant"}:
            raise ValueError(f"{plant_id}의 node_id={node_id}는 발전소 노드가 아닙니다.")
        if plant_id in seen_ids or node_id in seen_node_ids:
            raise ValueError(f"plants.csv에 중복 발전소 ID 또는 node_id가 있습니다: {plant_id}/{node_id}")
        seen_ids.add(plant_id)
        seen_node_ids.add(node_id)
        plants.append(
            PowerPlantSpec(
                plant_id=plant_id,
                plant_name=_required_str(row, "plant_name", index),
                node_id=node_id,
                capacity_mw=_positive_float(row, "capacity_mw", index),
                fuel_type=_required_str(row, "fuel_type", index),
                min_output_mw=_required_float(row, "min_output_mw", index),
                max_output_mw=_positive_float(row, "max_output_mw", index),
                ramp_rate_mw_per_h=_optional_float(row, "ramp_rate_mw_per_h"),
                availability=_bounded_optional_float(row, "availability", index, default=1.0) or 1.0,
                operating_cost=_optional_float(row, "operating_cost"),
                emission_factor=_optional_float(row, "emission_factor"),
                source=_parse_source(row, index),
                metadata={"csv_row": int(index) + 2},
            )
        )
    return plants


def _parse_towers(
    df: pd.DataFrame,
    node_by_id: dict[str, GridNode],
) -> list[TransmissionTowerSpec]:
    towers: list[TransmissionTowerSpec] = []
    seen_ids: set[str] = set()
    seen_node_ids: set[str] = set()
    for index, row in df.iterrows():
        tower_id = _required_str(row, "tower_id", index)
        node_id = _required_str(row, "node_id", index)
        node = node_by_id.get(node_id)
        if node is None:
            raise ValueError(f"{tower_id}가 존재하지 않는 GridNode를 참조합니다.")
        if node.node_type not in {"transmission_tower", "user_transmission_tower"}:
            raise ValueError(f"{tower_id}의 node_id={node_id}는 송전탑 노드가 아닙니다.")
        if tower_id in seen_ids or node_id in seen_node_ids:
            raise ValueError(f"tower_candidates.csv에 중복 송전탑 ID 또는 node_id가 있습니다: {tower_id}/{node_id}")
        seen_ids.add(tower_id)
        seen_node_ids.add(node_id)
        towers.append(
            TransmissionTowerSpec(
                tower_id=tower_id,
                tower_name=_required_str(row, "tower_name", index),
                node_id=node_id,
                voltage_kv=_positive_float(row, "voltage_kv", index),
                elevation_m=_optional_float(row, "elevation_m"),
                height_m=_optional_float(row, "height_m"),
                terrain_slope_deg=_optional_float(row, "terrain_slope_deg"),
                install_cost_billion=_optional_float(row, "install_cost_billion"),
                land_type=_optional_str(row, "land_type"),
                environment_risk=_bounded_optional_float(row, "environment_risk", index, default=0.0) or 0.0,
                policy_risk=_bounded_optional_float(row, "policy_risk", index, default=0.0) or 0.0,
                accessibility_score=_bounded_optional_float(row, "accessibility_score", index),
                nearest_node_id=_optional_str(row, "nearest_node_id"),
                source=_parse_source(row, index),
                metadata={"csv_row": int(index) + 2},
            )
        )
    return towers


def _connectivity_warnings(nodes: list[GridNode], lines: list[GridLine]) -> list[str]:
    if not nodes:
        return ["Grid CSV에 노드가 없습니다."]
    neighbors: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    for line in lines:
        if line.from_node_id in neighbors and line.to_node_id in neighbors:
            neighbors[line.from_node_id].add(line.to_node_id)
            neighbors[line.to_node_id].add(line.from_node_id)
    start = nodes[0].node_id
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for neighbor in neighbors[current]:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    missing = sorted(set(neighbors) - seen)
    if missing:
        return [f"Grid CSV 그래프가 연결되지 않았습니다. 미연결 노드: {', '.join(missing)}"]
    return []


def _required_str(row: pd.Series, field_name: str, index: int) -> str:
    value = str(row[field_name]).strip()
    if not value:
        raise ValueError(f"{field_name}는 필수입니다. CSV {index + 2}행")
    return value


def _optional_str(row: pd.Series, field_name: str) -> str:
    return str(row[field_name]).strip()


def _required_float(row: pd.Series, field_name: str, index: int) -> float:
    raw_value = str(row[field_name]).strip()
    if not raw_value:
        raise ValueError(f"{field_name}는 필수 숫자입니다. CSV {index + 2}행")
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{field_name}는 숫자여야 합니다. CSV {index + 2}행") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field_name}는 유한한 숫자여야 합니다. CSV {index + 2}행")
    return value


def _positive_float(row: pd.Series, field_name: str, index: int) -> float:
    value = _required_float(row, field_name, index)
    if value <= 0.0:
        raise ValueError(f"{field_name}는 0보다 커야 합니다. CSV {index + 2}행")
    return value


def _optional_float(
    row: pd.Series,
    field_name: str,
    default: float | None = None,
) -> float | None:
    raw_value = str(row[field_name]).strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{field_name}는 숫자여야 합니다.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{field_name}는 유한한 숫자여야 합니다.")
    return value


def _bounded_optional_float(
    row: pd.Series,
    field_name: str,
    index: int,
    default: float | None = None,
) -> float | None:
    value = _optional_float(row, field_name, default=default)
    if value is None:
        return None
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{field_name}는 0~1 범위여야 합니다. CSV {index + 2}행")
    return value


def _required_bool(row: pd.Series, field_name: str, index: int) -> bool:
    raw_value = str(row[field_name]).strip().lower()
    if raw_value in {"true", "1", "yes", "y"}:
        return True
    if raw_value in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"{field_name}는 true/false여야 합니다. CSV {index + 2}행")


def _parse_source(row: pd.Series, index: int) -> str:
    source = _required_str(row, "source", index)
    if source not in {"default_asset", "user_installation", "csv", "fallback_mock", "legacy"}:
        raise ValueError(f"source가 GridDataSource 계약과 다릅니다. CSV {index + 2}행: {source}")
    return source


def _resolve_created_at(created_at: datetime | None) -> datetime:
    if created_at is None:
        created_at = datetime.now()
    if not isinstance(created_at, datetime):
        raise TypeError("created_at는 datetime 인스턴스여야 합니다.")
    return created_at.replace(minute=0, second=0, microsecond=0)
