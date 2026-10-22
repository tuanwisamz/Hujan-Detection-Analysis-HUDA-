import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Response

from .. import repo
from ..auth import User, clerk_user, current_user
from ..config import get_settings
from ..errors import ApiError
from ..models import ProfilePatch, SubscriptionsPut, SyncBody
from ..ratelimit import default_limit

router = APIRouter(prefix="/me", tags=["me"], dependencies=[Depends(default_limit)])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _me(profile: dict) -> dict:
    return {"id": profile["id"], "email": profile.get("email"), "full_name": profile.get("full_name"),
            "role": profile.get("role", "user"), "language": profile.get("language", "en"),
            "theme": profile.get("theme") or "system",
            "telegram_linked": profile.get("telegram_chat_id") is not None,
            "onboarded": bool(profile.get("onboarded"))}


@router.post("/sync")
def sync(body: SyncBody | None = None, user: User = Depends(current_user)):
    """Upsert the Clerk user into profiles. Email comes from Clerk's API when configured."""
    body = body or SyncBody()
    row = {"id": user.id}
    clerk = clerk_user(user.id)
    if clerk:
        emails = clerk.get("email_addresses") or []
        primary = next((e for e in emails if e.get("id") == clerk.get("primary_email_address_id")), None)
        row["email"] = (primary or (emails[0] if emails else {})).get("email_address")
        name = " ".join(p for p in (clerk.get("first_name"), clerk.get("last_name")) if p)
        row["full_name"] = name or None
    else:
        row["email"], row["full_name"] = body.email, body.full_name
    if not user.profile:
        repo.log_event("auth", "new user signed up", actor=user.id)
    row = {k: v for k, v in row.items() if v is not None or k == "id"}
    return _me(repo.upsert_profile(row))


@router.get("")
def get_me(user: User = Depends(current_user)):
    if not user.profile:
        raise ApiError(404, "Profile not found; call POST /me/sync first")
    return _me(user.profile)


@router.patch("")
def patch_me(body: ProfilePatch, user: User = Depends(current_user)):
    patch = body.model_dump(exclude_none=True)
    return _me(repo.update_profile(user.id, patch) if patch else user.profile)


@router.get("/subscriptions")
def get_subscriptions(user: User = Depends(current_user)):
    return {"subscriptions": repo.get_subscriptions(user.id)}


@router.put("/subscriptions")
def put_subscriptions(body: SubscriptionsPut, user: User = Depends(current_user)):
    valid = {z["id"] for z in repo.list_zones()}
    subs = [{"zone_id": s.zone_id, "min_level": s.min_level.value} for s in body.subscriptions]
    unknown = [s["zone_id"] for s in subs if s["zone_id"] not in valid]
    if unknown:
        raise ApiError(422, f"Unknown or inactive zone(s): {', '.join(unknown)}")
    return {"subscriptions": repo.put_subscriptions(user.id, subs)}


@router.post("/telegram/link")
def telegram_link(user: User = Depends(current_user)):
    code = "HUDA-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
    expires = repo.now() + timedelta(minutes=15)
    repo.update_profile(user.id, {"telegram_link_code": code, "telegram_link_expires_at": repo.iso(expires)})
    bot = get_settings().telegram_bot_username
    return {"code": code, "deep_link": f"https://t.me/{bot}?start={code}", "expires_at": repo.iso(expires)}


@router.delete("/telegram/link", status_code=204)
def telegram_unlink(user: User = Depends(current_user)):
    repo.update_profile(user.id, {"telegram_chat_id": None, "telegram_link_code": None,
                                  "telegram_link_expires_at": None})
    return Response(status_code=204)
