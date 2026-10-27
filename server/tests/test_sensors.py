"""JPS InfoBanjir parsing and sensor evidence (architecture.md §3.2)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import Level, Thresholds
from app.services import ingest_sensors, sensors
from app.services.risk import classify

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 22, 14, 10, tzinfo=timezone.utc)
ELMINA = {"id": "elmina", "lat": 3.183, "lon": 101.486}


def test_rain_page_columns_by_header():
    rows = ingest_sensors.parse_rain((FIX / "infobanjir_sel.html").read_text(encoding="utf-8"), "SEL")
    assert len(rows) == 133
    fraser = next(r for r in rows if r["station_id"] == "3717101")
    assert fraser["name"] == "Bukit Fraser" and fraser["district"] == "Hulu Selangor"
    assert fraser["ts"] == datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)  # 22:00 MYT
    kkb = next(r for r in rows if r["station_id"] == "3516022")
    assert (kkb["rain_today_mm"], kkb["rain_1h_mm"]) == (2.0, 0.0)  # midnight vs 1-hour columns


def test_rain_page_layout_change_is_an_error():
    html = (FIX / "infobanjir_sel.html").read_text(encoding="utf-8").replace("Total 1 Hour", "Jumlah")
    with pytest.raises(ValueError):
        ingest_sensors.parse_rain(html, "SEL")


def test_river_page_and_indicator():
    rows = ingest_sensors.parse_river((FIX / "infobanjir_wl_sel.html").read_text(encoding="utf-8"), "SEL")
    assert len(rows) == 69 and all(r["indicator"] in ("NORMAL", "ALERT", "WARNING", "DANGER", None) for r in rows)
    first = rows[0]
    assert first["station_id"] == "3516423" and first["ts"] == datetime(2026, 10, 22, 14, 30, tzinfo=timezone.utc)
    assert ingest_sensors.river_indicator(48.4, 47.6, 47.9, 48.3) == "DANGER"
    assert ingest_sensors.river_indicator(47.9, 47.6, 47.9, 48.3) == "WARNING"
    assert ingest_sensors.river_indicator(45.0, 47.6, 47.9, 48.3) == "NORMAL"
    assert ingest_sensors.river_indicator(45.0, 0, 0, 0) is None


def test_station_id_grid_cell():
    assert ingest_sensors.coords_from_station_id("3717101") == (3.75, 101.75)
    assert ingest_sensors.coords_from_station_id("1437116_") == (1.45, 103.75)
    assert ingest_sensors.coords_from_station_id("PANDAMARAN") is None


def gauge(sid, lat, lon, quality="verified"):
    return {"id": sid, "kind": "rain", "name": sid, "lat": lat, "lon": lon, "location_quality": quality}


def river(sid, lat, lon):
    return {"id": sid, "kind": "river", "name": sid, "lat": lat, "lon": lon, "location_quality": "verified"}


def reading(minutes_ago, rain=None, indicator=None):
    return {"ts": NOW - timedelta(minutes=minutes_ago), "rain_1h_mm": rain, "indicator": indicator}


def test_zone_evidence_radius_freshness_and_quality():
    stations = [gauge("near", 3.20, 101.50), gauge("grid", 3.17, 101.47, "grid"),
                gauge("far", 3.40, 101.50), gauge("stale", 3.19, 101.49), river("sg", 3.25, 101.55)]
    readings = {"near": [reading(10, 35.0)], "grid": [reading(5, 70.0)], "far": [reading(5, 90.0)],
                "stale": [reading(60, 80.0)], "sg": [reading(30, indicator="WARNING")]}
    ev = sensors.zone_evidence([ELMINA], stations, readings, NOW)["elmina"]
    assert ev["rain_1h"] == 70.0            # any fresh gauge in range
    assert ev["rain_1h_verified"] == 35.0   # the grid-placed gauge can't raise (D21)
    assert ev["river"] == "WARNING" and ev["fresh_count"] == 3
    assert [s["id"] for s in ev["stations"]] == ["grid", "near", "sg"]  # nearest first
    assert sensors.official_text(ev) == "River warning – sg"
    level, ex = classify({}, None, None, None, Thresholds(), sensor=ev)
    assert level == Level.AMBER and set(ex["rules_fired"]) == {"river_warning", "gauge_1h>=31"}


def test_no_station_nearby_means_no_evidence():
    assert sensors.zone_evidence([ELMINA], [gauge("far", 4.0, 102.0)], {"far": [reading(5, 10.0)]}, NOW) == {}


def test_rain_3h_needs_three_hourly_readings():
    hist = [reading(0, 30.0), reading(60, 20.0), reading(125, 15.0)]
    assert sensors.rain_3h(hist) == 65.0
    assert sensors.rain_3h([reading(0, 30.0), reading(60, 20.0)]) is None
    assert sensors.rain_3h([reading(0, 30.0), reading(60, 20.0), reading(150, 15.0)]) is None
