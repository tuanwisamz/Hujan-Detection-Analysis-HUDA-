import pytest

from app.models import Level, Thresholds
from app.services.risk import classify, is_raise, sensor_check

TH = Thresholds()
SEVERE = {"severity": "severe", "title": "Danger heavy rain – Petaling"}
ACTIVE = {"severity": "active", "title": "Thunderstorm warning – Petaling"}


def st(rate=None, accum=0.0, red_min=0, very_min=0, area=0.0):
    """Zone stats as zone_stats() returns them."""
    return {"rain_rate_max": rate, "eta_min": None, "accum_1h": accum, "red_sustained_min": red_min,
            "red_area_max": area, "very_heavy_sustained_min": very_min}


def sensor(rain_1h=None, verified_1h=None, verified_3h=None, river=None, fresh=1):
    return {"rain_1h": rain_1h, "rain_1h_verified": verified_1h, "rain_3h_verified": verified_3h,
            "river": river, "fresh_count": fresh, "stations": [{"station": "Kg. Pertak", "kind": "rain"}]}


@pytest.mark.parametrize("stats, p, warning, expected, rule", [
    # RED (implementation-plan-v2 D16)
    (st(35.0, red_min=30, area=0.4), None, None, Level.RED, "nowcast_sustained>=30"),
    (st(35.0, accum=40.0), None, None, Level.RED, "nowcast_accum_1h>=40"),
    (st(80.0, very_min=20), None, None, Level.RED, "nowcast_rate>=60"),
    (None, None, SEVERE, Level.RED, "met_severe_warning"),
    # A heavy cell that is too brief or too small for RED is AMBER
    (st(273.0, red_min=20, very_min=10), None, None, Level.AMBER, "nowcast_rate>=10"),
    (st(30.0), None, None, Level.AMBER, "nowcast_rate>=10"),
    (st(10.0), None, None, Level.AMBER, "nowcast_rate>=10"),
    (st(0.0), 0.40, None, Level.AMBER, "p_ml>=0.40"),
    (st(0.0), 0.69, None, Level.AMBER, "p_ml>=0.40"),
    (None, None, ACTIVE, Level.AMBER, "met_warning"),
    # GREEN otherwise
    (st(9.9), 0.39, None, Level.GREEN, None),
    (None, None, None, Level.GREEN, None),
])
def test_rules(stats, p, warning, expected, rule):
    level, explanation = classify(stats, p, warning, None, TH)
    assert level == expected
    assert explanation["rule"] == rule


def test_red_beats_amber_and_lists_all_rules():
    level, ex = classify(st(35.0, red_min=40), 0.5, ACTIVE, None, TH)
    assert level == Level.RED
    assert ex["rules_fired"] == ["nowcast_sustained>=30", "met_warning", "p_ml>=0.40"]
    assert ex["red_rules"] == ["nowcast_sustained>=30"]


@pytest.mark.parametrize("stats, expected, bumped", [
    (st(0.0), Level.AMBER, True),
    (st(12.0), Level.AMBER, False),   # D17: AMBER is never bumped to RED
    (st(40.0, red_min=30), Level.RED, False),
])
def test_wet_ground_bump_capped_at_amber(stats, expected, bumped):
    level, ex = classify(stats, None, None, 50.0, TH)
    assert level == expected
    assert ex["wet_ground_bump"] is bumped


# ---- Sensors (D18, D19) ----

def test_ml_only_red_needs_a_sensor():
    level, ex = classify(st(0.0), 0.8, None, None, TH)
    assert level == Level.AMBER and ex["rule"] == "p_ml_unconfirmed" and ex["sensor_check"] == "no_sensor"
    level, ex = classify(st(0.0), 0.8, None, None, TH, sensor=sensor(rain_1h=2.0))
    assert level == Level.AMBER and ex["sensor_check"] == "not_yet"
    level, ex = classify(st(0.0), 0.8, None, None, TH, sensor=sensor(rain_1h=12.0))  # grid gauge may confirm
    assert level == Level.RED and ex["rule"] == "p_ml>=0.70" and ex["sensor_check"] == "confirmed"
    level, _ = classify(st(0.0), 0.8, None, None, TH, sensor=sensor(river="ALERT"))
    assert level == Level.RED


def test_radar_red_is_not_held_for_a_sensor():
    level, ex = classify(st(35.0, red_min=30), None, None, None, TH, sensor=sensor(rain_1h=0.0))
    assert level == Level.RED and ex["sensor_check"] == "not_yet"


@pytest.mark.parametrize("s, expected, rule", [
    (sensor(river="DANGER"), Level.RED, "river_danger"),
    (sensor(river="WARNING"), Level.AMBER, "river_warning"),
    (sensor(rain_1h=70.0, verified_1h=70.0), Level.RED, "gauge_1h>=60"),
    (sensor(rain_1h=20.0, verified_1h=20.0, verified_3h=65.0), Level.RED, "gauge_3h>=60"),
    (sensor(rain_1h=35.0, verified_1h=35.0), Level.AMBER, "gauge_1h>=31"),
    # A gauge placed only by its grid cell (D21) can't raise a level
    (sensor(rain_1h=90.0), Level.GREEN, None),
])
def test_sensor_alarms(s, expected, rule):
    level, ex = classify(st(0.0), None, None, None, TH, sensor=s)
    assert level == expected and ex["rule"] == rule


def test_sensor_check_states():
    assert sensor_check(None, TH) == "no_sensor"
    assert sensor_check(sensor(fresh=0, rain_1h=50.0), TH) == "no_sensor"
    assert sensor_check(sensor(rain_1h=11.0), TH) == "confirmed"
    assert sensor_check(sensor(river="NORMAL"), TH) == "not_yet"


def test_thresholds_are_settings():
    custom = Thresholds(amber_rate_mmh=5, red_rate_mmh=20, red_duration_min=10)
    level, ex = classify(st(21.0, red_min=10), None, None, None, custom)
    assert level == Level.RED and ex["rule"] == "nowcast_sustained>=20"


@pytest.mark.parametrize("bad", [
    {"amber_rate_mmh": 40, "red_rate_mmh": 30},
    {"amber_p": 0.8, "red_p": 0.7},
    {"red_rate_mmh": 150},
    {"red_rate_mmh": 60, "very_heavy_mmh": 60},
    {"gauge_amber_1h_mm": 60, "gauge_red_1h_mm": 60},
    {"red_duration_min": 25},
    {"very_heavy_duration_min": 15},
    {"red_area_frac": 0.01},
])
def test_threshold_validation(bad):
    with pytest.raises(ValueError):
        Thresholds(**bad)


def test_is_raise():
    assert is_raise(None, Level.AMBER)
    assert is_raise(Level.AMBER, Level.RED)
    assert not is_raise(Level.RED, Level.AMBER)
    assert not is_raise(Level.AMBER, Level.AMBER)
    assert not is_raise(None, Level.GREEN)
