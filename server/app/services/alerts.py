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
from ..models import LEVEL_ORDER, AppSettings, Level
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


def decide(prev: Level | None, new: Level, recent_warnings: list[dict], last_sent: dict | None,
           green_since: datetime | None, now: datetime, settings: AppSettings) -> Action:
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
        if new == Level.AMBER and settings.amber_requires_approval:
            return Action("raise", new, "pending_approval", "amber requires approval")  # FR-32
        return Action("raise", new, "send", f"raise {prev.value if prev else 'none'}->{new.value}")

    if (new == Level.GREEN and last_sent and last_sent.get("level") == Level.RED.value
            and green_since and now - green_since >= timedelta(minutes=settings.all_clear_after_min)):
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


def send_warning(warning: dict, zone: dict, prediction: dict | None, actor: str = "system") -> dict:
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
    queued: list[tuple[dict, dict, dict, Action]] = []
    for zone_id, pred in predictions.items():
        zone, new = zones[zone_id], Level(pred["level"])
        since = now - timedelta(minutes=max(settings.cooldown_min, 60))
        recent = repo.zone_warnings(zone_id, since)
        last_sent = repo.last_sent_warning(zone_id)
        streak = green_since(repo.recent_levels(zone_id, settings.all_clear_after_min + 30), new, now)
        action = decide(prev_levels.get(zone_id), new, recent, last_sent, streak, now, settings)
        if action.kind == "none":
            continue
        row = repo.create_warning({
            "zone_id": zone_id, "level": action.level.value, "source": "auto",
            "status": "pending_approval" if action.status == "pending_approval" else "draft",
            "created_by": "system", "expires_at": repo.iso(now + timedelta(hours=2)),
        })
        queued.append((row, zone, pred, action))
        repo.log_event("alert", f"{action.kind} {action.level.value} for {zone['name']} ({action.reason})",
                       meta={"zone_id": zone_id, "warning_id": row["id"], "run_id": run_id})

    # One Gemini call for every raise in this run (implementation-plan §5.3 "Bursts").
    raises = [(row, zone, pred) for row, zone, pred, a in queued if a.kind == "raise"]
    texts = alert_writer.write_alerts([alert_writer.event(zone, row["level"], pred) for row, zone, pred in raises])
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
            sent.append(send_warning(row, zone, pred))
        except telegram.TelegramError as exc:
            repo.log_event("alert", f"Telegram send failed for {zone['name']}: {exc}", "error",
                           meta={"zone_id": zone["id"], "warning_id": row["id"]})
    return sent
