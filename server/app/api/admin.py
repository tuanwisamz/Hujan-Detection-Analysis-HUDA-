"""Admin routes (api-spec §4, §6, §7, §9). Every write leaves a category='admin' log."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from .. import repo
from ..agents import alert_writer
from ..auth import User, clerk_set_role, require_admin
from ..errors import ApiError, not_found
from ..models import AppSettings, RoleBody, SettingsPatch, WarningIn, WarningTextPatch, ZoneIn, ZonePatch
from ..ratelimit import default_limit
from ..services import alerts, telegram
from .zones import zone_out

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(default_limit), Depends(require_admin)])

REBROADCAST_MIN = 5


def _audit(user: User, message: str, **meta) -> None:
    repo.log_event("admin", message, actor=user.id, meta=meta)


# ---- Zones ----

@router.post("/zones", status_code=201)
def create_zone(body: ZoneIn, user: User = Depends(require_admin)):
    z = repo.create_zone(body.model_dump())
    _audit(user, f"zone created: {z['name']}", zone_id=z["id"])
    return zone_out(z)


@router.patch("/zones/{zone_id}")
def update_zone(zone_id: str, body: ZonePatch, user: User = Depends(require_admin)):
    patch = body.model_dump(exclude_unset=True)
    z = repo.update_zone(zone_id, patch)
    if not z:
        raise not_found("Zone")
    _audit(user, f"zone updated: {z['name']}", zone_id=zone_id, fields=list(patch))
    return zone_out(z)


@router.delete("/zones/{zone_id}")
def delete_zone(zone_id: str, user: User = Depends(require_admin)):
    z = repo.update_zone(zone_id, {"active": False})  # soft delete
    if not z:
        raise not_found("Zone")
    _audit(user, f"zone deactivated: {z['name']}", zone_id=zone_id)
    return zone_out(z)


# ---- Warnings ----

def _warning_out(w: dict) -> dict:
    zone = w.pop("zones", None) or {}
    return {**w, "zone": zone.get("name"), "zone_slug": zone.get("slug")}


def _load(warning_id: str) -> tuple[dict, dict]:
    w = repo.get_warning(warning_id)
    if not w:
        raise not_found("Warning")
    z = repo.get_zone(w["zone_id"])
    if not z:
        raise not_found("Zone")
    return w, z


@router.get("/warnings")
def list_warnings(status: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return {"items": [_warning_out(w) for w in repo.list_warnings(status, limit)]}


@router.post("/warnings", status_code=201)
def create_warning(body: WarningIn, user: User = Depends(require_admin)):
    if not repo.get_zone(body.zone_id):
        raise not_found("Zone")
    w = repo.create_warning({"zone_id": body.zone_id, "level": body.level.value, "status": "draft",
                             "source": "manual", "created_by": user.id,
                             "message_en": body.message_en, "message_ms": body.message_ms,
                             "expires_at": repo.iso(repo.now() + timedelta(minutes=body.expires_in_min))})
    _audit(user, f"manual {body.level.value} warning drafted", zone_id=body.zone_id, warning_id=w["id"])
    return w


@router.patch("/warnings/{warning_id}")
def edit_warning_text(warning_id: str, body: WarningTextPatch, user: User = Depends(require_admin)):
    """Edit EN/BM text before approval (added to api-spec; admins correct AI drafts)."""
    w, z = _load(warning_id)
    if w["status"] not in ("draft", "pending_approval"):
        raise ApiError(409, f"Warning is {w['status']}; only draft or pending text can be edited")
    fields = body.model_dump(exclude_unset=True)  # editing one language must not clear the other
    if not fields:
        raise ApiError(422, "Send message_en and/or message_ms")
    updated = repo.update_warning(warning_id, fields)
    _audit(user, f"warning text edited: {z['name']}", zone_id=z["id"], warning_id=warning_id)
    return updated


@router.post("/warnings/{warning_id}/generate-text")
def generate_text(warning_id: str, user: User = Depends(require_admin)):
    w, z = _load(warning_id)
    pred = repo.latest_predictions().get(z["id"])
    text = alert_writer.write_alerts([alert_writer.event(z, w["level"], pred)])[0]
    if not text:  # Gemini unavailable/invalid: show the template text so the admin can edit it
        rendered = alerts.render_message(z, w["level"], pred, all_clear=w["level"] == "GREEN").splitlines()
        text = {"message_en": next((l[4:] for l in rendered if l.startswith("EN: ")), ""),
                "message_ms": next((l[4:] for l in rendered if l.startswith("BM: ")), ""),
                "fallback": True}
    stored = {k: v for k, v in text.items() if k in ("message_en", "message_ms")}
    return {**repo.update_warning(warning_id, stored), "fallback": text.get("fallback", False)}


@router.post("/warnings/{warning_id}/approve")
def approve(warning_id: str, user: User = Depends(require_admin)):
    """Approve AND send to Telegram."""
    w, z = _load(warning_id)
    if w["status"] not in ("draft", "pending_approval"):
        raise ApiError(409, f"Warning is {w['status']}; only draft or pending warnings can be approved")
    repo.update_warning(warning_id, {"approved_by": user.id})
    try:
        sent = alerts.send_warning({**w, "approved_by": user.id}, z, repo.latest_predictions().get(z["id"]),
                                   actor=user.id)
    except telegram.TelegramError as exc:
        raise ApiError(503, f"Telegram send failed: {exc}") from exc
    _audit(user, f"warning approved and sent: {z['name']} {w['level']}", zone_id=z["id"], warning_id=warning_id)
    return {"id": sent["id"], "status": sent["status"], "telegram_message_id": sent["telegram_message_id"],
            "sent_at": sent["sent_at"]}


@router.post("/warnings/{warning_id}/cancel")
def cancel(warning_id: str, user: User = Depends(require_admin)):
    """Cancel; if already sent, post a correction to the channel."""
    w, z = _load(warning_id)
    if w["status"] in ("cancelled", "expired"):
        raise ApiError(409, f"Warning is already {w['status']}")
    if w["status"] == "sent" and w.get("telegram_message_id"):
        text = alerts.render_message(z, w["level"], None, cancelled=True)
        try:
            telegram.reply_to_channel(text, w["telegram_message_id"])
        except telegram.TelegramError as exc:
            raise ApiError(503, f"Telegram correction failed: {exc}") from exc
    updated = repo.update_warning(warning_id, {"status": "cancelled"})
    _audit(user, f"warning cancelled: {z['name']} {w['level']}", zone_id=z["id"], warning_id=warning_id)
    return updated


@router.post("/warnings/{warning_id}/rebroadcast")
def rebroadcast(warning_id: str, user: User = Depends(require_admin)):
    w, z = _load(warning_id)
    if w["status"] != "sent":
        raise ApiError(409, "Only sent warnings can be re-broadcast")
    last = repo.parse_ts(w.get("last_broadcast_at") or w.get("sent_at"))
    if last and repo.now() - last < timedelta(minutes=REBROADCAST_MIN):
        raise ApiError(429, f"Re-broadcast allowed once every {REBROADCAST_MIN} min")
    try:
        sent = alerts.send_warning(w, z, repo.latest_predictions().get(z["id"]), actor=user.id)
    except telegram.TelegramError as exc:
        raise ApiError(503, f"Telegram send failed: {exc}") from exc
    _audit(user, f"warning re-broadcast: {z['name']} {w['level']}", zone_id=z["id"], warning_id=warning_id)
    return sent


# ---- Logs, runs ----

@router.get("/logs")
def admin_logs(category: str | None = None, severity: str | None = None,
               from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
               q: str | None = None, limit: int = Query(50, ge=1, le=200), cursor: str | None = None):
    return repo.query_logs(category, severity, from_, to, q, None, limit, cursor)


@router.get("/runs")
def runs(limit: int = Query(50, ge=1, le=200)):
    items = []
    for r in repo.list_runs(limit):
        started, finished = repo.parse_ts(r["started_at"]), repo.parse_ts(r.get("finished_at"))
        items.append({**r, "duration_s": round((finished - started).total_seconds(), 1) if finished else None})
    return {"items": items}


# ---- Settings, users ----

@router.get("/settings")
def get_settings_route():
    return repo.get_app_settings().model_dump()


@router.patch("/settings")
def patch_settings(body: SettingsPatch, user: User = Depends(require_admin)):
    current = repo.get_app_settings()
    patch = body.model_dump(exclude_none=True)
    merged = AppSettings.model_validate({**current.model_dump(), **patch})  # re-validates amber < red
    repo.save_app_settings({k: getattr(merged, k).model_dump() if k == "thresholds" else getattr(merged, k)
                            for k in patch}, user.id)
    _audit(user, "settings updated", fields=list(patch))
    return merged.model_dump()


@router.patch("/users/{user_id}/role")
def set_role(user_id: str, body: RoleBody, user: User = Depends(require_admin)):
    if not repo.get_profile(user_id):
        raise not_found("User")
    if user_id == user.id and body.role != "admin":
        raise ApiError(422, "You can't remove your own admin role")
    profile = repo.update_profile(user_id, {"role": body.role})
    clerk_set_role(user_id, body.role)
    _audit(user, f"role set to {body.role}", target=user_id)
    return {"id": profile["id"], "role": profile["role"]}


@router.get("/users")
def list_users():
    from ..db import sb

    rows = sb().table("profiles").select("id,email,full_name,role,created_at").order("created_at").execute().data
    return {"items": rows}

