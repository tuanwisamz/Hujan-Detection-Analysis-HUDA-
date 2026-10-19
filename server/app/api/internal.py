"""Machine-to-machine routes (api-spec §11). Secret headers, no JWT."""

import hmac

from fastapi import APIRouter, BackgroundTasks, Header, Request

from .. import repo
from ..agents import report_analyst
from ..config import get_settings
from ..errors import ApiError
from ..models import IngestBody
from ..services import pipeline, telegram

router = APIRouter(prefix="/internal", tags=["internal"])

LEVEL_ICON = {"RED": "🔴", "AMBER": "🟠", "GREEN": "🟢"}


def _check(secret: str | None, expected: str) -> None:
    if not expected or not secret or not hmac.compare_digest(secret, expected):
        raise ApiError(401, "Invalid secret")


@router.post("/ingest", status_code=202)
def ingest(tasks: BackgroundTasks, body: IngestBody | None = None,
           x_cron_secret: str | None = Header(None)):
    _check(x_cron_secret, get_settings().cron_secret)
    body = body or IngestBody()
    replay = body.backfill_ts is not None or body.fixture is not None
    run_id = repo.start_run(body.backfill_ts or (repo.now() if body.fixture else None),
                            min_gap_min=0 if replay else 8)
    if not run_id:
        return {"run_id": None, "status": "skipped"}
    tasks.add_task(pipeline.run, run_id, body.backfill_ts, body.fixture)
    return {"run_id": run_id, "status": "started"}


@router.post("/daily-report", status_code=202)
def daily_report(tasks: BackgroundTasks, x_cron_secret: str | None = Header(None)):
    _check(x_cron_secret, get_settings().cron_secret)
    start, end = report_analyst.daily_period(repo.now())
    r = repo.create_report({"type": "daily", "zone_ids": None, "period_start": repo.iso(start),
                            "period_end": repo.iso(end), "created_by": "system", "status": "generating"})
    tasks.add_task(report_analyst.generate_report, r["id"])
    return {"id": r["id"], "status": "generating"}


def _status_text(arg: str) -> str:
    zone = repo.resolve_zone(arg) if arg else None
    if not zone:
        return "Usage: /status <township>, e.g. /status Elmina"
    p = repo.latest_predictions().get(zone["id"]) or {}
    level = p.get("level")
    if not level:
        return f"No data yet for {zone['name']}."
    parts = [f"{LEVEL_ICON[level]} {level} · {zone['name']}"]
    if p.get("rain_rate_max") is not None:
        parts.append(f"Max rain next 60 min: ~{round(p['rain_rate_max'])} mm/h")
    if p.get("eta_min") is not None:
        parts.append(f"Heavy rain in ~{p['eta_min']} min")
    parts.append(f"{get_settings().public_site_url}/z/{zone['slug']}")
    return "\n".join(parts)


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str | None = Header(None)):
    _check(x_telegram_bot_api_secret_token, get_settings().telegram_webhook_secret)
    chat_id, command, arg = telegram.parse_command(await request.json())
    if chat_id is None or command is None:
        return {"ok": True}
    try:
        if command == "/start":
            profile = repo.profile_by_link_code(arg) if arg else None
            if profile:
                repo.update_profile(profile["id"], {"telegram_chat_id": chat_id, "telegram_link_code": None,
                                                    "telegram_link_expires_at": None})
                repo.log_event("auth", "Telegram linked", actor=profile["id"])
                reply = "✅ Linked. You'll get HUDA alerts here for your subscribed zones. /stop to unlink."
            else:
                reply = ("Welcome to HUDA. To get personal alerts, use the link on the Settings page "
                         "(codes expire after 15 min). Try /status Elmina.")
        elif command == "/status":
            reply = _status_text(arg)
        elif command == "/stop":
            profile = repo.profile_by_chat(chat_id)
            if profile:
                repo.update_profile(profile["id"], {"telegram_chat_id": None})
            reply = "Unlinked. You won't get personal HUDA alerts any more."
        else:
            reply = "Commands: /status <township> · /stop"
        telegram.send(chat_id, reply)
    except telegram.TelegramError as exc:
        repo.log_event("alert", f"webhook reply failed: {exc}", "warn")
    return {"ok": True}

