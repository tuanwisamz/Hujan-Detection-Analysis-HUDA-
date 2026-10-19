from datetime import datetime, timedelta, timezone

from app.models import AppSettings, Level
from app.services import alerts

NOW = datetime(2026, 10, 18, 6, 40, tzinfo=timezone.utc)
S = AppSettings()
ZONE = {"id": "z1", "name": "City of Elmina", "slug": "city-of-elmina"}


def sent(level, minutes_ago):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"level": level, "status": "sent", "sent_at": ts, "created_at": ts}


def test_raise_sends():
    a = alerts.decide(Level.GREEN, Level.RED, [], None, None, NOW, S)
    assert (a.kind, a.level, a.status) == ("raise", Level.RED, "send")


def test_cooldown_blocks_same_level_within_30_min():
    a = alerts.decide(Level.AMBER, Level.RED, [sent("RED", 10)], sent("RED", 10), None, NOW, S)
    assert a.kind == "none" and a.reason == "cooldown"


def test_cooldown_expires():
    a = alerts.decide(Level.AMBER, Level.RED, [sent("RED", 31)], sent("RED", 31), None, NOW, S)
    assert a.kind == "raise"


def test_cooldown_is_per_level():
    a = alerts.decide(Level.AMBER, Level.RED, [sent("AMBER", 5)], sent("AMBER", 5), None, NOW, S)
    assert a.kind == "raise"


def test_amber_requires_approval_toggle():
    s = AppSettings(amber_requires_approval=True)
    assert alerts.decide(Level.GREEN, Level.AMBER, [], None, None, NOW, s).status == "pending_approval"
    assert alerts.decide(Level.GREEN, Level.RED, [], None, None, NOW, s).status == "send"  # RED always auto


def test_pending_warning_not_duplicated():
    pending = {"level": "AMBER", "status": "pending_approval", "sent_at": None}
    assert alerts.decide(Level.GREEN, Level.AMBER, [pending], None, None, NOW, S).kind == "none"


def test_drop_sends_nothing():
    assert alerts.decide(Level.RED, Level.AMBER, [], sent("RED", 5), None, NOW, S).kind == "none"


def test_all_clear_after_30_min_green_following_red():
    since = NOW - timedelta(minutes=30)
    a = alerts.decide(Level.GREEN, Level.GREEN, [], sent("RED", 60), since, NOW, S)
    assert (a.kind, a.level) == ("all_clear", Level.GREEN)


def test_no_all_clear_too_soon_or_after_amber_or_twice():
    assert alerts.decide(Level.GREEN, Level.GREEN, [], sent("RED", 60), NOW - timedelta(minutes=20), NOW, S).kind == "none"
    assert alerts.decide(Level.GREEN, Level.GREEN, [], sent("AMBER", 60), NOW - timedelta(hours=1), NOW, S).kind == "none"
    assert alerts.decide(Level.GREEN, Level.GREEN, [], sent("GREEN", 5), NOW - timedelta(hours=1), NOW, S).kind == "none"


def test_green_since_walks_streak():
    rows = [{"ts": (NOW - timedelta(minutes=m)).isoformat(), "level": lvl}
            for m, lvl in [(10, "GREEN"), (20, "GREEN"), (30, "GREEN"), (40, "RED")]]
    assert alerts.green_since(rows, Level.GREEN, NOW) == NOW - timedelta(minutes=30)
    assert alerts.green_since(rows, Level.RED, NOW) is None


def test_template_matches_api_spec_format():
    text = alerts.render_message(ZONE, "RED", {"rain_rate_max": 38.4, "eta_min": 20}, now=NOW)
    lines = text.splitlines()
    assert lines[0] == "🔴 RED · City of Elmina"
    assert lines[1].startswith("EN: Intense rain (~38 mm/h) expected in ~20 min.")
    assert lines[2].startswith("BM: Hujan lebat (~38 mm/j) dijangka dalam ~20 minit.")
    assert lines[3] == "Updated 14:40 MYT · huda.netlify.app/z/city-of-elmina"
    assert len(text) <= alerts.MAX_MESSAGE_CHARS


def test_template_variants_fit_600_chars():
    for level, pred, kw in [("AMBER", {"rain_rate_max": 12, "eta_min": 30}, {}),
                            ("AMBER", None, {}), ("RED", {"rain_rate_max": 50, "eta_min": 0}, {}),
                            ("RED", {"rain_rate_max": None}, {}), ("GREEN", None, {"all_clear": True}),
                            ("RED", None, {"cancelled": True})]:
        text = alerts.render_message(ZONE, level, pred, now=NOW, **kw)
        assert len(text) <= 600 and "EN: " in text and "BM: " in text


def test_llm_text_used_only_if_it_fits():
    short = alerts.render_message(ZONE, "RED", None, "Short EN.", "Pendek BM.", now=NOW)
    assert "EN: Short EN." in short
    long = alerts.render_message(ZONE, "RED", None, "x" * 400, "y" * 400, now=NOW)
    assert "EN: Intense rain" in long  # fell back to the template
