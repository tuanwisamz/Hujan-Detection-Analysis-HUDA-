import math
from datetime import datetime, timedelta, timezone

from app.services import features, ingest_weather

T0 = datetime(2026, 10, 18, 0, tzinfo=timezone.utc)


def series(precip):
    n = len(precip)
    return {"time": [T0 + timedelta(hours=i) for i in range(n)], "precipitation": precip,
            "cape": [1000.0] * n, "relative_humidity_2m": [80.0] * n, "dew_point_2m": [24.0] * n,
            "temperature_2m": [30.0] * n, "surface_pressure": [1008.0 + i * 0.1 for i in range(n)],
            "cloud_cover_low": [50.0] * n, "cloud_cover_mid": [40.0] * n, "wind_speed_10m": [10.0] * n,
            "wind_direction_10m": [90.0] * n}


def test_lags_and_forecast_windows():
    obs = series([1.0] * 30)
    f = features.build_features(obs, 24, 3.18, 101.49, obs["time"][24], fcst=obs)
    assert f["precip_lag_1h"] == 1 and f["precip_lag_3h"] == 3 and f["precip_lag_24h"] == 24
    assert f["fcst_precip_3h"] == 3
    assert f["dewpoint_depression"] == 6
    assert round(f["pressure_tendency_3h"], 3) == 0.3
    assert f["wind_dir_sin"] == 1.0
    assert list(f) == features.FEATURE_NAMES


def test_forecast_features_never_come_from_obs():
    """D3 leakage guard: without a forecast series, forecast features are NaN, not observed future rain."""
    obs = series([0.0] * 24 + [40.0] * 6)
    f = features.build_features(obs, 23, 3.18, 101.49, obs["time"][23])
    assert math.isnan(f["fcst_precip_1h"]) and math.isnan(f["fcst_precip_3h"])
    assert features.label(obs, 23) == 1


def test_label_and_accum():
    obs = series([0.0] * 10 + [10.0, 10.0, 9.0] + [0.0] * 5)
    assert features.label(obs, 9) == 0
    assert features.label(obs, 9, threshold_mm=29) == 1
    assert features.label(obs, 16) is None  # not enough future hours
    assert features.accum_24h(obs, 5) is None
    assert features.accum_24h(series([2.0] * 30), 25) == 48.0


def test_myt_time_features_and_monsoon():
    obs = series([0.0] * 30)
    f = features.build_features(obs, 0, 3.0, 101.0, datetime(2026, 1, 1, 6, tzinfo=timezone.utc))
    assert round(f["hour_sin"], 6) == round(math.sin(2 * math.pi * 14 / 24), 6)  # 06 UTC = 14 MYT
    assert [features.monsoon_phase(m) for m in (1, 4, 7, 10, 12)] == [0, 2, 1, 2, 0]


def test_current_index():
    times = [T0 + timedelta(hours=i) for i in range(5)]
    assert features.current_index(times, T0 + timedelta(hours=2, minutes=35)) == 2


ZONES = [
    {"id": "elmina", "district": "Petaling", "state": "Selangor", "match_terms": ["Shah Alam"]},
    {"id": "klang", "district": "Klang", "state": "Selangor", "match_terms": []},
    {"id": "pagoh", "district": "Muar", "state": "Johor", "match_terms": ["Pagoh"]},
]


def warning(title, text):
    return {"warning_issue": {"title_en": title}, "heading_en": title, "text_en": text}


def test_warning_matches_district_and_terms():
    m = ingest_weather.match_warnings([warning("Thunderstorm Warning", "Selangor (Petaling, Hulu Langat)")], ZONES)
    assert set(m) == {"elmina"} and m["elmina"]["severity"] == "active"
    m = ingest_weather.match_warnings([warning("Heavy Rain Warning (Danger Level)", "Johor: Pagoh area")], ZONES)
    assert m["pagoh"]["severity"] == "severe"


def test_whole_state_warning_matches_all_zones_in_state():
    m = ingest_weather.match_warnings([warning("Thunderstorm Warning", "Thunderstorms over Selangor.")], ZONES)
    assert set(m) == {"elmina", "klang"}


def test_non_rain_warnings_ignored():
    m = ingest_weather.match_warnings([warning("Strong Wind Warning", "Strong winds over Petaling")], ZONES)
    assert m == {}


def test_parse_ts_defaults_to_myt():
    assert ingest_weather._ts("2026-10-18T14:00:00").utcoffset() == timedelta(hours=8)


def test_marine_bulletin_with_rain_words_is_ignored():
    w = warning("Strong Winds and Rough Seas Warning", "Waters off Selangor ... thunderstorms and heavy rain")
    assert ingest_weather.match_warnings([w], ZONES) == {}


def test_flood_stations_by_distance_level_and_freshness():
    now = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)
    zones = [{"id": "elmina", "lat": 3.183, "lon": 101.486}]
    near = {"station_name": "Sg. Buloh", "latitude": 3.20, "longitude": 101.50,
            "water_level_indicator": "WARNING", "water_level_update_datetime": "2026-10-18 13:30:00"}
    assert ingest_weather.match_flood([near], zones, now) == {"elmina": "River warning – Sg. Buloh"}
    stale = {**near, "water_level_update_datetime": "2024-02-23 14:45:00"}
    normal = {**near, "water_level_indicator": "NORMAL"}
    far = {**near, "latitude": 4.0}
    assert ingest_weather.match_flood([stale, normal, far], zones, now) == {}
