from fastapi import APIRouter, Depends, Query

from .. import repo
from ..errors import not_found
from ..ratelimit import default_limit

router = APIRouter(prefix="/zones", tags=["zones"], dependencies=[Depends(default_limit)])

ZONE_FIELDS = ("id", "name", "slug", "state", "district", "met_location_id", "match_terms",
               "lat", "lon", "radius_m", "polygon", "active")


def zone_out(z: dict) -> dict:
    return {k: z.get(k) for k in ZONE_FIELDS}


@router.get("")
def list_zones(active: str = Query("true", pattern="^(true|false|all)$"), state: str | None = None):
    flag = None if active == "all" else active == "true"
    return {"items": [zone_out(z) for z in repo.list_zones(active=flag, state=state)]}


@router.get("/{zone_id}")
def get_zone(zone_id: str):
    z = repo.get_zone(zone_id) or repo.resolve_zone(zone_id)
    if not z:
        raise not_found("Zone")
    p = repo.latest_predictions().get(z["id"])
    latest = None
    if p:
        latest = {k: p.get(k) for k in ("ts", "level", "rain_rate_max", "eta_min", "accum_1h", "accum_24h",
                                        "p_ml", "official_warning", "explanation")}
        inputs = (p.get("explanation") or {}).get("inputs") or {}
        latest |= {k: inputs.get(k) for k in ("red_sustained_min", "red_area_max")}
    sensors = ((p or {}).get("explanation") or {}).get("sensors") or []
    try:  # works before migration 0004 too
        siren_active = any(a["status"] == "active" for a in repo.open_siren_activations(z["id"]))
    except Exception:  # noqa: BLE001
        siren_active = False
    return {**zone_out(z), "latest": latest, "sensors": sensors, "siren_active": siren_active}


@router.get("/{zone_id}/timeseries")
def timeseries(zone_id: str, hours: int = Query(6, ge=1, le=72)):
    if not repo.get_zone(zone_id):
        raise not_found("Zone")
    return repo.zone_timeseries(zone_id, hours)
