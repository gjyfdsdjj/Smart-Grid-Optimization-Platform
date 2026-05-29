from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.data.schemas import HourlyLoadPrediction, ScenarioContext


def build_load_df(
    *,
    bus_ids: tuple[str, ...] = ("NODE_A", "NODE_B"),
    hours: int = 96,
    start: datetime = datetime(2026, 1, 1, 0, 0),
    include_temperature: bool = True,
) -> pd.DataFrame:
    rows: list[dict] = []
    for hour_index in range(hours):
        ts = start + timedelta(hours=hour_index)
        hour_shape = (ts.hour * 4.0) + ((hour_index // 24) * 6.0)
        for bus_index, bus_id in enumerate(bus_ids):
            base_load = 900.0 + (bus_index * 140.0)
            row = {
                "timestamp": ts,
                "bus_id": bus_id,
                "bus_name": f"Bus {bus_index + 1}",
                "load_mw": round(base_load + hour_shape + (bus_index * 11.0), 1),
                "generation_mw": 500.0 if bus_index == 0 else 0.0,
            }
            if include_temperature:
                row["temperature_c"] = round(18.0 + (ts.hour * 0.25) + bus_index, 1)
            rows.append(row)
    return pd.DataFrame(rows)


def build_prediction(
    *,
    timestamp: datetime,
    bus_id: str,
    value: float,
) -> HourlyLoadPrediction:
    return HourlyLoadPrediction(
        timestamp=timestamp,
        bus_id=bus_id,
        predicted_load_mw=value,
        confidence_lower_mw=max(0.0, value - 10.0),
        confidence_upper_mw=value + 10.0,
    )


@pytest.fixture
def load_df_2bus() -> pd.DataFrame:
    return build_load_df()


@pytest.fixture
def load_df_13bus() -> pd.DataFrame:
    bus_ids = tuple(f"NODE_{index:03d}" for index in range(1, 14))
    return build_load_df(bus_ids=bus_ids)


@pytest.fixture
def prediction_factory():
    return build_prediction


@pytest.fixture
def scenario() -> ScenarioContext:
    return ScenarioContext(
        scenario_id="test-prediction-scenario",
        title="Prediction Test Scenario",
        region="South Korea",
        created_at=datetime(2026, 1, 5, 0, 0),
        created_by="pytest",
    )
