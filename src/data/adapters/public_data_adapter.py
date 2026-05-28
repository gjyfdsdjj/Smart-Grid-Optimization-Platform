# 공공 데이터 응답을 SGOP에서 사용할 수 있는 구조로 변환한다.
"""
public_data_adapter — KPX 전력수급현황 CSV 로더

원본 데이터
-----------
출처  : 한국전력거래소 오늘전력수급현황 (https://openapi.kpx.or.kr/sukub.do)
형식  : CSV, EUC-KR, 5분 간격
컬럼  : 기준일시, 공급능력(MW), 현재수요(MW), 최대예측수요(MW),
        공급예비력(MW), 공급예비율(%), 운영예비력(MW), 운영예비율(%)

출력 계약
---------
national_df : pd.DataFrame
    컬럼 : timestamp (datetime), demand_mw (float), supply_mw (float)
    주기  : 1시간 (원본 5분 → 평균 리샘플)
    범위  : data/raw/sukub*.csv 전체 기간
"""
from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

def load_kpx_national_hourly(raw_dir: str | Path) -> pd.DataFrame:
    """data/raw/sukub*.csv 를 모두 읽어 시간별 전국 수급 DataFrame 으로 반환한다."""
    raw_dir = Path(raw_dir)
    csv_files = sorted(glob.glob(str(raw_dir / "sukub*.csv")))
    if not csv_files:
        raise FileNotFoundError(f"sukub*.csv 파일이 없습니다: {raw_dir}")

    frames = [_read_one(p) for p in csv_files]
    frames = [f for f in frames if f is not None]

    if not frames:
        raise ValueError("읽을 수 있는 CSV 파일이 없습니다.")

    national = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .set_index("timestamp")
    )

    # 5분 → 1시간 평균 리샘플
    national_hourly = national.resample("1h").mean().dropna().reset_index()
    return national_hourly[["timestamp", "demand_mw", "supply_mw"]]


def load_kpx_csvs(raw_dir: str | Path) -> pd.DataFrame:
    """이전 public 진입점 이름을 유지하되 전국 수급 DataFrame을 반환한다."""
    return load_kpx_national_hourly(raw_dir)


def _read_one(path: str) -> pd.DataFrame | None:
    """단일 CSV 파일을 읽어 timestamp / demand_mw / supply_mw DataFrame 반환."""
    for enc in ("euc-kr", "cp949", "utf-8-sig", "utf-8"):
        try:
            raw = pd.read_csv(path, encoding=enc, header=0)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    # 컬럼을 위치로 매핑 (인코딩 무관하게 안전)
    raw.columns = [
        "ts_raw", "supply_mw", "demand_mw", "max_pred_mw",
        "supply_reserve_mw", "supply_reserve_pct",
        "op_reserve_mw", "op_reserve_pct",
    ]

    raw["timestamp"] = pd.to_datetime(
        raw["ts_raw"].astype(str).str[:12],
        format="%Y%m%d%H%M",
        errors="coerce",
    )
    raw["demand_mw"] = pd.to_numeric(raw["demand_mw"], errors="coerce")
    raw["supply_mw"] = pd.to_numeric(raw["supply_mw"], errors="coerce")

    return raw[["timestamp", "demand_mw", "supply_mw"]].dropna()


def load_kpx_with_weather(raw_dir: str | Path) -> pd.DataFrame:
    """KPX 부하 데이터에 Open-Meteo 기온을 합쳐 반환한다.

    Returns
    -------
    national_df 와 동일한 계약 + 전국 평균 temperature_c 컬럼 추가
    """
    from src.data.adapters.weather_adapter import fetch_historical

    national_df = load_kpx_national_hourly(raw_dir)
    start = str(national_df["timestamp"].min().date())
    end = str(national_df["timestamp"].max().date())

    print(f"[날씨] {start} ~ {end} 기온 데이터 로딩 중...")
    weather_df = fetch_historical(start, end)
    weather_hourly = (
        weather_df.groupby("timestamp", as_index=False)
        .agg(temperature_c=("temperature_c", "mean"))
        .sort_values("timestamp")
    )

    merged = national_df.merge(weather_hourly, on="timestamp", how="left")
    missing = merged["temperature_c"].isna().sum()
    if missing > 0:
        merged["temperature_c"] = merged["temperature_c"].ffill().bfill()
        print(f"[날씨] {missing}개 결측 → ffill 보완")

    return merged
