from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("torch")
pytestmark = pytest.mark.slow

from src.data.schemas import GridDataset, GridLine, GridNode, GridPowerProfile
from src.engine.forecast.feature_builder import build_prediction_feature_matrix
from src.engine.forecast.neural_gnn_forecaster import NeuralGNNForecaster
from src.services.prediction_service import PredictionService


def _tiny_grid_dataset(created_at: datetime) -> GridDataset:
    nodes = [
        GridNode(
            node_id="NODE_A",
            node_name="Node A",
            node_type="transmission_tower",
            latitude=37.0,
            longitude=127.0,
            voltage_kv=345.0,
            base_load_mw=900.0,
        ),
        GridNode(
            node_id="NODE_B",
            node_name="Node B",
            node_type="transmission_tower",
            latitude=36.5,
            longitude=128.0,
            voltage_kv=345.0,
            base_load_mw=1050.0,
        ),
    ]
    return GridDataset(
        nodes=nodes,
        lines=[
            GridLine(
                line_id="GLINE_NODE_A_NODE_B",
                from_node_id="NODE_A",
                to_node_id="NODE_B",
                voltage_kv=345.0,
                capacity_mw=1600.0,
                reactance_pu=0.08,
                distance_km=70.0,
            )
        ],
        power_profiles=[
            GridPowerProfile(node_id="NODE_A", timestamp=created_at, load_mw=900.0, load_weight=0.46),
            GridPowerProfile(node_id="NODE_B", timestamp=created_at, load_mw=1050.0, load_weight=0.54),
        ],
        created_at=created_at,
        source="default_asset",
    )


def test_neural_gnn_forecaster_trains_saves_history_and_predicts(load_df_2bus, tmp_path):
    forecast_start = load_df_2bus["timestamp"].max()
    target_features = build_prediction_feature_matrix(
        load_df=load_df_2bus,
        forecast_start=forecast_start,
        bus_ids=["NODE_A", "NODE_B"],
        horizon_h=3,
    )

    forecaster = NeuralGNNForecaster(model_dir=tmp_path)
    forecaster.fit_or_load(
        load_df_2bus,
        graph_edges=[("NODE_A", "NODE_B")],
        retrain=True,
        epochs=2,
        batch_size=8,
        patience=2,
    )
    predictions = forecaster.predict(
        load_df_2bus,
        forecast_start,
        graph_edges=[("NODE_A", "NODE_B")],
        target_features=target_features,
    )

    assert len(predictions) == 6
    assert [p.bus_id for p in predictions] == [feature.bus_id for feature in target_features]
    assert all(p.predicted_load_mw >= 0.0 for p in predictions)
    assert (tmp_path / "model.pt").exists()
    assert (tmp_path / "training_history.csv").exists()
    metadata = forecaster.training_metadata()
    assert metadata["model_type"] == "neural_gnn"
    assert metadata["framework"] == "torch"
    assert metadata["deep_learning"] is True
    assert metadata["epochs_trained"] >= 1


def test_prediction_service_neural_gnn_result_contract(
    monkeypatch,
    load_df_2bus,
    scenario,
    tmp_path,
):
    service = PredictionService()
    dataset = _tiny_grid_dataset(scenario.created_at)
    monkeypatch.setattr(service, "_load_grid_history", lambda raw_dir, dataset: load_df_2bus)

    result = service.run_neural_gnn_prediction(
        raw_dir="unused",
        load_scale=1.0,
        forecast_start=load_df_2bus["timestamp"].max(),
        scenario=scenario,
        retrain=True,
        epochs=1,
        grid_dataset=dataset,
        model_dir=str(tmp_path / "service_gnn"),
    )

    assert result.source == "neural_gnn"
    assert result.fallback.enabled is False
    assert len(result.predictions) == 2 * 24
    assert result.metadata["model_type"] == "neural_gnn"
    assert result.metadata["deep_learning"] is True
    assert result.metadata["framework"] == "torch"
    assert result.metadata["graph_edge_source"] == "GridLine"
    assert result.metadata["legacy_bus_source"] is False
    assert isinstance(result.metadata["training_history"], list)
