"""Admin automation rules (architecture.md §3.1)."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import AppSettings, Automation, Level, QuietHours
from app.services import alerts

NOW = datetime(2026, 10, 18, 6, 40, tzinfo=timezone.utc)  # 14:40 MYT


def settings(**automation) -> AppSettings:
    return AppSettings(automation=Automation(**automation))


def raise_to(level, s, zone_id="z1", recent=None, now=NOW):
    return alerts.decide(Level.GREEN, level, recent or [], None, None, now, s, zone_id=zone_id)


def sent_red(minutes_ago):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"level": "RED", "status": "sent", "sent_at": ts, "created_at": ts}


def all_clear(s, recent=None, red_minutes_ago=90, zone_id="z1"):
    return alerts.decide(Level.GREEN, Level.GREEN, recent or [], sent_red(red_minutes_ago),
                         NOW - timedelta(minutes=45), NOW, s, zone_id=zone_id)


def test_defaults_keep_todays_behaviour():
    s = AppSettings()
    assert raise_to(Level.AMBER, s).status == "send"
    assert raise_to(Level.RED, s).status == "send"
    assert all_clear(s).status == "send"


@pytest.mark.parametrize("level,event", [(Level.AMBER, "amber"), (Level.RED, "red")])
def test_event_modes(level, event):
    assert raise_to(level, settings(modes={event: "approval"})).status == "pending_approval"
    off = raise_to(level, settings(modes={event: "off"}))
    assert off.kind == "none" and off.suppressed and off.level == level


def test_red_can_now_require_approval_without_touching_amber():
    s = settings(modes={"red": "approval"})
    assert raise_to(Level.RED, s).status == "pending_approval"
    assert raise_to(Level.AMBER, s).status == "send"


def test_zone_override_off_and_approval():
    s = settings(zone_overrides={"z1": "off", "z2": "approval"})
    assert raise_to(Level.RED, s, "z1").suppressed
    assert raise_to(Level.RED, s, "z2").status == "pending_approval"
    assert raise_to(Level.RED, s, "z3").status == "send"


def test_zone_approval_does_not_unmute_an_off_event():
    s = settings(modes={"red": "off"}, zone_overrides={"z1": "approval"})
    assert raise_to(Level.RED, s, "z1").suppressed


def test_pause_holds_instead_of_dropping():
    a = raise_to(Level.RED, settings(enabled=False))
    assert (a.kind, a.status, a.reason) == ("raise", "pending_approval", "automation paused")
    assert raise_to(Level.RED, settings(enabled=False, modes={"red": "off"})).suppressed


def test_timed_pause_expires():
    s = settings(paused_until=NOW + timedelta(minutes=30))
    assert raise_to(Level.RED, s).status == "pending_approval"
    assert raise_to(Level.RED, s, now=NOW + timedelta(minutes=31)).status == "send"


def test_naive_pause_is_utc():
    assert Automation(paused_until=datetime(2026, 1, 1)).paused_until.tzinfo is not None


def test_quiet_hours_cross_midnight():
    q = QuietHours(enabled=True, start="23:00", end="06:00")
    at = lambda h, m=0: datetime(2026, 10, 18, h, m, tzinfo=timezone.utc) - alerts.MYT  # MYT clock
    assert alerts.in_quiet_hours(q, at(23, 0)) and alerts.in_quiet_hours(q, at(2)) and alerts.in_quiet_hours(q, at(5, 59))
    assert not alerts.in_quiet_hours(q, at(6)) and not alerts.in_quiet_hours(q, at(14))
    day = QuietHours(enabled=True, start="13:00", end="15:00")
    assert alerts.in_quiet_hours(day, NOW) and not alerts.in_quiet_hours(day, NOW + timedelta(hours=1))


def test_quiet_hours_only_hold_listed_events():
    s = settings(quiet_hours={"enabled": True, "start": "14:00", "end": "15:00", "events": ["amber"]})
    assert raise_to(Level.AMBER, s).reason == "quiet hours"
    assert raise_to(Level.RED, s).status == "send"


def test_quiet_hours_validation():
    with pytest.raises(ValidationError):
        QuietHours(start="25:00")
    with pytest.raises(ValidationError):
        QuietHours(start="06:00", end="06:00")


def test_all_clear_modes():
    assert all_clear(settings(modes={"all_clear": "approval"})).status == "pending_approval"
    off = all_clear(settings(modes={"all_clear": "off"}))
    assert off.kind == "none" and off.suppressed


def test_all_clear_one_attempt_per_red_episode():
    after = (NOW - timedelta(minutes=10)).isoformat()
    before = (NOW - timedelta(minutes=200)).isoformat()
    for status in ("pending_approval", "draft", "cancelled"):
        held = {"level": "GREEN", "status": status, "created_at": after}
        assert all_clear(AppSettings(), [held]).reason == "all-clear already handled"
    old = {"level": "GREEN", "status": "cancelled", "created_at": before}  # from an earlier episode
    assert all_clear(AppSettings(), [old]).kind == "all_clear"


def test_legacy_amber_flag_maps_both_ways():
    assert AppSettings(amber_requires_approval=True).automation.modes.amber == "approval"
    s = AppSettings.model_validate({"amber_requires_approval": False, "automation": {"modes": {"amber": "approval"}}})
    assert s.amber_requires_approval is True  # automation row wins and the flag mirrors it
    assert AppSettings.model_validate({"amber_requires_approval": True, "automation": None}).automation.modes.amber == "approval"


def test_status_summary():
    st = alerts.automation_status(AppSettings(), NOW)
    assert st["state"] == "active"
    assert st["effective"] == {"amber": "auto", "red": "auto", "all_clear": "auto", "siren": "approval"}
    st = alerts.automation_status(settings(paused_until=NOW + timedelta(hours=1)), NOW)
    assert st["state"] == "paused" and st["paused_until"] and st["effective"]["red"] == "approval"
    st = alerts.automation_status(settings(modes={"amber": "off", "red": "off", "all_clear": "off"}), NOW)
    assert st["state"] == "off"
    st = alerts.automation_status(settings(quiet_hours={"enabled": True, "start": "14:00", "end": "15:00"}), NOW)
    assert st["state"] == "quiet_hours" and st["effective"]["red"] == "auto"
