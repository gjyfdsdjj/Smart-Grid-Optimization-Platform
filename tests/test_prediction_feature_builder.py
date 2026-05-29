from __future__ import annotations

from datetime import timedelta

from src.engine.forecast.feature_builder import (
    build_feature_vector,
    build_prediction_feature_matrix,
)


def test_build_feature_vector_populates_lags_and_time_fields(load_df_2bus):
    target_ts = load_df_2bus["timestamp"].min() + timedelta(hours=80)

    feature = build_feature_vector(
        load_df=load_df_2bus,
        target_ts=target_ts,
        bus_id="NODE_A",
    )

    expected_lag_1h = load_df_2bus[
        (load_df_2bus["bus_id"] == "NODE_A")
        & (load_df_2bus["timestamp"] == target_ts - timedelta(hours=1))
    ]["load_mw"].iloc[0]
    expected_lag_24h = load_df_2bus[
        (load_df_2bus["bus_id"] == "NODE_A")
        & (load_df_2bus["timestamp"] == target_ts - timedelta(hours=24))
    ]["load_mw"].iloc[0]

    assert feature.timestamp == target_ts
    assert feature.bus_id == "NODE_A"
    assert feature.load_lag_1h == expected_lag_1h
    assert feature.load_lag_24h == expected_lag_24h
    assert feature.hour == target_ts.hour
    assert feature.day_of_week == target_ts.weekday()
    assert feature.month == target_ts.month
    assert 0.0 <= feature.regional_demand_ratio <= 1.0
    assert feature.total_generation_mw == 500.0


def test_build_prediction_feature_matrix_counts_and_order(load_df_2bus, load_df_13bus):
    forecast_start = load_df_2bus["timestamp"].max()

    features = build_prediction_feature_matrix(
        load_df=load_df_2bus,
        forecast_start=forecast_start,
        bus_ids=["NODE_A", "NODE_B"],
        horizon_h=24,
    )

    assert len(features) == 48
    assert (features[0].timestamp, features[0].bus_id) == (
        forecast_start + timedelta(hours=1),
        "NODE_A",
    )
    assert (features[1].timestamp, features[1].bus_id) == (
        forecast_start + timedelta(hours=1),
        "NODE_B",
    )
    assert (features[-1].timestamp, features[-1].bus_id) == (
        forecast_start + timedelta(hours=24),
        "NODE_B",
    )

    service_shape_features = build_prediction_feature_matrix(
        load_df=load_df_13bus,
        forecast_start=load_df_13bus["timestamp"].max(),
    )
    assert len(service_shape_features) == 24 * 13


def test_build_feature_vector_missing_lag_falls_back_to_zero(load_df_2bus):
    target_ts = load_df_2bus["timestamp"].min() + timedelta(hours=6)

    feature = build_feature_vector(
        load_df=load_df_2bus,
        target_ts=target_ts,
        bus_id="NODE_A",
    )

    assert feature.load_lag_1h > 0.0
    assert feature.load_lag_24h == 0.0
    assert feature.load_lag_48h == 0.0
    assert feature.load_lag_72h == 0.0
