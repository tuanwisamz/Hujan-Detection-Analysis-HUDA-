"""Predictions, user alerts and user logs (api-spec §5, §6, §7)."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from .. import repo
from ..auth import User
from ..models import Level
from ..ratelimit import default_limit

router = APIRouter(tags=["feeds"])


def _alert_out(w: dict) -> dict:
    zone = w.get("zones") or {}
    return {"id": w["id"], "zone_id": w["zone_id"], "zone": zone.get("name"), "zone_slug": zone.get("slug"),
            "level": w["level"], "message_en": w.get("message_en"), "message_ms": w.get("message_ms"),
            "sent_at": w.get("sent_at"), "source": w.get("source")}


@router.get("/predictions")
def predictions(zone_id: str | None = None, from_: datetime | None = Query(None, alias="from"),
                to: datetime | None = None, level: Level | None = None,
                limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                user: User = Depends(default_limit)):
    return repo.query_predictions(zone_id, from_, to, level.value if level else None, limit, cursor)


@router.get("/alerts")
def alerts(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
           level: Level | None = None, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
           user: User = Depends(default_limit)):
    """User scope: sent warnings for subscribed zones. Admins see all."""
    zone_ids = None if user.is_admin else [s["zone_id"] for s in repo.get_subscriptions(user.id)]
    res = repo.sent_alerts(zone_ids, from_, to, level.value if level else None, limit, cursor)
    return {"items": [_alert_out(w) for w in res["items"]], "next_cursor": res["next_cursor"]}


@router.get("/logs")
def user_logs(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
              limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
              user: User = Depends(default_limit)):
    """User scope: alert history entries for subscribed zones."""
    zone_ids = [s["zone_id"] for s in repo.get_subscriptions(user.id)]
    return repo.query_logs(category="alert", frm=from_, to=to, zone_ids=zone_ids, limit=limit, cursor=cursor)
