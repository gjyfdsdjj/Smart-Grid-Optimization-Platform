from __future__ import annotations

from src.services.geo_place_service import GeoPlaceService, load_korea_places


def test_korea_places_csv_loads_major_city_and_county_representatives():
    places = load_korea_places()
    names = {place.place_name for place in places}

    assert len(places) >= 150
    assert {"서울", "부산", "구미", "상주", "거창", "해남"}.issubset(names)
    assert all(place.latitude and place.longitude for place in places)


def test_geo_place_service_finds_nearest_small_city_points():
    service = GeoPlaceService()

    gumi = service.find_nearest_place(36.1195, 128.3446)
    sangju = service.find_nearest_place(36.4109, 128.1591)

    assert gumi.place_name == "구미"
    assert gumi.distance_km < 0.1
    assert sangju.place_name == "상주"
    assert sangju.distance_km < 0.1


def test_geo_place_service_builds_installation_labels_from_nearest_place():
    service = GeoPlaceService()

    assert service.build_installation_label(36.1195, 128.3446, "power_plant") == "구미 발전소"
    assert service.build_installation_label(36.1195, 128.3446, "transmission_tower") == "구미 송전탑"
