from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

from src.data.schemas import InstallationTargetKind


_DEFAULT_PLACES_CSV = (
    Path(__file__).resolve().parents[2] / "data" / "geo" / "korea_places.csv"
)
_REQUIRED_COLUMNS = {
    "place_id",
    "place_name",
    "province",
    "place_type",
    "latitude",
    "longitude",
}
_INSTALLATION_SUFFIX_BY_KIND: dict[InstallationTargetKind, str] = {
    "power_plant": "발전소",
    "transmission_tower": "송전탑",
    "start_point": "시작점",
    "end_point": "종료점",
}


@dataclass(frozen=True)
class GeoPlace:
    place_id: str
    place_name: str
    province: str
    place_type: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class NearestPlace:
    place_id: str
    place_name: str
    province: str
    place_type: str
    latitude: float
    longitude: float
    distance_km: float

    def to_metadata(self) -> dict[str, object]:
        return {
            "nearest_place_id": self.place_id,
            "nearest_place_name": self.place_name,
            "nearest_place_province": self.province,
            "nearest_place_type": self.place_type,
            "nearest_place_latitude": self.latitude,
            "nearest_place_longitude": self.longitude,
            "nearest_place_distance_km": round(self.distance_km, 3),
        }


class GeoPlaceService:
    """CSV 기반 대표 지명 조회 서비스.

    현재 목적은 지도 클릭 좌표에 대해 가까운 시/군 이름을 추천하는 것이다.
    법정 경계 포함 여부나 주소 역지오코딩을 판단하지 않는다.
    """

    def __init__(self, csv_path: str | Path | None = None) -> None:
        self.csv_path = _resolve_places_csv_path(csv_path)

    def load_places(self) -> tuple[GeoPlace, ...]:
        return load_korea_places(self.csv_path)

    def find_nearest_place(self, latitude: float, longitude: float) -> NearestPlace:
        places = self.load_places()
        if not places:
            raise LookupError(f"지명 CSV가 비어 있습니다: {self.csv_path}")

        nearest_place = min(
            places,
            key=lambda place: _distance_km(
                latitude,
                longitude,
                place.latitude,
                place.longitude,
            ),
        )
        distance_km = _distance_km(
            latitude,
            longitude,
            nearest_place.latitude,
            nearest_place.longitude,
        )
        return NearestPlace(
            place_id=nearest_place.place_id,
            place_name=nearest_place.place_name,
            province=nearest_place.province,
            place_type=nearest_place.place_type,
            latitude=nearest_place.latitude,
            longitude=nearest_place.longitude,
            distance_km=distance_km,
        )

    def build_installation_label(
        self,
        latitude: float,
        longitude: float,
        kind: InstallationTargetKind,
    ) -> str:
        nearest = self.find_nearest_place(latitude, longitude)
        suffix = _INSTALLATION_SUFFIX_BY_KIND.get(kind, "지점")
        return f"{nearest.place_name} {suffix}"


def load_korea_places(csv_path: str | Path | None = None) -> tuple[GeoPlace, ...]:
    return _load_korea_places_from_path(str(_resolve_places_csv_path(csv_path)))


def _resolve_places_csv_path(csv_path: str | Path | None) -> Path:
    if csv_path is None:
        return _DEFAULT_PLACES_CSV
    return Path(csv_path)


@lru_cache(maxsize=8)
def _load_korea_places_from_path(csv_path: str) -> tuple[GeoPlace, ...]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = _REQUIRED_COLUMNS.difference(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"지명 CSV 필수 컬럼이 없습니다: {missing}")

        places: list[GeoPlace] = []
        seen_ids: set[str] = set()
        for row in reader:
            place_id = str(row.get("place_id", "")).strip()
            if not place_id:
                raise ValueError(f"지명 CSV {reader.line_num}행에 place_id가 없습니다.")
            if place_id in seen_ids:
                raise ValueError(f"지명 CSV place_id가 중복됩니다: {place_id}")

            place_name = str(row.get("place_name", "")).strip()
            province = str(row.get("province", "")).strip()
            place_type = str(row.get("place_type", "")).strip()
            if not place_name or not province or not place_type:
                raise ValueError(f"지명 CSV {reader.line_num}행에 빈 필드가 있습니다.")

            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"지명 CSV {reader.line_num}행 좌표를 숫자로 읽을 수 없습니다."
                ) from exc

            if not (33.0 <= latitude <= 39.0 and 124.0 <= longitude <= 132.0):
                raise ValueError(
                    f"지명 CSV {reader.line_num}행 좌표가 국내 대표점 범위를 벗어났습니다."
                )

            seen_ids.add(place_id)
            places.append(
                GeoPlace(
                    place_id=place_id,
                    place_name=place_name,
                    province=province,
                    place_type=place_type,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
    return tuple(places)


def _distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    radius_km = 6371.0
    lat_a = radians(latitude_a)
    lat_b = radians(latitude_b)
    delta_lat = radians(latitude_b - latitude_a)
    delta_lon = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * atan2(sqrt(haversine), sqrt(1 - haversine))
