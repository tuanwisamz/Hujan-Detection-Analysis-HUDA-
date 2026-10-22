"""Siren manager (spec FR-35, architecture §3.3, implementation-plan-v2 D22–D23).

`decide` is pure and unit-tested. `send` and `process_run` do the IO. Agents never
import this module (guardrail test): only the pipeline and admins sound a siren.
"""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from .. import repo
from ..config import get_settings
from ..models import AppSettings, Level
from .alerts import resolve_mode

log = logging.getLogger("huda")

# RED rules backed by radar or sensors. A MET text warning or a sensor-confirmed ML RED
# doesn't sound a siren: it is district-wide or still a forecast.
PHYSICAL_RULES = ("nowcast_sustained", "nowcast_accum_1h", "nowcast_rate", "gauge_", "river_danger")
TIMEOUT_S = 5.0
RETRIES = 2


class SirenError(RuntimeError):
    pass


@dataclass
class SirenAction:
    kind: str  # "create" | "expire" | "stop"
    siren_id: str
    activation_id: str | None = None
    status: str | None = None  # for create: "active" | "pending_approval"
    reason: str = ""
    rule: str | None = None


def physical_rule(level: str, explanation: dict | None) -> str | None:
    """The first RED rule that comes from radar or a sensor, or None."""
    if level != Level.RED.value:
        return None
    return next((r for r in (explanation or {}).get("red_rules", []) if r.startswith(PHYSICAL_RULES)), None)


def red_since(levels_desc: list[dict]) -> datetime | None:
    """Start of the current RED episode from predictions newest-first, or None if not RED now."""
    start = None
    for row in levels_desc:
        if row["level"] != Level.RED.value:
            break
        start = repo.parse_ts(row["ts"])
    return start


def decide(zone_id: str, level: str, explanation: dict | None, sirens: list[dict], open_acts: list[dict],
           episode_acts: list[dict], now: datetime, settings: AppSettings) -> list[SirenAction]:
    """What to do with one zone's sirens after a run.

    sirens: the zone's active sirens. open_acts: their pending/active activations.
    episode_acts: activations of any status created since the current RED episode began.
    """
    timing = settings.automation.siren
    actions: list[SirenAction] = []
    for a in open_acts:
        created = repo.parse_ts(a.get("started_at") or a["created_at"])
        if level != Level.RED.value:
            kind = "stop" if a["status"] == "active" else "expire"
            actions.append(SirenAction(kind, a["siren_id"], a["id"], reason="level_drop"))
        elif a["status"] == "active" and now - created >= timedelta(minutes=timing.max_on_min):
            actions.append(SirenAction("stop", a["siren_id"], a["id"], reason="max_duration"))
        elif a["status"] == "pending_approval" and now - created >= timedelta(minutes=timing.approval_expires_min):
            actions.append(SirenAction("expire", a["siren_id"], a["id"], reason="expired"))

    rule = physical_rule(level, explanation)
    if rule is None:
        return actions
    mode, reason = resolve_mode("siren", zone_id, now, settings)
    if mode == "off":
        return actions
    used = {a["siren_id"] for a in episode_acts} | {a["siren_id"] for a in open_acts}
    for s in sirens:
        if s["id"] not in used:
            actions.append(SirenAction("create", s["id"], status="active" if mode == "auto" else "pending_approval",
                                       reason=reason, rule=rule))
    return actions


# ---- IO ----

def sign(secret: str, timestamp: str, body: bytes) -> str:
    """X-HUDA-Signature value: sha256=HMAC(secret, timestamp + "." + body)."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def payload(event: str, siren: dict, zone: dict, activation: dict | None, settings: AppSettings,
            reason: str | None = None) -> dict:
    out = {"event": event, "activation_id": (activation or {}).get("id"), "siren_id": siren["id"],
           "zone": {"id": zone["id"], "name": zone["name"]}, "level": Level.RED.value if event == "siren.on" else None,
           "rule": (activation or {}).get("rule"), "max_on_s": settings.automation.siren.max_on_min * 60,
           "sent_at": repo.iso(repo.now())}
    if event == "siren.test":
        out |= {"level": None, "max_on_s": 5}
    if reason:
        out["reason"] = reason
    return out


def send(siren: dict, body: dict, client: httpx.Client | None = None) -> dict:
    """POST one signed event. Virtual sirens (no endpoint) succeed without a request."""
    if not siren.get("endpoint_url"):
        return {"ok": True, "virtual": True}
    secret = get_settings().siren_webhook_secret
    if not secret:
        raise SirenError("SIREN_WEBHOOK_SECRET is not set")
    raw = json.dumps(body, separators=(",", ":")).encode()
    stamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", "X-HUDA-Timestamp": stamp,
               "X-HUDA-Signature": sign(secret, stamp, raw)}
    http = client or httpx.Client(timeout=TIMEOUT_S)
    last = ""
    try:
        for _ in range(RETRIES + 1):
            t0 = time.monotonic()
            try:
                r = http.post(siren["endpoint_url"], content=raw, headers=headers)
            except httpx.HTTPError as exc:
                last = str(exc) or exc.__class__.__name__
                continue
            if r.is_success:
                return {"ok": True, "status_code": r.status_code, "latency_ms": int((time.monotonic() - t0) * 1000)}
            last = f"HTTP {r.status_code}"
    finally:
        if client is None:
            http.close()
    raise SirenError(f"{siren['name']}: {last}")


def start(siren: dict, zone: dict, activation: dict, settings: AppSettings, actor: str = "system") -> dict:
    """Mark an activation active and send siren.on; failure marks it failed."""
    stamp = repo.iso(repo.now())
    try:
        send(siren, payload("siren.on", siren, zone, activation, settings))
    except SirenError as exc:
        repo.log_event("siren", f"siren failed to start: {exc}", "error", actor=actor,
                       meta={"zone_id": zone["id"], "siren_id": siren["id"], "activation_id": activation["id"]})
        return repo.update_siren_activation(activation["id"], {"status": "failed", "stopped_at": stamp,
                                                               "stop_reason": "failed", "last_error": str(exc)[:300]})
    repo.log_event("siren", f"siren sounding: {siren['name']} ({zone['name']})", actor=actor,
                   meta={"zone_id": zone["id"], "siren_id": siren["id"], "activation_id": activation["id"]})
    return repo.update_siren_activation(activation["id"], {"status": "active", "started_at": stamp})


def stop(siren: dict, zone: dict, activation: dict, reason: str, settings: AppSettings, actor: str = "system") -> dict:
    """Mark an activation stopped and send siren.off (a failed off is logged; the controller self-silences)."""
    patch = {"status": "stopped", "stopped_at": repo.iso(repo.now()), "stop_reason": reason}
    try:
        send(siren, payload("siren.off", siren, zone, activation, settings, reason=reason))
    except SirenError as exc:
        patch["last_error"] = str(exc)[:300]
        repo.log_event("siren", f"siren stop message failed: {exc}", "error", actor=actor,
                       meta={"zone_id": zone["id"], "siren_id": siren["id"], "activation_id": activation["id"]})
    repo.log_event("siren", f"siren stopped ({reason}): {siren['name']} ({zone['name']})", actor=actor,
                   meta={"zone_id": zone["id"], "siren_id": siren["id"], "activation_id": activation["id"]})
    return repo.update_siren_activation(activation["id"], patch)


def process_run(run_id: str, zones: dict[str, dict], predictions: dict[str, dict], settings: AppSettings) -> None:
    """Pipeline step 7b: create, expire or stop activations for every zone that has sirens."""
    sirens = [s for s in repo.list_sirens() if s["active"]]
    if not sirens:
        return
    now = repo.now()
    by_zone: dict[str, list[dict]] = {}
    for s in sirens:
        by_zone.setdefault(s["zone_id"], []).append(s)
    by_id = {s["id"]: s for s in sirens}
    for zone_id, zone_sirens in by_zone.items():
        pred, zone = predictions.get(zone_id), zones.get(zone_id)
        if not pred or not zone:
            continue
        open_acts = repo.open_siren_activations(zone_id)
        since = red_since(repo.recent_levels(zone_id, 24 * 60)) if pred["level"] == Level.RED.value else None
        episode = repo.siren_activations_since(zone_id, since) if since else []
        for act in decide(zone_id, pred["level"], pred.get("explanation"), zone_sirens, open_acts, episode,
                          now, settings):
            siren = by_id.get(act.siren_id) or repo.get_siren(act.siren_id)
            if act.kind == "create":
                row = repo.create_siren_activation({"siren_id": act.siren_id, "zone_id": zone_id, "status": act.status,
                                                    "source": "auto", "rule": act.rule, "reason": act.reason})
                if act.status == "active":
                    start(siren, zone, row, settings)
                else:
                    repo.log_event("siren", f"siren needs approval: {siren['name']} ({zone['name']})",
                                   meta={"zone_id": zone_id, "siren_id": siren["id"], "activation_id": row["id"],
                                         "run_id": run_id, "rule": act.rule})
            elif act.kind == "expire":
                repo.update_siren_activation(act.activation_id, {"status": "expired", "stopped_at": repo.iso(now),
                                                                 "stop_reason": act.reason})
                repo.log_event("siren", f"siren approval expired ({act.reason}): {siren['name']}",
                               meta={"zone_id": zone_id, "activation_id": act.activation_id})
            else:
                activation = next(a for a in open_acts if a["id"] == act.activation_id)
                stop(siren, zone, activation, act.reason, settings)
