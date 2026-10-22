"""Township sirens (api-spec §13, spec FR-35). Every write leaves an admin log."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from .. import repo
from ..auth import User, require_admin
from ..errors import ApiError, not_found
from ..models import Level, SirenIn, SirenPatch, SoundBody
from ..ratelimit import default_limit
from ..services import sirens

router = APIRouter(prefix="/admin", tags=["sirens"], dependencies=[Depends(default_limit), Depends(require_admin)])


def _audit(user: User, message: str, **meta) -> None:
    repo.log_event("admin", message, actor=user.id, meta=meta)


def _activation_out(a: dict) -> dict:
    siren, zone = a.pop("sirens", None) or {}, a.pop("zones", None) or {}
    return {**a, "siren_name": siren.get("name"), "zone_name": zone.get("name"),
            "virtual": not siren.get("endpoint_url") if siren else None}


def _siren_out(s: dict, zones: dict[str, dict], acts: list[dict]) -> dict:
    mine = [a for a in acts if a["siren_id"] == s["id"]]
    last = mine[0] if mine else None
    state = last["status"] if last and last["status"] in ("pending_approval", "active", "failed") else "idle"
    return {**s, "zone_name": (zones.get(s["zone_id"]) or {}).get("name"), "virtual": not s.get("endpoint_url"),
            "state": state, "last_activation": last}


def _get(siren_id: str) -> dict:
    s = repo.get_siren(siren_id)
    if not s:
        raise not_found("Siren")
    return s


def _zone(zone_id: str) -> dict:
    z = repo.get_zone(zone_id)
    if not z:
        raise ApiError(422, "Unknown zone")
    return z


@router.get("/sirens")
def list_sirens():
    zones = {z["id"]: z for z in repo.list_zones(active=None)}
    acts = repo.list_siren_activations(limit=200)
    return {"items": [_siren_out(s, zones, acts) for s in repo.list_sirens()]}


@router.post("/sirens", status_code=201)
def create_siren(body: SirenIn, user: User = Depends(require_admin)):
    _zone(body.zone_id)
    s = repo.create_siren(body.model_dump() | {"created_by": user.id})
    _audit(user, f"siren added: {s['name']}", siren_id=s["id"], virtual=not s.get("endpoint_url"))
    return s


@router.patch("/sirens/{siren_id}")
def update_siren(siren_id: str, body: SirenPatch, user: User = Depends(require_admin)):
    _get(siren_id)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise ApiError(422, "Nothing to update")
    if patch.get("zone_id"):
        _zone(patch["zone_id"])
    s = repo.update_siren(siren_id, patch)
    _audit(user, f"siren updated: {s['name']}", siren_id=siren_id, fields=list(patch))
    return s


@router.post("/sirens/{siren_id}/test")
def test_siren(siren_id: str, user: User = Depends(require_admin)):
    """siren.test: a short chirp so admins can check the controller without a full alarm."""
    s = _get(siren_id)
    zone = _zone(s["zone_id"])
    try:
        result = sirens.send(s, sirens.payload("siren.test", s, zone, None, repo.get_app_settings()))
    except sirens.SirenError as exc:
        _audit(user, f"siren test failed: {exc}", siren_id=siren_id)
        raise ApiError(503, f"Siren controller failed: {exc}") from exc
    _audit(user, f"siren test sent: {s['name']}", siren_id=siren_id)
    return result


@router.post("/sirens/{siren_id}/sound")
def sound_siren(siren_id: str, body: SoundBody, user: User = Depends(require_admin)):
    s = _get(siren_id)
    zone = _zone(s["zone_id"])
    if any(a["siren_id"] == siren_id and a["status"] == "active" for a in repo.open_siren_activations(s["zone_id"])):
        raise ApiError(409, "This siren is already sounding")
    row = repo.create_siren_activation({"siren_id": siren_id, "zone_id": s["zone_id"], "status": "pending_approval",
                                        "source": "manual", "reason": body.reason, "approved_by": user.id})
    _audit(user, f"siren sounded by hand: {s['name']}", siren_id=siren_id, reason=body.reason)
    return sirens.start(s, zone, row, repo.get_app_settings(), actor=user.id)


@router.get("/siren-activations")
def list_activations(status: str | None = Query(None, pattern="^(pending_approval|active|stopped|expired|cancelled|failed)$"),
                     zone_id: str | None = None, limit: int = Query(50, ge=1, le=200)):
    return {"items": [_activation_out(a) for a in repo.list_siren_activations(status, zone_id, limit)]}


def _activation(activation_id: str, status: str) -> tuple[dict, dict, dict]:
    a = repo.get_siren_activation(activation_id)
    if not a:
        raise not_found("Siren activation")
    if a["status"] != status:
        raise ApiError(409, f"Activation is {a['status']}, not {status}")
    return a, _get(a["siren_id"]), _zone(a["zone_id"])


@router.post("/siren-activations/{activation_id}/approve")
def approve(activation_id: str, user: User = Depends(require_admin)):
    a, s, zone = _activation(activation_id, "pending_approval")
    settings = repo.get_app_settings()
    age = repo.now() - repo.parse_ts(a["created_at"])
    level = (repo.latest_predictions().get(a["zone_id"]) or {}).get("level")
    if age > timedelta(minutes=settings.automation.siren.approval_expires_min) or level != Level.RED.value:
        repo.update_siren_activation(activation_id, {"status": "expired", "stopped_at": repo.iso(repo.now()),
                                                     "stop_reason": "expired" if level == Level.RED.value else "level_drop"})
        raise ApiError(409, "Too late: the approval expired or the zone is no longer RED")
    repo.update_siren_activation(activation_id, {"approved_by": user.id})
    _audit(user, f"siren approved: {s['name']}", siren_id=s["id"], activation_id=activation_id)
    return sirens.start(s, zone, a, settings, actor=user.id)


@router.post("/siren-activations/{activation_id}/stop")
def stop(activation_id: str, user: User = Depends(require_admin)):
    a, s, zone = _activation(activation_id, "active")
    _audit(user, f"siren stopped by hand: {s['name']}", siren_id=s["id"], activation_id=activation_id)
    return sirens.stop(s, zone, a, "admin", repo.get_app_settings(), actor=user.id)


@router.post("/siren-activations/{activation_id}/cancel")
def cancel(activation_id: str, user: User = Depends(require_admin)):
    a, s, _ = _activation(activation_id, "pending_approval")
    _audit(user, f"siren approval cancelled: {s['name']}", siren_id=s["id"], activation_id=activation_id)
    return repo.update_siren_activation(activation_id, {"status": "cancelled", "stopped_at": repo.iso(repo.now())})
