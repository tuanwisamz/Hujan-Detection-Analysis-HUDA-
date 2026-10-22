import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest

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


# ---- Open-Meteo cache / 429 handling ----

class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.is_error = status >= 400
        self.reason_phrase = "Too Many Requests" if status == 429 else "OK"
        self.request = httpx.Request("GET", ingest_weather.FORECAST_URL)

    def json(self):
        return self._body


OM_ZONES = [{"id": "z1", "lat": 3.18, "lon": 101.49}]
OM_BODY = {"hourly": {"time": ["2026-10-18T00:00"], "precipitation": [1.5]}}


def fake_open_meteo(monkeypatch, responses):
    calls = []
    def get(url, params=None, timeout=None):
        calls.append(url)
        return responses.pop(0)
    monkeypatch.setattr(ingest_weather.httpx, "get", get)
    monkeypatch.setattr(ingest_weather.time, "sleep", lambda s: None)
    monkeypatch.setattr(ingest_weather, "_open_meteo_cache", {})
    return calls


def test_open_meteo_live_result_is_cached(monkeypatch):
    calls = fake_open_meteo(monkeypatch, [FakeResponse(200, OM_BODY)])
    first = ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])
    again = ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])
    assert first == again and first["z1"]["precipitation"] == [1.5] and len(calls) == 1


def test_open_meteo_retries_429_once(monkeypatch):
    calls = fake_open_meteo(monkeypatch, [FakeResponse(429, {"reason": "Minutely limit"}), FakeResponse(200, OM_BODY)])
    assert ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])["z1"]["precipitation"] == [1.5]
    assert len(calls) == 2


def test_open_meteo_serves_stale_result_on_failure_then_gives_up(monkeypatch):
    fake_open_meteo(monkeypatch, [FakeResponse(200, OM_BODY)] + [FakeResponse(429, {"reason": "Hourly limit"})] * 4)
    good = ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])
    key, (ts, result) = next(iter(ingest_weather._open_meteo_cache.items()))
    ingest_weather._open_meteo_cache[key] = (ts - timedelta(hours=1), result)    # past TTL, within stale max
    assert ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"]) == good
    ingest_weather._open_meteo_cache[key] = (ts - timedelta(hours=4), result)    # too old to serve
    with pytest.raises(httpx.HTTPStatusError, match="Hourly limit"):
        ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])


def test_open_meteo_daily_limit_serves_up_to_a_day_old(monkeypatch):
    daily = FakeResponse(429, {"reason": "Daily API request limit exceeded. Please try again tomorrow."})
    fake_open_meteo(monkeypatch, [FakeResponse(200, OM_BODY)] + [daily] * 4)
    good = ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])
    assert ingest_weather.last_stale_min is None
    key, (ts, result) = next(iter(ingest_weather._open_meteo_cache.items()))
    ingest_weather._open_meteo_cache[key] = (ts - timedelta(hours=10), result)   # beyond 3 h, within a day
    assert ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"]) == good
    assert 599 <= ingest_weather.last_stale_min <= 601
    ingest_weather._open_meteo_cache[key] = (ts - timedelta(hours=25), result)
    with pytest.raises(httpx.HTTPStatusError, match="Daily API request limit"):
        ingest_weather.fetch_open_meteo(OM_ZONES, variables=["precipitation"])


def test_stale_weather_does_not_degrade_the_run():
    from app.services.pipeline import _status
    base = {"radar": "ok", "nowcast": "ok", "met_warnings": "ok"}
    assert _status(base | {"open_meteo": "stale"}) == "ok"
    assert _status(base | {"open_meteo": "failed"}) == "degraded"


def test_open_meteo_backfill_is_not_cached(monkeypatch):
    calls = fake_open_meteo(monkeypatch, [FakeResponse(200, OM_BODY), FakeResponse(200, OM_BODY)])
    for _ in range(2):
        ingest_weather.fetch_open_meteo(OM_ZONES, at=T0, variables=["precipitation"])
    assert len(calls) == 2 and ingest_weather._open_meteo_cache == {}
