"""Admin view of JPS sensor stations (api-spec §12, implementation-plan-v2 §6.2)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from .. import repo
from ..auth import User, require_admin
from ..errors import not_found
from ..models import StationPatch
from ..ratelimit import default_limit
from ..services import sensors

router = APIRouter(prefix="/admin/sensors", tags=["sensors"],
                   dependencies=[Depends(default_limit), Depends(require_admin)])

NEEDS_LOCATION_KM = 15.0


def _sources(run: dict | None) -> dict:
    s = (run or {}).get("sources") or {}
    return {"status": s.get("infobanjir"), "pages": s.get("infobanjir_pages") or {},
            "checked_at": (run or {}).get("finished_at")}


def station_out(s: dict, latest: dict | None, zones: list[dict], now) -> dict:
    near = []
    for z in zones:
        if s.get("lat") is None:
            break
        d = sensors.km(z["lat"], z["lon"], s["lat"], s["lon"])
        limit = sensors.GAUGE_RADIUS_KM if s["kind"] == "rain" else sensors.RIVER_RADIUS_KM
        if d <= max(limit, NEEDS_LOCATION_KM):
            near.append({"id": z["id"], "name": z["name"], "distance_km": round(d, 1), "in_range": d <= limit})
    reading = None
    if latest:
        age = int((now - latest["ts"]).total_seconds() // 60)
        reading = {k: latest.get(k) for k in ("rain_1h_mm", "rain_today_mm", "water_level_m", "indicator")}
        reading |= {"ts": repo.iso(latest["ts"]), "age_min": age,
                    "fresh": now - latest["ts"] <= (sensors.GAUGE_MAX_AGE if s["kind"] == "rain"
                                                    else sensors.RIVER_MAX_AGE)}
    return {**s, "zones": sorted(near, key=lambda z: z["distance_km"]), "latest": reading}


@router.get("")
def list_sensors(kind: str | None = Query(None, pattern="^(rain|river)$"), zone_id: str | None = None,
                 stale: bool = False, needs_location: bool = False):
    now = repo.now()
    zones = repo.list_zones()
    stations = repo.list_stations(kind)
    history = repo.sensor_readings_since([s["id"] for s in stations], now - timedelta(hours=3))
    items = []
    for s in stations:
        latest = max(history.get(s["id"], []), key=lambda r: r["ts"], default=None)
        item = station_out(s, latest, zones, now)
        if zone_id and not any(z["id"] == zone_id for z in item["zones"]):
            continue
        if stale and item["latest"] and item["latest"]["fresh"]:
            continue
        if needs_location and (s["location_quality"] == "verified" or not item["zones"]):
            continue
        items.append(item)
    items.sort(key=lambda i: (i["zones"][0]["distance_km"] if i["zones"] else 999, i.get("name") or ""))
    return {"sources": _sources(repo.last_finished_run()), "items": items}


@router.patch("/{station_id}")
def update_sensor(station_id: str, body: StationPatch, user: User = Depends(require_admin)):
    if not repo.get_station(station_id):
        raise not_found("Station")
    patch = body.model_dump(exclude_unset=True)
    if "lat" in patch:
        patch |= {"location_quality": "verified", "location_source": "admin"}
    s = repo.update_station(station_id, patch | {"updated_by": user.id, "updated_at": repo.iso(repo.now())})
    repo.log_event("admin", f"sensor station updated: {s.get('name') or station_id}", actor=user.id,
                   meta={"station_id": station_id, "fields": list(body.model_dump(exclude_unset=True))})
    return s
