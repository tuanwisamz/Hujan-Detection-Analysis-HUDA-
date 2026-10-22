"""Alert manager (spec §6.5, architecture.md §3 step 7).

`decide` is pure and unit-tested. `send_warning` / `process_run` do the IO.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .. import repo
from ..config import get_settings
from ..models import EVENTS, LEVEL_ORDER, AppSettings, Automation, Level, QuietHours
from . import telegram
from .risk import is_raise

log = logging.getLogger("huda")

MAX_MESSAGE_CHARS = 600  # implementation-plan D6: whole Telegram message
SEND_GAP_S = 3.0  # spacing between messages in a burst
MYT = timedelta(hours=8)

_env = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "templates"),
                   keep_trailing_newline=False, autoescape=False)


@dataclass
class Action:
    kind: str  # "raise" | "all_clear" | "none"
    level: Level | None = None
    status: str | None = None  # "send" | "pending_approval"
    reason: str = ""
    suppressed: bool = False  # an admin rule said "off" for this announcement


# ---- Automation rules (docs/automation-control.md §3). Pure. ----

def is_paused(a: Automation, now: datetime) -> bool:
    return (not a.enabled) or (a.paused_until is not None and now < a.paused_until)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(q: QuietHours, now: datetime) -> bool:
    """True when `now` (UTC) falls in the MYT window; windows may cross midnight."""
    if not q.enabled:
        return False
    local = now + MYT
    t, start, end = local.hour * 60 + local.minute, _minutes(q.start), _minutes(q.end)
    return start <= t < end if start < end else (t >= start or t < end)


def resolve_mode(event: str, zone_id: str | None, now: datetime, settings: AppSettings) -> tuple[str, str]:
    """("auto" | "approval" | "off", reason) for one announcement.

    Order: event rule -> zone override -> master pause -> quiet hours. Pause and quiet hours
    only turn "auto" into "approval"; they never drop a warning.
    """
    a = settings.automation
    mode = getattr(a.modes, event)
    reason = f"{event} rule: {mode}"
    override = a.zone_overrides.get(zone_id) if zone_id else None
    if override == "off":
        return "off", "zone muted by admin"
    if mode == "off":
        return "off", f"{event} announcements turned off"
    if override == "approval" and mode == "auto":
        return "approval", "zone needs approval"
    if mode == "auto" and is_paused(a, now):
        return "approval", "automation paused"
    if mode == "auto" and event in a.quiet_hours.events and in_quiet_hours(a.quiet_hours, now):
        return "approval", "quiet hours"
    return mode, reason


def automation_status(settings: AppSettings, now: datetime) -> dict:
    """Live summary for the admin dashboard."""
    a = settings.automation
    effective = {e: resolve_mode(e, None, now, settings) for e in EVENTS}
    paused, quiet = is_paused(a, now), in_quiet_hours(a.quiet_hours, now)
    if all(m == "off" for m in (a.modes.amber, a.modes.red, a.modes.all_clear)):
        state = "off"
    elif paused:
        state = "paused"
    elif quiet and a.quiet_hours.events:
        state = "quiet_hours"
    else:
        state = "active"
    return {
        "state": state,
        "paused_until": repo.iso(a.paused_until) if a.enabled and paused and a.paused_until else None,
        "quiet_now": quiet,
        "effective": {e: m for e, (m, _) in effective.items()},
        "reasons": {e: r for e, (_, r) in effective.items()},
        "zones_overridden": len(a.zone_overrides),
    }


def decide(prev: Level | None, new: Level, recent_warnings: list[dict], last_sent: dict | None,
           green_since: datetime | None, now: datetime, settings: AppSettings,
           zone_id: str | None = None) -> Action:
    """What the alert manager should do for one zone after a run."""
    if is_raise(prev, new):
        cooldown_start = now - timedelta(minutes=settings.cooldown_min)
        for w in recent_warnings:
            if w["level"] != new.value:
                continue
            if w["status"] == "pending_approval":
                return Action("none", reason="already awaiting approval")
            sent_at = repo.parse_ts(w.get("sent_at"))
            if w["status"] == "sent" and sent_at and sent_at >= cooldown_start:
                return Action("none", reason="cooldown")  # FR-31
        mode, why = resolve_mode("red" if new == Level.RED else "amber", zone_id, now, settings)
        if mode == "off":
            return Action("none", new, reason=f"not announced: {why}", suppressed=True)
        if mode == "approval":
            return Action("raise", new, "pending_approval", why)  # FR-32
        return Action("raise", new, "send", f"raise {prev.value if prev else 'none'}->{new.value}")

    if (new == Level.GREEN and last_sent and last_sent.get("level") == Level.RED.value
            and green_since and now - green_since >= timedelta(minutes=settings.all_clear_after_min)):
        # One all-clear attempt per RED episode: a held, drafted or cancelled one is not re-queued.
        red_at = repo.parse_ts(last_sent.get("sent_at"))
        for w in recent_warnings:
            created = repo.parse_ts(w.get("created_at"))
            if w["level"] == Level.GREEN.value and (red_at is None or (created and created >= red_at)):
                return Action("none", reason="all-clear already handled")
        mode, why = resolve_mode("all_clear", zone_id, now, settings)
        if mode == "off":
            return Action("none", Level.GREEN, reason=f"not announced: {why}", suppressed=True)
        if mode == "approval":
            return Action("all_clear", Level.GREEN, "pending_approval", why)
        return Action("all_clear", Level.GREEN, "send", "green after red")  # FR-30
    return Action("none")  # drops and unchanged levels send nothing (D10)


def green_since(levels_desc: list[dict], current: Level, now: datetime) -> datetime | None:
    """Start of the current unbroken GREEN streak (levels_desc = newest first, excluding now)."""
    if current != Level.GREEN:
        return None
    since = now
    for row in levels_desc:
        if row["level"] != Level.GREEN.value:
            break
        since = repo.parse_ts(row["ts"])
    return since


def render_message(zone: dict, level: str, prediction: dict | None, message_en: str | None = None,
                   message_ms: str | None = None, all_clear: bool = False, cancelled: bool = False,
                   now: datetime | None = None) -> str:
    """Full Telegram text. LLM text is used only if the whole message fits D6."""
    p = prediction or {}
    context = {
        "zone": zone["name"], "level": level, "all_clear": all_clear, "cancelled": cancelled,
        "rain_rate_max": p.get("rain_rate_max"), "eta_min": p.get("eta_min"),
        "updated_myt": ((now or repo.now()) + MYT).strftime("%H:%M"),
        "url": f"{get_settings().public_site_url.removeprefix('https://')}/z/{zone['slug']}",
    }
    template = _env.get_template("alert.j2")
    if message_en and message_ms:
        text = template.render(**context, message_en=message_en, message_ms=message_ms).strip()
        if len(text) <= MAX_MESSAGE_CHARS:
            return text
    return template.render(**context).strip()


def send_warning(warning: dict, zone: dict, prediction: dict | None, actor: str = "system",
                 send_dms: bool = True) -> dict:
    """Broadcast to the channel (+ subscriber DMs) and mark the warning sent."""
    all_clear = warning["level"] == Level.GREEN.value
    text = render_message(zone, warning["level"], prediction, warning.get("message_en"),
                          warning.get("message_ms"), all_clear=all_clear)
    message_id = telegram.send_channel(text)
    stamp = repo.iso(repo.now())
    updated = repo.update_warning(warning["id"], {"status": "sent", "sent_at": warning.get("sent_at") or stamp,
                                                  "last_broadcast_at": stamp, "telegram_message_id": message_id})
    repo.log_event("alert", f"{warning['level']} sent for {zone['name']}", actor=actor,
                   meta={"zone_id": zone["id"], "warning_id": warning["id"], "level": warning["level"],
                         "telegram_message_id": message_id})
    if send_dms:
        _send_dms(zone, warning["level"], text)
    return updated


def _send_dms(zone: dict, level: str, text: str) -> None:
    """FR-33 (stretch): DM linked users subscribed to this zone at or below this level."""
    for sub in repo.subscribers_for_zone(zone["id"]):
        if level != Level.GREEN.value and LEVEL_ORDER[Level(level)] < LEVEL_ORDER[Level(sub["min_level"])]:
            continue
        try:
            telegram.send(sub["telegram_chat_id"], text)
        except telegram.TelegramError as exc:
            repo.log_event("alert", f"DM failed: {exc}", "warn", meta={"zone_id": zone["id"]})


def process_run(run_id: str, zones: dict[str, dict], predictions: dict[str, dict],
                prev_levels: dict[str, Level | None], settings: AppSettings) -> list[dict]:
    """Decide per zone, write warnings, draft text in one batched Gemini call, send."""
    from ..agents import alert_writer  # local import: agents depend on services, not the reverse

    now = repo.now()
    auto = settings.automation
    queued: list[tuple[dict, dict, dict, Action]] = []
    for zone_id, pred in predictions.items():
        zone, new = zones[zone_id], Level(pred["level"])
        last_sent = repo.last_sent_warning(zone_id)
        since = now - timedelta(minutes=max(settings.cooldown_min, 60))
        red_at = repo.parse_ts(last_sent.get("sent_at")) if last_sent else None
        if red_at and red_at < since and last_sent.get("level") == Level.RED.value:
            since = red_at  # all-clear needs every warning since the last RED
        recent = repo.zone_warnings(zone_id, since)
        streak = green_since(repo.recent_levels(zone_id, settings.all_clear_after_min + 30), new, now)
        action = decide(prev_levels.get(zone_id), new, recent, last_sent, streak, now, settings, zone_id=zone_id)
        if action.kind == "none":
            if action.suppressed and action.level != Level.GREEN:  # all-clear re-checks every run; don't spam
                repo.log_event("alert", f"{action.level.value} for {zone['name']} {action.reason}",
                               meta={"zone_id": zone_id, "run_id": run_id, "suppressed": True})
            continue
        row = repo.create_warning({
            "zone_id": zone_id, "level": action.level.value, "source": "auto",
            "status": "pending_approval" if action.status == "pending_approval" else "draft",
            "created_by": "system", "expires_at": repo.iso(now + timedelta(minutes=auto.auto_expires_min)),
        })
        queued.append((row, zone, pred, action))
        repo.log_event("alert", f"{action.kind} {action.level.value} for {zone['name']} ({action.reason})",
                       meta={"zone_id": zone_id, "warning_id": row["id"], "run_id": run_id})

    # One Gemini call for every raise in this run (implementation-plan §5.3 "Bursts").
    raises = [(row, zone, pred) for row, zone, pred, a in queued if a.kind == "raise"]
    if auto.use_ai_text:
        texts = alert_writer.write_alerts([alert_writer.event(zone, row["level"], pred) for row, zone, pred in raises])
    else:  # admin chose the standard template
        texts = [None] * len(raises)
    for (row, _, _), text in zip(raises, texts):
        if text:
            row.update(repo.update_warning(row["id"], text))

    sent = []
    for i, (row, zone, pred, action) in enumerate(queued):
        if action.status != "send":
            continue
        if sent:
            time.sleep(SEND_GAP_S)
        try:
            sent.append(send_warning(row, zone, pred, send_dms=auto.send_dms))
        except telegram.TelegramError as exc:
            repo.log_event("alert", f"Telegram send failed for {zone['name']}: {exc}", "error",
                           meta={"zone_id": zone["id"], "warning_id": row["id"]})
    return sent
