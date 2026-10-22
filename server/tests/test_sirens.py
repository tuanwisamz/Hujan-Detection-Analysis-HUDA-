"""Siren manager (spec FR-35, implementation-plan-v2 D22–D23)."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import repo
from app.models import AppSettings, Automation
from app.services import alerts, nowcast, sirens, synthetic
from app.services.pipeline import compute_zone_results

NOW = datetime(2026, 10, 18, 6, 40, tzinfo=timezone.utc)  # 14:40 MYT
SIREN = {"id": "s1", "zone_id": "z1", "name": "Elmina Central Park", "endpoint_url": None, "active": True}
ZONE = {"id": "z1", "name": "City of Elmina"}
RADAR_RED = {"red_rules": ["nowcast_sustained>=30"]}


def settings(**automation) -> AppSettings:
    return AppSettings(automation=Automation(**automation))


def act(status, minutes_ago, siren_id="s1"):
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    return {"id": f"a-{status}-{minutes_ago}", "siren_id": siren_id, "status": status, "created_at": ts,
            "started_at": ts if status == "active" else None}


def decide(level="RED", explanation=RADAR_RED, open_acts=(), episode=(), s=None):
    return sirens.decide("z1", level, explanation, [SIREN], list(open_acts), list(episode), NOW, s or AppSettings())


def test_default_is_approval_on_physical_red():
    [a] = decide()
    assert (a.kind, a.status, a.rule) == ("create", "pending_approval", "nowcast_sustained>=30")


def test_auto_mode_sounds_at_once():
    [a] = decide(s=settings(modes={"siren": "auto"}))
    assert a.status == "active"


@pytest.mark.parametrize("explanation", [
    {"red_rules": ["met_severe_warning"]},  # district-wide text warning
    {"red_rules": ["p_ml>=0.70"]},          # sensor-confirmed forecast, not evidence
    {"red_rules": []},
])
def test_no_siren_without_physical_evidence(explanation):
    assert decide(explanation=explanation) == []


@pytest.mark.parametrize("rules", [["river_danger"], ["gauge_1h>=60"], ["nowcast_rate>=60"], ["nowcast_accum_1h>=40"]])
def test_sensor_and_radar_rules_count(rules):
    assert decide(explanation={"red_rules": rules})[0].kind == "create"


def test_amber_never_sounds():
    assert decide(level="AMBER", explanation={"red_rules": []}) == []


def test_one_activation_per_red_episode():
    assert decide(episode=[act("expired", 20)]) == []   # a held, expired approval isn't re-queued
    assert decide(open_acts=[act("pending_approval", 5)]) == []


def test_pending_expires_and_active_stops_on_level_drop():
    actions = decide(level="AMBER", explanation={}, open_acts=[act("pending_approval", 5), act("active", 5, "s2")])
    assert [(a.kind, a.reason) for a in actions] == [("expire", "level_drop"), ("stop", "level_drop")]


def test_timeouts():
    s = AppSettings()
    actions = decide(open_acts=[act("pending_approval", 16)], episode=[act("pending_approval", 16)], s=s)
    assert [(a.kind, a.reason) for a in actions] == [("expire", "expired")]
    actions = decide(open_acts=[act("active", 30)], episode=[act("active", 30)], s=s)
    assert [(a.kind, a.reason) for a in actions] == [("stop", "max_duration")]


def test_siren_follows_automation_rules():
    assert decide(s=settings(modes={"siren": "off"})) == []
    assert decide(s=settings(modes={"siren": "auto"}, zone_overrides={"z1": "off"})) == []
    assert decide(s=settings(modes={"siren": "auto"}, zone_overrides={"z1": "approval"}))[0].status == "pending_approval"
    paused = settings(modes={"siren": "auto"}, enabled=False)
    assert decide(s=paused)[0].status == "pending_approval"
    quiet = settings(modes={"siren": "auto"}, quiet_hours={"enabled": True, "start": "14:00", "end": "15:00",
                                                           "events": ["siren"]})
    assert alerts.resolve_mode("siren", "z1", NOW, quiet) == ("approval", "quiet hours")


def test_old_automation_rows_default_to_approval():
    s = AppSettings.model_validate({"automation": {"modes": {"amber": "auto", "red": "auto", "all_clear": "auto"}}})
    assert s.automation.modes.siren == "approval" and s.automation.siren.max_on_min == 30


def test_red_since_finds_episode_start():
    rows = [{"ts": (NOW - timedelta(minutes=m)).isoformat(), "level": lv}
            for m, lv in [(0, "RED"), (10, "RED"), (20, "RED"), (30, "AMBER"), (40, "RED")]]
    assert sirens.red_since(rows) == NOW - timedelta(minutes=20)
    assert sirens.red_since([{"ts": NOW.isoformat(), "level": "AMBER"}]) is None


# ---- Webhook ----

def test_signature_matches_spec():
    assert sirens.sign("k", "1700000000", b'{"a":1}') == (
        "sha256=" + __import__("hmac").new(b"k", b'1700000000.{"a":1}', "sha256").hexdigest())


def test_send_signs_and_retries(monkeypatch):
    monkeypatch.setattr(sirens, "get_settings", lambda: type("S", (), {"siren_webhook_secret": "secret"})())
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500 if len(calls) < 2 else 200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = sirens.send({**SIREN, "endpoint_url": "https://c.example/huda"}, {"event": "siren.on"}, client)
    assert result["ok"] and len(calls) == 2
    req = calls[-1]
    assert req.headers["X-HUDA-Signature"] == sirens.sign("secret", req.headers["X-HUDA-Timestamp"], req.content)


def test_send_fails_after_retries_and_without_secret(monkeypatch):
    monkeypatch.setattr(sirens, "get_settings", lambda: type("S", (), {"siren_webhook_secret": "secret"})())
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(sirens.SirenError, match="HTTP 503"):
        sirens.send({**SIREN, "endpoint_url": "https://c.example/huda"}, {}, client)
    monkeypatch.setattr(sirens, "get_settings", lambda: type("S", (), {"siren_webhook_secret": ""})())
    with pytest.raises(sirens.SirenError, match="SIREN_WEBHOOK_SECRET"):
        sirens.send({**SIREN, "endpoint_url": "https://c.example/huda"}, {})


def test_virtual_siren_needs_no_request():
    assert sirens.send(SIREN, {"event": "siren.on"}) == {"ok": True, "virtual": True}


# ---- Integration: synthetic storm -> pending -> approve -> signed on -> off on level drop ----

class FakeDb:
    def __init__(self):
        self.acts: dict[str, dict] = {}
        self.logs: list[str] = []

    def create(self, row):
        row = {**row, "id": f"a{len(self.acts) + 1}", "created_at": repo.iso(repo.now())}
        self.acts[row["id"]] = row
        return row

    def update(self, aid, patch):
        self.acts[aid].update(patch)
        return self.acts[aid]


def test_storm_to_siren_end_to_end(monkeypatch):
    db, posts = FakeDb(), []
    siren = {**SIREN, "zone_id": "elmina", "endpoint_url": "https://c.example/huda"}
    elmina = {"id": "elmina", "name": "City of Elmina", "lat": 3.183, "lon": 101.486, "radius_m": 2500}
    clock = {"now": NOW}
    monkeypatch.setattr(repo, "now", lambda: clock["now"])
    monkeypatch.setattr(repo, "list_sirens", lambda: [siren])
    monkeypatch.setattr(repo, "open_siren_activations",
                        lambda zid=None: [a for a in db.acts.values() if a["status"] in ("pending_approval", "active")])
    monkeypatch.setattr(repo, "siren_activations_since", lambda zid, since: list(db.acts.values()))
    monkeypatch.setattr(repo, "recent_levels", lambda zid, minutes: [{"ts": NOW.isoformat(), "level": "RED"}])
    monkeypatch.setattr(repo, "create_siren_activation", db.create)
    monkeypatch.setattr(repo, "update_siren_activation", db.update)
    monkeypatch.setattr(repo, "log_event", lambda category, message, *a, **k: db.logs.append(message))
    monkeypatch.setattr(sirens, "get_settings", lambda: type("S", (), {"siren_webhook_secret": "secret"})())
    real_client = httpx.Client

    def fake_client(*a, **k):
        return real_client(transport=httpx.MockTransport(lambda r: posts.append(r) or httpx.Response(200)))
    monkeypatch.setattr(sirens.httpx, "Client", fake_client)

    observed = synthetic.storm_grids(NOW)
    forecast, _ = nowcast.nowcast(observed)
    results = compute_zone_results([elmina], observed, forecast, {}, {}, {}, AppSettings(), NOW)
    assert results["elmina"]["level"] == "RED"

    sirens.process_run("run1", {"elmina": elmina}, results, AppSettings())
    [pending] = db.acts.values()
    assert pending["status"] == "pending_approval" and not posts  # default: approval first

    sirens.start(siren, elmina, pending, AppSettings(), actor="admin_1")  # what /approve does
    on = json.loads(posts[-1].content)
    assert pending["status"] == "active" and on["event"] == "siren.on" and on["max_on_s"] == 1800
    assert posts[-1].headers["X-HUDA-Signature"] == sirens.sign("secret", posts[-1].headers["X-HUDA-Timestamp"],
                                                                posts[-1].content)

    clock["now"] = NOW + timedelta(minutes=40)
    sirens.process_run("run2", {"elmina": elmina}, {"elmina": {"level": "GREEN", "explanation": {}}}, AppSettings())
    off = json.loads(posts[-1].content)
    assert off["event"] == "siren.off" and off["reason"] == "level_drop"
    assert pending["status"] == "stopped" and pending["stop_reason"] == "level_drop"
