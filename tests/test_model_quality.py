# LSTM/GNN 예측 모델의 품질 기준을 검증한다.
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.data.schemas import HourlyLoadPrediction, PredictionResult
from src.services.prediction_service import PredictionService

_RAW_DIR = str(Path(__file__).resolve().parents[1] / "data" / "raw")
_N_BUSES = 13
_HORIZON = 24


@pytest.fixture(scope="module")
def mock_result() -> PredictionResult:
    return PredictionService().run_mock_prediction(load_scale=1.0)


@pytest.fixture(scope="module")
def baseline_result() -> PredictionResult:
    return PredictionService().run_baseline_prediction(
        raw_dir=_RAW_DIR, load_scale=1.0
    )


# ── 기본 계약 검증 ─────────────────────────────────────────────────────────────

class TestPredictionContract:
    def test_prediction_count(self, mock_result):
        assert len(mock_result.predictions) == _HORIZON * _N_BUSES

    def test_no_negative_load(self, mock_result):
        for p in mock_result.predictions:
            assert p.predicted_load_mw >= 0.0, f"{p.bus_id} @ {p.timestamp}: {p.predicted_load_mw}"

    def test_confidence_interval_order(self, mock_result):
        for p in mock_result.predictions:
            assert p.confidence_lower_mw <= p.predicted_load_mw <= p.confidence_upper_mw

    def test_all_buses_covered(self, mock_result):
        bus_ids = {p.bus_id for p in mock_result.predictions}
        assert len(bus_ids) == _N_BUSES

    def test_risk_lines_sorted_desc(self, mock_result):
        utils = [r.predicted_utilization for r in mock_result.risk_lines]
        assert utils == sorted(utils, reverse=True)

    def test_no_low_risk_in_risk_lines(self, mock_result):
        for r in mock_result.risk_lines:
            assert r.risk_level != "low"

    def test_peak_hour_valid_range(self, mock_result):
        for r in mock_result.risk_lines:
            assert 0 <= r.peak_risk_hour <= 23, f"{r.line_id}: peak_hour={r.peak_risk_hour}"


# ── 피크 시각 합리성 검증 ──────────────────────────────────────────────────────

class TestPeakHourReasonability:
    def test_mock_peak_not_deep_night(self, mock_result):
        """Mock 예측에서 피크는 심야(0~5시)에 몰리지 않아야 한다."""
        night_peaks = [
            r for r in mock_result.risk_lines
            if r.peak_risk_hour in range(0, 6)
        ]
        total = len(mock_result.risk_lines)
        if total == 0:
            return
        # 심야 피크 비율이 50% 이하여야 함
        assert len(night_peaks) / total <= 0.5, (
            f"심야 피크 선로 비율 {len(night_peaks)}/{total} 초과"
        )

    def test_baseline_peak_in_business_hours(self, baseline_result):
        """Baseline 예측에서 최고 위험 선로 피크는 업무 시간대(7~23시)여야 한다."""
        if not baseline_result.risk_lines:
            pytest.skip("위험 선로 없음")
        top = baseline_result.risk_lines[0]
        assert 7 <= top.peak_risk_hour <= 23, (
            f"최고 위험 선로 피크 시각 {top.peak_risk_hour}시는 업무 시간대 아님"
        )


# ── 부하 배율 반영 검증 ────────────────────────────────────────────────────────

class TestLoadScaleEffect:
    def _avg_load(self, result: PredictionResult) -> float:
        return sum(p.predicted_load_mw for p in result.predictions) / len(result.predictions)

    def test_higher_scale_increases_load(self):
        svc = PredictionService()
        r1 = svc.run_mock_prediction(load_scale=1.0)
        r2 = svc.run_mock_prediction(load_scale=1.2)
        assert self._avg_load(r2) > self._avg_load(r1)

    def test_scale_preserved_in_result(self):
        r = PredictionService().run_mock_prediction(load_scale=1.15)
        assert r.load_scale == pytest.approx(1.15)


# ── 도시 규모별 부하 검증 ──────────────────────────────────────────────────────

class TestCityScaleOrder:
    def test_seoul_larger_than_gangneung(self, baseline_result):
        """서울 평균 예측 부하는 강릉보다 커야 한다."""
        by_bus: dict[str, list[float]] = {}
        for p in baseline_result.predictions:
            by_bus.setdefault(p.bus_id, []).append(p.predicted_load_mw)

        seoul = sum(by_bus.get("BUS_001", [0])) / max(len(by_bus.get("BUS_001", [1])), 1)
        gangneung = sum(by_bus.get("BUS_005", [0])) / max(len(by_bus.get("BUS_005", [1])), 1)
        assert seoul > gangneung, f"서울({seoul:.0f}) <= 강릉({gangneung:.0f})"

    def test_busan_larger_than_jeonju(self, baseline_result):
        """부산 평균 예측 부하는 전주보다 커야 한다."""
        by_bus: dict[str, list[float]] = {}
        for p in baseline_result.predictions:
            by_bus.setdefault(p.bus_id, []).append(p.predicted_load_mw)

        busan = sum(by_bus.get("BUS_013", [0])) / max(len(by_bus.get("BUS_013", [1])), 1)
        jeonju = sum(by_bus.get("BUS_010", [0])) / max(len(by_bus.get("BUS_010", [1])), 1)
        assert busan > jeonju, f"부산({busan:.0f}) <= 전주({jeonju:.0f})"
