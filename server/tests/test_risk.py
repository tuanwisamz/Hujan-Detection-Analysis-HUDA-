import pytest

from app.models import Level, Thresholds
from app.services.risk import classify, is_raise

TH = Thresholds()
SEVERE = {"severity": "severe", "title": "Danger heavy rain – Petaling"}
ACTIVE = {"severity": "active", "title": "Thunderstorm warning – Petaling"}


@pytest.mark.parametrize("rate, p, warning, acc24, expected, rule", [
    # RED if ANY of these hold
    (30.0, None, None, None, Level.RED, "nowcast_rate>=30"),
    (5.0, 0.70, None, None, Level.RED, "p_ml>=0.70"),
    (None, None, SEVERE, None, Level.RED, "met_severe_warning"),
    # AMBER if ANY of these hold
    (10.0, None, None, None, Level.AMBER, "nowcast_rate>=10"),
    (29.9, 0.1, None, None, Level.AMBER, "nowcast_rate>=10"),
    (0.0, 0.40, None, None, Level.AMBER, "p_ml>=0.40"),
    (0.0, 0.69, None, None, Level.AMBER, "p_ml>=0.40"),
    (None, None, ACTIVE, None, Level.AMBER, "met_warning"),
    # GREEN otherwise
    (9.9, 0.39, None, 10.0, Level.GREEN, None),
    (None, None, None, None, Level.GREEN, None),
])
def test_rules(rate, p, warning, acc24, expected, rule):
    level, explanation = classify(rate, p, warning, acc24, TH)
    assert level == expected
    assert explanation["rule"] == rule


def test_red_beats_amber_and_lists_all_rules():
    level, ex = classify(35.0, 0.5, ACTIVE, None, TH)
    assert level == Level.RED
    assert ex["rules_fired"] == ["nowcast_rate>=30", "p_ml>=0.40", "met_warning"]


@pytest.mark.parametrize("base_rate, expected", [(0.0, Level.AMBER), (12.0, Level.RED), (40.0, Level.RED)])
def test_wet_ground_bump_one_step_capped_at_red(base_rate, expected):
    level, ex = classify(base_rate, None, None, 50.0, TH)
    assert level == expected
    assert ex["wet_ground_bump"] is (base_rate < 30)


def test_thresholds_are_settings():
    custom = Thresholds(amber_rate_mmh=5, red_rate_mmh=20)
    assert classify(21.0, None, None, None, custom)[0] == Level.RED
    assert classify(21.0, None, None, None, custom)[1]["rule"] == "nowcast_rate>=20"


def test_amber_threshold_cannot_exceed_red():
    with pytest.raises(ValueError):
        Thresholds(amber_rate_mmh=40, red_rate_mmh=30)
    with pytest.raises(ValueError):
        Thresholds(amber_p=0.8, red_p=0.7)
    with pytest.raises(ValueError):
        Thresholds(red_rate_mmh=150)


def test_is_raise():
    assert is_raise(None, Level.AMBER)
    assert is_raise(Level.AMBER, Level.RED)
    assert not is_raise(Level.RED, Level.AMBER)
    assert not is_raise(Level.AMBER, Level.AMBER)
    assert not is_raise(None, Level.GREEN)
