# 예측 워크플로와 결과 처리 흐름을 조율한다.
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import numpy as np
import pandas as pd

from src.data.grid_builder import DEFAULT_GRID_TOTAL_LOAD_MW
from src.data.loaders import DEFAULT_GRID_CSV_DIR, load_grid_dataset_or_default
from src.data.schemas import (
    GridDataset,
    GridNode,
    GridPowerProfile,
    HourlyLoadPrediction,
    InstallationPoint,
    PredictionResult,
    RiskLine,
    ScenarioContext,
)
from src.services.result_metadata import (
    build_fallback_info,
    build_fallback_warning,
    build_no_fallback_info,
    build_source_warning,
)


def _hourly_factor(hour: int, day_of_week: int) -> float:
    """시간대·요일별 부하 배율 (0.55 ~ 1.0).

    이중 피크 패턴: 오전 10시 + 오후 14시
    주말은 평일 대비 85% 수준
    """
    weekend_coef = 0.85 if day_of_week >= 5 else 1.0
    morning = 0.6 * np.exp(-((hour - 10) ** 2) / 8.0)
    afternoon = 0.4 * np.exp(-((hour - 14) ** 2) / 10.0)
    base = 0.55 + 0.30 * (morning + afternoon)
    return float(np.clip(base * weekend_coef, 0.50, 1.00))


class PredictionService:
    """예측 워크플로와 결과 처리 흐름을 조율한다.

    1주차: run_mock_prediction() 사용 (합성 데이터 기반, API 없음)
    2주차 이후: generate_load_history() → feature_builder → lstm/baseline 연결
    """

    def generate_load_history(
        self,
        end_ts: datetime,
        hours: int = 72,
        load_scale: float = 1.0,
        rng_seed: int = 42,
        grid_dataset: GridDataset | None = None,
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> pd.DataFrame:
        """과거 hours 시간의 합성 부하 이력을 DataFrame 으로 반환한다.

        컬럼: timestamp, bus_id, bus_name, load_mw, generation_mw
        feature_builder.build_feature_vector() 의 load_df 입력 계약을 만족한다.
        bus_id 컬럼명은 예측 엔진 호환을 위해 유지하지만 값은 새 Grid node_id다.
        """
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            user_installations=user_installations,
            created_at=end_ts,
        )
        return self._generate_grid_load_history(
            dataset=dataset,
            end_ts=end_ts,
            hours=hours,
            load_scale=load_scale,
            rng_seed=rng_seed,
        )

    def run_mock_prediction(
        self,
        load_scale: float = 1.0,
        created_at: datetime | None = None,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> PredictionResult:
        """합성 패턴 기반 24시간 예측 결과를 반환한다.

        Parameters
        ----------
        load_scale     : 부하 배율 (1.0 = 기본, 1.2 = 20% 증가)
        created_at     : 공통 서비스 인터페이스 기준 시각
        forecast_start : 기존 호출부 호환용 예측 기준 시각
        """
        now = (created_at or forecast_start or datetime.now()).replace(
            minute=0, second=0, microsecond=0
        )
        resolved_scenario = self._resolve_scenario(scenario, now)
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=now,
        )
        predictions = self._generate_grid_predictions(now, load_scale, dataset)
        risk_lines = self._compute_grid_risk_lines(predictions, load_scale, dataset)
        summary = self._build_summary(now, predictions, risk_lines)

        return PredictionResult(
            scenario_id=resolved_scenario.scenario_id,
            created_at=now,
            load_scale=load_scale,
            forecast_horizon_h=24,
            predictions=predictions,
            risk_lines=risk_lines,
            summary=summary,
            source="mock",
            scenario=resolved_scenario,
            warnings=self._build_warnings(),
            fallback=build_fallback_info(
                mode="mock_data",
                reason="실제 예측 모델 대신 PredictionService의 mock 패턴 예측 결과를 사용합니다.",
                primary_path="GridDataset -> src.engine.forecast.feature_builder -> baseline/lstm/gnn forecaster",
                active_path="src.services.prediction_service.PredictionService.run_mock_prediction",
            ),
            metadata=self._build_grid_metadata(
                dataset,
                prediction_nodes=self._prediction_nodes(dataset),
                risk_lines=risk_lines,
                graph_edge_source="GridLine",
            ),
        )

    def run_baseline_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> PredictionResult:
        """KPX 실데이터 기반 baseline 예측 결과를 반환한다.

        Parameters
        ----------
        raw_dir        : sukub*.csv 가 있는 디렉터리 경로
        load_scale     : 부하 배율
        forecast_start : 예측 기준 시각 (None 이면 현재 시각)
        """
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        now = self._resolve_forecast_start(load_df, forecast_start)
        resolved_scenario = self._resolve_scenario(scenario, now)

        load_df = self._apply_load_scale(load_df, load_scale)
        predictions = self._predict_baseline(
            load_df=load_df,
            forecast_start=now,
        )

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="baseline",
            warnings=[],
            grid_dataset=dataset,
            metadata={
                "history_source": "KPX CSV redistributed to GridNode",
                "legacy_bus_source": False,
            },
        )

    def run_lstm_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> PredictionResult:
        """LSTM 학습/추론 기반 24시간 예측 결과를 반환한다.

        Parameters
        ----------
        raw_dir        : sukub*.csv 가 있는 디렉터리 경로
        load_scale     : 부하 배율
        forecast_start : 예측 기준 시각 (None 이면 데이터 마지막 시각)
        retrain        : True 이면 저장된 모델 무시하고 재학습
        epochs         : 재학습 시 에포크 수
        """
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        data_end = load_df["timestamp"].max().replace(minute=0, second=0, microsecond=0)
        now = (forecast_start or data_end).replace(minute=0, second=0, microsecond=0)
        if now > data_end:
            now = data_end
        resolved_scenario = self._resolve_scenario(scenario, now)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )
        try:
            predictions, warnings = self._predict_lstm(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                retrain=retrain,
                epochs=epochs,
            )
        except Exception as exc:  # noqa: BLE001
            baseline_result = self.run_baseline_prediction(
                raw_dir=raw_dir,
                load_scale=load_scale,
                forecast_start=now,
                scenario=resolved_scenario,
                grid_dataset=dataset,
                grid_dir=grid_dir,
                user_installations=user_installations,
            )
            baseline_result.summary = (
                "LSTM 예측 실패로 baseline 결과를 사용합니다. "
                f"{baseline_result.summary}"
            )
            baseline_result.warnings = [
                build_fallback_warning("PredictionService", "baseline_model"),
                f"LSTM 실패: {_summarize_prediction_error(exc)}",
                *baseline_result.warnings,
            ]
            baseline_result.fallback = build_fallback_info(
                mode="baseline_model",
                reason="Grid node_id 기준 LSTM 예측이 실패해 baseline 예측으로 전환했습니다.",
                primary_path="src.engine.forecast.lstm_forecaster",
                active_path="src.services.prediction_service.PredictionService.run_baseline_prediction",
            )
            baseline_result.metadata["lstm_fallback_error"] = _summarize_prediction_error(exc)
            baseline_result.metadata["requires_lstm_retrain_for_grid_nodes"] = True
            return baseline_result

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="lstm",
            warnings=warnings,
            grid_dataset=dataset,
            metadata={
                "history_source": "KPX CSV redistributed to GridNode",
                "legacy_bus_source": False,
                "requires_lstm_retrain_for_grid_nodes": retrain,
            },
        )

    def run_gnn_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> PredictionResult:
        """그래프 기반 최소 GNN 예측 결과를 반환한다."""
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        now = self._resolve_forecast_start(load_df, forecast_start)
        resolved_scenario = self._resolve_scenario(scenario, now)

        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )
        predictions = self._predict_gnn(
            history_df=history_df,
            forecast_start=now,
            target_features=target_features,
            grid_dataset=dataset,
        )

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="gnn",
            warnings=[],
            grid_dataset=dataset,
            metadata={
                "history_source": "KPX CSV redistributed to GridNode",
                "graph_edge_source": "GridLine",
                "legacy_bus_source": False,
            },
        )

    def run_neural_gnn_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
        model_dir: str | None = None,
    ) -> PredictionResult:
        """PyTorch 기반 Neural GNN(beta) 예측 결과를 반환한다."""
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        now = self._resolve_forecast_start(load_df, forecast_start)
        resolved_scenario = self._resolve_scenario(scenario, now)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )

        try:
            predictions, neural_metadata = self._predict_neural_gnn(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                grid_dataset=dataset,
                retrain=retrain,
                epochs=epochs,
                model_dir=model_dir,
            )
        except Exception as exc:  # noqa: BLE001
            fallback_result = self.run_gnn_prediction(
                raw_dir=raw_dir,
                load_scale=load_scale,
                forecast_start=now,
                scenario=resolved_scenario,
                grid_dataset=dataset,
                grid_dir=grid_dir,
                user_installations=user_installations,
            )
            fallback_result.summary = (
                "Neural GNN 예측 실패로 기존 graph-aware GNN 결과를 사용합니다. "
                f"{fallback_result.summary}"
            )
            fallback_result.warnings = [
                build_fallback_warning("PredictionService", "graph_model"),
                f"Neural GNN 실패: {_summarize_prediction_error(exc)}",
                *fallback_result.warnings,
            ]
            fallback_result.fallback = build_fallback_info(
                mode="graph_model",
                reason="학습형 Neural GNN 경로가 실패해 기존 graph-aware GNN 예측으로 전환했습니다.",
                primary_path="src.engine.forecast.neural_gnn_forecaster",
                active_path="src.engine.forecast.gnn_forecaster",
            )
            fallback_result.metadata["neural_gnn_fallback_error"] = _summarize_prediction_error(exc)
            fallback_result.metadata["neural_gnn_beta_requested"] = True
            return fallback_result

        return self._build_prediction_result(
            scenario=resolved_scenario,
            created_at=now,
            load_scale=load_scale,
            predictions=predictions,
            source="neural_gnn",
            warnings=[],
            grid_dataset=dataset,
            metadata={
                "history_source": "KPX CSV redistributed to GridNode",
                "graph_edge_source": "GridLine",
                "legacy_bus_source": False,
                "model_type": "neural_gnn",
                "deep_learning": True,
                "framework": "torch",
                **neural_metadata,
            },
        )

    def run_hybrid_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
    ) -> PredictionResult:
        """LSTM + GNN 병렬 조합 예측을 반환하고 실패 시 baseline 으로 전환한다."""
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        now = self._resolve_forecast_start(load_df, forecast_start)
        resolved_scenario = self._resolve_scenario(scenario, now)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )

        lstm_predictions: list[HourlyLoadPrediction] | None = None
        gnn_predictions: list[HourlyLoadPrediction] | None = None
        lstm_warnings: list[str] = []
        branch_errors: list[str] = []

        try:
            lstm_predictions, lstm_warnings = self._predict_lstm(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                retrain=retrain,
                epochs=epochs,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"LSTM 실패: {_summarize_prediction_error(exc)}")

        try:
            gnn_predictions = self._predict_gnn(
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                grid_dataset=dataset,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"GNN 실패: {_summarize_prediction_error(exc)}")

        if lstm_predictions is not None and gnn_predictions is not None:
            predictions = _combine_prediction_lists(
                primary=lstm_predictions,
                secondary=gnn_predictions,
                primary_weight=0.65,
                secondary_weight=0.35,
            )
            warnings = [
                build_source_warning("PredictionService", "hybrid"),
                "LSTM 65% + GNN 35% 가중 평균으로 병렬 조합 예측을 사용합니다.",
            ]
            warnings.extend(f"LSTM: {warning}" for warning in lstm_warnings)

            return self._build_prediction_result(
                scenario=resolved_scenario,
                created_at=now,
                load_scale=load_scale,
                predictions=predictions,
                source="hybrid",
                warnings=warnings,
                grid_dataset=dataset,
                metadata={
                    "history_source": "KPX CSV redistributed to GridNode",
                    "graph_edge_source": "GridLine",
                    "legacy_bus_source": False,
                },
            )

        baseline_result = self.run_baseline_prediction(
            raw_dir=raw_dir,
            load_scale=load_scale,
            forecast_start=now,
            scenario=resolved_scenario,
            grid_dataset=dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
        )
        baseline_result.summary = (
            "LSTM+GNN 병렬 예측 실패로 baseline 결과를 사용합니다. "
            f"{baseline_result.summary}"
        )
        baseline_result.warnings = [
            build_fallback_warning("PredictionService", "baseline_model"),
            *branch_errors,
            *baseline_result.warnings,
        ]
        baseline_result.fallback = build_fallback_info(
            mode="baseline_model",
            reason="LSTM+GNN 병렬 예측 중 하나 이상이 실패해 baseline 예측으로 전환했습니다.",
            primary_path="src.engine.forecast.lstm_forecaster + src.engine.forecast.gnn_forecaster",
            active_path="src.services.prediction_service.PredictionService.run_baseline_prediction",
        )
        return baseline_result

    def run_hybrid_neural_gnn_prediction(
        self,
        raw_dir: str,
        load_scale: float = 1.0,
        forecast_start: datetime | None = None,
        scenario: ScenarioContext | None = None,
        retrain: bool = False,
        epochs: int = 20,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
        model_dir: str | None = None,
    ) -> PredictionResult:
        """LSTM + Neural GNN(beta) 병렬 조합 예측을 반환한다."""
        dataset = self._resolve_grid_dataset(
            grid_dataset=grid_dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
            created_at=forecast_start,
        )
        load_df = self._load_grid_history(raw_dir, dataset)
        now = self._resolve_forecast_start(load_df, forecast_start)
        resolved_scenario = self._resolve_scenario(scenario, now)
        history_df = self._apply_load_scale(load_df, load_scale)
        target_features = self._build_target_features(
            load_df=history_df,
            forecast_start=now,
        )

        lstm_predictions: list[HourlyLoadPrediction] | None = None
        neural_predictions: list[HourlyLoadPrediction] | None = None
        neural_metadata: dict[str, object] = {}
        lstm_warnings: list[str] = []
        branch_errors: list[str] = []

        try:
            lstm_predictions, lstm_warnings = self._predict_lstm(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                retrain=retrain,
                epochs=epochs,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"LSTM 실패: {_summarize_prediction_error(exc)}")

        try:
            neural_predictions, neural_metadata = self._predict_neural_gnn(
                training_df=load_df,
                history_df=history_df,
                forecast_start=now,
                target_features=target_features,
                grid_dataset=dataset,
                retrain=retrain,
                epochs=epochs,
                model_dir=model_dir,
            )
        except Exception as exc:  # noqa: BLE001
            branch_errors.append(f"Neural GNN 실패: {_summarize_prediction_error(exc)}")

        if lstm_predictions is not None and neural_predictions is not None:
            predictions = _combine_prediction_lists(
                primary=lstm_predictions,
                secondary=neural_predictions,
                primary_weight=0.65,
                secondary_weight=0.35,
            )
            warnings = [
                build_source_warning("PredictionService", "hybrid_neural_gnn"),
                "LSTM 65% + Neural GNN 35% 가중 평균으로 병렬 조합 예측을 사용합니다.",
            ]
            warnings.extend(f"LSTM: {warning}" for warning in lstm_warnings)

            return self._build_prediction_result(
                scenario=resolved_scenario,
                created_at=now,
                load_scale=load_scale,
                predictions=predictions,
                source="hybrid_neural_gnn",
                warnings=warnings,
                grid_dataset=dataset,
                metadata={
                    "history_source": "KPX CSV redistributed to GridNode",
                    "graph_edge_source": "GridLine",
                    "legacy_bus_source": False,
                    "model_type": "lstm_neural_gnn_hybrid",
                    "deep_learning": True,
                    "framework": "tensorflow+torch",
                    "hybrid_primary": "lstm",
                    "hybrid_secondary": "neural_gnn",
                    "hybrid_primary_weight": 0.65,
                    "hybrid_secondary_weight": 0.35,
                    "training_history": neural_metadata.get("training_history", []),
                    **{
                        f"neural_gnn_{key}": value
                        for key, value in neural_metadata.items()
                        if key != "training_history"
                    },
                },
            )

        baseline_result = self.run_baseline_prediction(
            raw_dir=raw_dir,
            load_scale=load_scale,
            forecast_start=now,
            scenario=resolved_scenario,
            grid_dataset=dataset,
            grid_dir=grid_dir,
            user_installations=user_installations,
        )
        baseline_result.summary = (
            "LSTM+Neural GNN 병렬 예측 실패로 baseline 결과를 사용합니다. "
            f"{baseline_result.summary}"
        )
        baseline_result.warnings = [
            build_fallback_warning("PredictionService", "baseline_model"),
            *branch_errors,
            *baseline_result.warnings,
        ]
        baseline_result.fallback = build_fallback_info(
            mode="baseline_model",
            reason="LSTM+Neural GNN 병렬 예측 중 하나 이상이 실패해 baseline 예측으로 전환했습니다.",
            primary_path="src.engine.forecast.lstm_forecaster + src.engine.forecast.neural_gnn_forecaster",
            active_path="src.services.prediction_service.PredictionService.run_baseline_prediction",
        )
        baseline_result.metadata["hybrid_neural_gnn_requested"] = True
        return baseline_result

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _resolve_grid_dataset(
        self,
        *,
        grid_dataset: GridDataset | None = None,
        grid_dir: str | None = str(DEFAULT_GRID_CSV_DIR),
        user_installations: Iterable[InstallationPoint] | None = None,
        created_at: datetime | None = None,
    ) -> GridDataset:
        if grid_dataset is not None:
            return grid_dataset
        return load_grid_dataset_or_default(
            grid_dir,
            user_installations=user_installations,
            created_at=created_at,
            load_scale=1.0,
            total_load_mw=DEFAULT_GRID_TOTAL_LOAD_MW,
        )

    def _prediction_nodes(self, dataset: GridDataset) -> list[GridNode]:
        profile_by_node_id = self._profile_by_node_id(dataset)
        load_nodes = [
            node
            for node in dataset.nodes
            if (
                max(0.0, node.base_load_mw) > 0.0
                or profile_by_node_id.get(node.node_id, GridPowerProfile(node.node_id)).load_mw > 0.0
            )
        ]
        if load_nodes:
            return sorted(load_nodes, key=lambda node: node.node_id)
        return sorted(dataset.nodes, key=lambda node: node.node_id)

    def _profile_by_node_id(self, dataset: GridDataset) -> dict[str, GridPowerProfile]:
        return {
            profile.node_id: profile
            for profile in dataset.power_profiles
        }

    def _node_name_map(self, dataset: GridDataset) -> dict[str, str]:
        return {
            node.node_id: node.node_name
            for node in dataset.nodes
        }

    def _load_grid_history(
        self,
        raw_dir: str,
        dataset: GridDataset,
    ) -> pd.DataFrame:
        from src.data.adapters.public_data_adapter import load_kpx_national_hourly

        national_df = load_kpx_national_hourly(raw_dir)
        return self._redistribute_kpx_history_to_grid(national_df, dataset)

    def _redistribute_kpx_history_to_grid(
        self,
        national_df: pd.DataFrame,
        dataset: GridDataset,
    ) -> pd.DataFrame:
        if national_df.empty:
            raise ValueError("KPX 부하 이력이 비어 있습니다.")

        df = national_df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if "demand_mw" in df.columns:
            national = (
                df.groupby("timestamp", as_index=False)
                .agg(load_mw=("demand_mw", "mean"))
                .sort_values("timestamp")
            )
        elif "load_mw" in df.columns:
            national = (
                df.groupby("timestamp", as_index=False)
                .agg(load_mw=("load_mw", "sum"))
                .sort_values("timestamp")
            )
        else:
            raise ValueError("KPX 이력에는 demand_mw 또는 load_mw 컬럼이 필요합니다.")
        median_load = float(national["load_mw"].median())
        scale_to_grid = DEFAULT_GRID_TOTAL_LOAD_MW / median_load if median_load > 0.0 else 1.0
        prediction_nodes = self._prediction_nodes(dataset)
        weights = _prediction_node_load_weights(dataset, prediction_nodes)
        profiles = self._profile_by_node_id(dataset)
        rows: list[dict] = []

        for _, row in national.iterrows():
            grid_total_load = max(0.0, float(row["load_mw"]) * scale_to_grid)
            for node in prediction_nodes:
                profile = profiles.get(node.node_id)
                rows.append(
                    {
                        "timestamp": row["timestamp"],
                        "bus_id": node.node_id,
                        "bus_name": node.node_name,
                        "load_mw": round(grid_total_load * weights[node.node_id], 1),
                        "generation_mw": round(profile.generation_mw if profile else 0.0, 1),
                    }
                )

        history = pd.DataFrame(rows)
        history.attrs["grid_load_scale_to_default_total"] = scale_to_grid
        return history

    def _generate_grid_load_history(
        self,
        *,
        dataset: GridDataset,
        end_ts: datetime,
        hours: int = 72,
        load_scale: float = 1.0,
        rng_seed: int = 42,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(rng_seed)
        start_ts = end_ts - timedelta(hours=hours)
        timestamps = [start_ts + timedelta(hours=h) for h in range(hours)]
        prediction_nodes = self._prediction_nodes(dataset)
        profiles = self._profile_by_node_id(dataset)
        weights = _prediction_node_load_weights(dataset, prediction_nodes)

        rows: list[dict] = []
        for ts in timestamps:
            factor = _hourly_factor(ts.hour, ts.weekday())
            total_load_mw = DEFAULT_GRID_TOTAL_LOAD_MW * load_scale * factor
            for node in prediction_nodes:
                profile = profiles.get(node.node_id)
                noise = float(rng.normal(0, 0.025))
                load_mw = total_load_mw * weights[node.node_id] * (1 + noise)
                rows.append(
                    {
                        "timestamp": ts,
                        "bus_id": node.node_id,
                        "bus_name": node.node_name,
                        "load_mw": round(max(0.0, load_mw), 1),
                        "generation_mw": round(profile.generation_mw if profile else 0.0, 1),
                    }
                )
        return pd.DataFrame(rows)

    def _generate_grid_predictions(
        self,
        now: datetime,
        load_scale: float,
        dataset: GridDataset,
    ) -> list[HourlyLoadPrediction]:
        rng = np.random.default_rng(seed=7)
        prediction_nodes = self._prediction_nodes(dataset)
        weights = _prediction_node_load_weights(dataset, prediction_nodes)
        predictions: list[HourlyLoadPrediction] = []

        for h in range(1, 25):
            ts = now + timedelta(hours=h)
            factor = _hourly_factor(ts.hour, ts.weekday())
            total_load_mw = DEFAULT_GRID_TOTAL_LOAD_MW * load_scale * factor
            for node in prediction_nodes:
                noise = float(rng.normal(0, 0.022))
                pred = total_load_mw * weights[node.node_id] * (1 + noise)
                ci = pred * 0.08
                predictions.append(
                    HourlyLoadPrediction(
                        timestamp=ts,
                        bus_id=node.node_id,
                        predicted_load_mw=round(max(0.0, pred), 1),
                        confidence_lower_mw=round(max(0.0, pred - ci), 1),
                        confidence_upper_mw=round(pred + ci, 1),
                    )
                )
        return predictions

    def _compute_grid_risk_lines(
        self,
        predictions: list[HourlyLoadPrediction],
        load_scale: float,
        dataset: GridDataset,
    ) -> list[RiskLine]:
        node_name = self._node_name_map(dataset)
        load_map: dict[tuple[datetime, str], float] = {
            (p.timestamp, p.bus_id): p.predicted_load_mw
            for p in predictions
        }
        timestamps = sorted({p.timestamp for p in predictions})
        risk_lines: list[RiskLine] = []

        for line in dataset.lines:
            if line.status == "out_of_service":
                continue
            peak_util = 0.0
            peak_ts = timestamps[0] if timestamps else None
            for ts in timestamps:
                from_load = load_map.get((ts, line.from_node_id), 0.0)
                to_load = load_map.get((ts, line.to_node_id), 0.0)
                flow = _estimate_grid_line_flow_mw(from_load, to_load)
                utilization = flow / line.capacity_mw if line.capacity_mw > 0.0 else 0.0
                if utilization > peak_util:
                    peak_util = utilization
                    peak_ts = ts

            level = _classify_risk(peak_util)
            if level == "low":
                continue

            peak_h = peak_ts.hour if peak_ts is not None else 0
            from_name = node_name.get(line.from_node_id, line.from_node_id)
            to_name = node_name.get(line.to_node_id, line.to_node_id)
            risk_lines.append(
                RiskLine(
                    line_id=line.line_id,
                    from_bus=line.from_node_id,
                    to_bus=line.to_node_id,
                    from_bus_name=from_name,
                    to_bus_name=to_name,
                    peak_risk_hour=peak_h,
                    predicted_utilization=round(peak_util, 3),
                    risk_level=level,
                    explanation=_build_explanation(
                        line.line_id,
                        from_name,
                        to_name,
                        peak_util,
                        peak_h,
                        level,
                        load_scale,
                    ),
                )
            )

        return sorted(risk_lines, key=lambda r: r.predicted_utilization, reverse=True)

    def _grid_graph_edges(self, dataset: GridDataset) -> list[tuple[str, str]]:
        return [
            (line.from_node_id, line.to_node_id)
            for line in dataset.lines
            if line.status != "out_of_service"
        ]

    def _build_grid_metadata(
        self,
        dataset: GridDataset,
        *,
        prediction_nodes: list[GridNode],
        risk_lines: list[RiskLine],
        graph_edge_source: str,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "grid_dataset": dataset,
            "grid_source": dataset.source,
            "grid_stage": dataset.metadata.get("grid_stage", ""),
            "prediction_node_ids": [node.node_id for node in prediction_nodes],
            "prediction_node_count": len(prediction_nodes),
            "prediction_line_ids": [line.line_id for line in dataset.lines],
            "prediction_line_count": len(dataset.lines),
            "risk_line_ids": [line.line_id for line in risk_lines],
            "graph_edge_source": graph_edge_source,
            "graph_edge_count": len(self._grid_graph_edges(dataset)),
            "legacy_bus_source": False,
            "bus_id_field_semantics": "GridNode.node_id",
        }
        if dataset.fallback.enabled:
            metadata["grid_loader_fallback_mode"] = dataset.fallback.mode
            metadata["grid_loader_fallback_reason"] = dataset.fallback.reason
        if extra:
            metadata.update(extra)
        return metadata

    def _build_summary(
        self,
        now: datetime,
        predictions: list[HourlyLoadPrediction],
        risk_lines: list[RiskLine],
    ) -> str:
        n_critical = sum(1 for r in risk_lines if r.risk_level == "critical")
        n_high = sum(1 for r in risk_lines if r.risk_level == "high")
        n_medium = sum(1 for r in risk_lines if r.risk_level == "medium")

        hourly_total: dict[int, float] = {}
        for p in predictions:
            h = p.timestamp.hour
            hourly_total[h] = hourly_total.get(h, 0.0) + p.predicted_load_mw
        peak_h = max(hourly_total, key=hourly_total.__getitem__)
        peak_ts = now.replace(hour=peak_h) + (
            timedelta(days=1) if peak_h <= now.hour else timedelta()
        )

        parts = [f"향후 24시간 기준 부하 피크는 {peak_ts:%m/%d %H시}입니다."]
        if n_critical:
            parts.append(f"위험(critical) 선로 {n_critical}건 즉각 확인 필요.")
        if n_high:
            parts.append(f"경고(high) 선로 {n_high}건 모니터링 강화 권장.")
        if n_medium:
            parts.append(f"주의(medium) 선로 {n_medium}건.")
        if not risk_lines:
            parts.append("위험 선로 없음. 정상 운영 범위입니다.")
        return " ".join(parts)

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
            scenario_id="prediction-mock",
            title="Prediction Mock Scenario",
            description="예측 mock 서비스 기본 시나리오",
            region="South Korea",
            created_at=created_at,
            created_by="PredictionService",
        )

    def _build_warnings(self) -> list[str]:
        return [
            build_fallback_warning("PredictionService", "mock_data"),
            "실제 baseline/LSTM/GNN 모델이 연결되기 전까지 합성 패턴 기반 예측을 사용합니다.",
        ]

    def _build_prediction_result(
        self,
        *,
        scenario: ScenarioContext,
        created_at: datetime,
        load_scale: float,
        predictions: list[HourlyLoadPrediction],
        source: str,
        warnings: list[str],
        grid_dataset: GridDataset | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PredictionResult:
        dataset = grid_dataset or self._resolve_grid_dataset(created_at=created_at)
        risk_lines = self._compute_grid_risk_lines(predictions, load_scale, dataset)
        prediction_nodes = self._prediction_nodes(dataset)
        resolved_metadata = dict(metadata or {})
        if grid_dataset is None:
            resolved_metadata.setdefault(
                "grid_dataset_inferred_for_risk",
                True,
            )
            resolved_metadata.setdefault(
                "history_prediction_id_source",
                "external_prediction_list",
            )

        result_metadata = self._build_grid_metadata(
            dataset,
            prediction_nodes=prediction_nodes,
            risk_lines=risk_lines,
            graph_edge_source=str(resolved_metadata.get("graph_edge_source", "GridLine")),
            extra=resolved_metadata,
        )
        summary = self._build_summary(created_at, predictions, risk_lines)
        source_warning = build_source_warning("PredictionService", source)
        result_warnings = list(warnings)
        if source_warning not in result_warnings:
            result_warnings.insert(0, source_warning)
        return PredictionResult(
            scenario_id=scenario.scenario_id,
            created_at=created_at,
            load_scale=load_scale,
            forecast_horizon_h=24,
            predictions=predictions,
            risk_lines=risk_lines,
            summary=summary,
            source=source,
            scenario=scenario,
            warnings=result_warnings,
            fallback=build_no_fallback_info(),
            metadata=result_metadata,
        )

    def _resolve_forecast_start(
        self,
        load_df: pd.DataFrame,
        forecast_start: datetime | None,
    ) -> datetime:
        """forecast_start 가 데이터 범위를 벗어나면 데이터 마지막 시각으로 고정한다."""
        data_end = load_df["timestamp"].max().replace(minute=0, second=0, microsecond=0)
        now = (forecast_start or data_end).replace(minute=0, second=0, microsecond=0)
        return min(now, data_end)

    def _load_weather_history(self, raw_dir: str) -> pd.DataFrame:
        from src.data.adapters.public_data_adapter import load_kpx_with_weather

        return load_kpx_with_weather(raw_dir)

    def _apply_load_scale(self, load_df: pd.DataFrame, load_scale: float) -> pd.DataFrame:
        if load_scale == 1.0:
            return load_df

        scaled_df = load_df.copy()
        scaled_df["load_mw"] = scaled_df["load_mw"] * load_scale
        return scaled_df

    def _build_target_features(
        self,
        *,
        load_df: pd.DataFrame,
        forecast_start: datetime,
    ) -> list:
        from src.engine.forecast.feature_builder import build_prediction_feature_matrix

        return build_prediction_feature_matrix(
            load_df=load_df,
            forecast_start=forecast_start,
        )

    def _predict_baseline(
        self,
        *,
        load_df: pd.DataFrame,
        forecast_start: datetime,
    ) -> list[HourlyLoadPrediction]:
        from src.engine.forecast.baseline_forecaster import BaselineForecaster

        forecaster = BaselineForecaster().fit(load_df)
        target_features = self._build_target_features(
            load_df=load_df,
            forecast_start=forecast_start,
        )
        return forecaster.predict(target_features=target_features)

    def _predict_lstm(
        self,
        *,
        training_df: pd.DataFrame,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        target_features: list,
        retrain: bool,
        epochs: int,
    ) -> tuple[list[HourlyLoadPrediction], list[str]]:
        from src.engine.forecast.lstm_forecaster import LSTMForecaster

        forecaster = LSTMForecaster()
        if retrain or not forecaster.is_trained():
            forecaster.fit(training_df, epochs=epochs)

        warnings: list[str] = []
        try:
            # lookback 윈도우는 원본 스케일 데이터 사용 (load_scale은 예측 후 적용)
            predictions = forecaster.predict(
                history_df=training_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
        except Exception as exc:
            if retrain or not _is_recoverable_lstm_model_error(exc):
                raise

            forecaster = LSTMForecaster()
            forecaster.fit(training_df, epochs=epochs)
            predictions = forecaster.predict(
                history_df=training_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
            warnings.append(
                "저장된 LSTM 모델 로드에 실패해 현재 환경에서 재학습 후 예측을 수행했습니다."
            )
            warnings.append(f"LSTM 모델 재학습 원인: {_summarize_lstm_model_error(exc)}")

        # load_scale 을 예측 결과에 사후 적용
        scale = history_df["load_mw"].sum() / training_df["load_mw"].sum() if training_df["load_mw"].sum() > 0 else 1.0
        if abs(scale - 1.0) > 0.001:
            predictions = [
                HourlyLoadPrediction(
                    timestamp=p.timestamp,
                    bus_id=p.bus_id,
                    predicted_load_mw=round(p.predicted_load_mw * scale, 1),
                    confidence_lower_mw=round(p.confidence_lower_mw * scale, 1),
                    confidence_upper_mw=round(p.confidence_upper_mw * scale, 1),
                )
                for p in predictions
            ]

        return predictions, warnings

    def _predict_gnn(
        self,
        *,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        target_features: list,
        grid_dataset: GridDataset | None = None,
    ) -> list[HourlyLoadPrediction]:
        from src.engine.forecast.gnn_forecaster import GNNForecaster

        return (
            GNNForecaster()
            .fit(
                history_df,
                graph_edges=self._grid_graph_edges(grid_dataset) if grid_dataset is not None else None,
            )
            .predict(
                history_df=history_df,
                forecast_start=forecast_start,
                target_features=target_features,
            )
        )

    def _predict_neural_gnn(
        self,
        *,
        training_df: pd.DataFrame,
        history_df: pd.DataFrame,
        forecast_start: datetime,
        target_features: list,
        grid_dataset: GridDataset,
        retrain: bool,
        epochs: int,
        model_dir: str | None = None,
    ) -> tuple[list[HourlyLoadPrediction], dict[str, object]]:
        from src.engine.forecast.neural_gnn_forecaster import NeuralGNNForecaster

        graph_edges = self._grid_graph_edges(grid_dataset)
        forecaster = NeuralGNNForecaster(model_dir=model_dir)
        forecaster.fit_or_load(
            training_df,
            graph_edges=graph_edges,
            retrain=retrain,
            epochs=epochs,
        )
        predictions = forecaster.predict(
            history_df=history_df,
            forecast_start=forecast_start,
            graph_edges=graph_edges,
            target_features=target_features,
        )
        metadata = forecaster.training_metadata()
        metadata["training_history"] = forecaster.training_history()
        return predictions, metadata


# ── 순수 함수 ──────────────────────────────────────────────────────────────────

def _prediction_node_load_weights(
    dataset: GridDataset,
    prediction_nodes: list[GridNode],
) -> dict[str, float]:
    if not prediction_nodes:
        return {}
    profile_by_node_id = {
        profile.node_id: profile
        for profile in dataset.power_profiles
    }
    raw_weights: dict[str, float] = {}
    for node in prediction_nodes:
        profile = profile_by_node_id.get(node.node_id)
        raw_weight = (
            profile.load_weight
            if profile is not None and profile.load_weight > 0.0
            else max(0.0, node.base_load_mw)
        )
        raw_weights[node.node_id] = float(raw_weight)

    total_weight = sum(raw_weights.values())
    if total_weight <= 0.0:
        equal_weight = 1.0 / len(prediction_nodes)
        return {
            node.node_id: equal_weight
            for node in prediction_nodes
        }
    return {
        node_id: weight / total_weight
        for node_id, weight in raw_weights.items()
    }


def _estimate_grid_line_flow_mw(from_load_mw: float, to_load_mw: float) -> float:
    endpoint_pressure = max(0.0, from_load_mw, to_load_mw)
    imbalance = abs(from_load_mw - to_load_mw)
    return (endpoint_pressure * 0.95) + (imbalance * 0.20)


def _classify_risk(utilization: float) -> str:
    if utilization >= 0.90:
        return "critical"
    if utilization >= 0.75:
        return "high"
    if utilization >= 0.55:
        return "medium"
    return "low"


def _is_recoverable_lstm_model_error(exc: Exception) -> bool:
    message = str(exc)
    recoverable_markers = (
        "could not be deserialized properly",
        "quantization_config",
        "load_model",
    )
    return any(marker in message for marker in recoverable_markers)


def _summarize_lstm_model_error(exc: Exception) -> str:
    message = str(exc)
    if "quantization_config" in message:
        return "저장된 model.keras가 현재 Keras 버전의 Dense 설정과 호환되지 않았습니다."
    if "could not be deserialized properly" in message:
        return "저장된 model.keras를 현재 Keras 환경에서 역직렬화하지 못했습니다."
    if "load_model" in message:
        return "저장된 LSTM 모델 로드에 실패했습니다."
    return message.splitlines()[0] if message else exc.__class__.__name__


def _summarize_prediction_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message.splitlines()[0] if message else exc.__class__.__name__


def _combine_prediction_lists(
    *,
    primary: list[HourlyLoadPrediction],
    secondary: list[HourlyLoadPrediction],
    primary_weight: float,
    secondary_weight: float,
) -> list[HourlyLoadPrediction]:
    secondary_map = {
        (prediction.timestamp, prediction.bus_id): prediction
        for prediction in secondary
    }
    combined: list[HourlyLoadPrediction] = []
    total_weight = primary_weight + secondary_weight

    for prediction in primary:
        key = (prediction.timestamp, prediction.bus_id)
        secondary_prediction = secondary_map.get(key)
        if secondary_prediction is None:
            raise ValueError(f"병렬 조합 대상 예측 키가 맞지 않습니다: {key}")

        predicted_load = (
            (prediction.predicted_load_mw * primary_weight)
            + (secondary_prediction.predicted_load_mw * secondary_weight)
        ) / total_weight
        lower_bound = (
            (prediction.confidence_lower_mw * primary_weight)
            + (secondary_prediction.confidence_lower_mw * secondary_weight)
        ) / total_weight
        upper_bound = (
            (prediction.confidence_upper_mw * primary_weight)
            + (secondary_prediction.confidence_upper_mw * secondary_weight)
        ) / total_weight
        combined.append(
            HourlyLoadPrediction(
                timestamp=prediction.timestamp,
                bus_id=prediction.bus_id,
                predicted_load_mw=round(predicted_load, 1),
                confidence_lower_mw=round(max(0.0, lower_bound), 1),
                confidence_upper_mw=round(max(predicted_load, upper_bound), 1),
            )
        )

    return combined


def _time_zone_label(hour: int) -> str:
    if 6 <= hour < 11:
        return "오전 피크 시간대"
    if 11 <= hour < 14:
        return "정오 전후"
    if 14 <= hour < 19:
        return "오후 피크 시간대"
    if 19 <= hour < 23:
        return "저녁 고부하 시간대"
    return "심야·새벽 시간대"


def _scale_note(load_scale: float) -> str:
    if abs(load_scale - 1.0) <= 0.01:
        return ""
    diff = int((load_scale - 1.0) * 100)
    sign = "+" if diff > 0 else ""
    return f" 부하 배율 {load_scale:.0%} 적용으로 평시 대비 {sign}{diff}% 수준입니다."


def _action_note(utilization: float, risk_level: str) -> str:
    pct = int(utilization * 100)
    if risk_level == "critical":
        if pct >= 110:
            return "즉각적인 발전 재배치 및 우회 경로 투입이 필요합니다. 계통 보호 장치 동작 위험이 있습니다."
        return "즉각적인 우회 경로 구성 또는 발전 재배치를 시행하십시오."
    if risk_level == "high":
        return "ESS 방전 또는 인근 선로 부하 분산을 검토하십시오. 수요 반응 프로그램 발동도 고려할 수 있습니다."
    return "현재는 관리 범위 내이나 추세를 지속 모니터링하십시오."


def _build_explanation(
    line_id: str,
    from_name: str,
    to_name: str,
    utilization: float,
    peak_hour: int,
    risk_level: str,
    load_scale: float,
) -> str:
    pct = int(utilization * 100)
    hour_str = f"{peak_hour:02d}:00"
    zone = _time_zone_label(peak_hour)
    scale = _scale_note(load_scale)
    action = _action_note(utilization, risk_level)

    if risk_level == "critical":
        return (
            f"{from_name}–{to_name} 선로({line_id})는 {hour_str} ({zone})에 "
            f"이용률 {pct}%로 열적 한계를 초과할 위험이 있습니다.{scale} {action}"
        )
    if risk_level == "high":
        return (
            f"{from_name}–{to_name} 선로({line_id})는 {hour_str} ({zone})에 "
            f"이용률 {pct}%로 혼잡 임계치에 근접합니다.{scale} {action}"
        )
    return (
        f"{from_name}–{to_name} 선로({line_id})는 {hour_str} ({zone})에 "
        f"이용률 {pct}%입니다.{scale} {action}"
    )
