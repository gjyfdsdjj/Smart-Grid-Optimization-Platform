from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.engine.forecast.feature_builder import build_prediction_feature_matrix
from src.services.prediction_service import (
    PredictionService,
    _combine_prediction_lists,
)


def test_combine_prediction_lists_uses_weighted_average(prediction_factory):
    ts = datetime(2026, 1, 5, 1, 0)
    primary = [prediction_factory(timestamp=ts, bus_id="NODE_A", value=100.0)]
    secondary = [prediction_factory(timestamp=ts, bus_id="NODE_A", value=200.0)]

    combined = _combine_prediction_lists(
        primary=primary,
        secondary=secondary,
        primary_weight=0.65,
        secondary_weight=0.35,
    )

    assert len(combined) == 1
    assert combined[0].predicted_load_mw == 135.0
    assert combined[0].confidence_lower_mw == 125.0
    assert combined[0].confidence_upper_mw == 145.0


def test_combine_prediction_lists_key_mismatch_raises(prediction_factory):
    ts = datetime(2026, 1, 5, 1, 0)
    primary = [prediction_factory(timestamp=ts, bus_id="NODE_A", value=100.0)]
    secondary = [
        prediction_factory(
            timestamp=ts + timedelta(hours=1),
            bus_id="NODE_A",
            value=200.0,
        )
    ]

    with pytest.raises(ValueError, match="예측 키가 맞지 않습니다"):
        _combine_prediction_lists(
            primary=primary,
            secondary=secondary,
            primary_weight=0.65,
            secondary_weight=0.35,
        )


def test_hybrid_prediction_falls_back_to_baseline_when_branch_fails(
    monkeypatch,
    load_df_13bus,
    prediction_factory,
    scenario,
):
    service = PredictionService()
    forecast_start = load_df_13bus["timestamp"].max()

    def fail_lstm(**kwargs):
        raise RuntimeError("forced lstm failure")

    def fake_gnn(**kwargs):
        return [
            prediction_factory(
                timestamp=feature.timestamp,
                bus_id=feature.bus_id,
                value=110.0,
            )
            for feature in kwargs["target_features"]
        ]

    def fake_baseline(**kwargs):
        target_features = build_prediction_feature_matrix(
            load_df=load_df_13bus,
            forecast_start=kwargs["forecast_start"],
        )
        predictions = [
            prediction_factory(
                timestamp=feature.timestamp,
                bus_id=feature.bus_id,
                value=100.0,
            )
            for feature in target_features
        ]
        return service._build_prediction_result(
            scenario=kwargs["scenario"],
            created_at=kwargs["forecast_start"],
            load_scale=kwargs["load_scale"],
            predictions=predictions,
            source="baseline",
            warnings=[],
        )

    monkeypatch.setattr(service, "_load_grid_history", lambda raw_dir, dataset: load_df_13bus)
    monkeypatch.setattr(service, "_predict_lstm", fail_lstm)
    monkeypatch.setattr(service, "_predict_gnn", fake_gnn)
    monkeypatch.setattr(service, "run_baseline_prediction", fake_baseline)

    result = service.run_hybrid_prediction(
        raw_dir="unused",
        load_scale=1.0,
        forecast_start=forecast_start,
        scenario=scenario,
        retrain=False,
        epochs=1,
    )

    assert result.source == "baseline"
    assert result.fallback.enabled is True
    assert result.fallback.mode == "baseline_model"
    assert result.warnings[0] == "PredictionService는 현재 `baseline_model` fallback 결과를 반환합니다."
    assert any("LSTM 실패" in warning for warning in result.warnings)
    assert "baseline 예측으로 전환" in result.fallback.reason


def test_risk_lines_are_sorted_non_low_and_explained(scenario):
    service = PredictionService()

    base_result = service.run_mock_prediction(
        load_scale=1.0,
        created_at=scenario.created_at,
        scenario=scenario,
    )
    high_load_result = service.run_mock_prediction(
        load_scale=1.5,
        created_at=scenario.created_at,
        scenario=scenario,
    )

    risk_lines = high_load_result.risk_lines

    assert len(risk_lines) >= len(base_result.risk_lines)
    assert risk_lines
    assert risk_lines == sorted(
        risk_lines,
        key=lambda item: item.predicted_utilization,
        reverse=True,
    )
    assert all(line.risk_level != "low" for line in risk_lines)
    assert all(line.explanation.strip() for line in risk_lines)
    assert all(0 <= line.peak_risk_hour <= 23 for line in risk_lines)
