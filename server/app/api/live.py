from fastapi import APIRouter, Depends

from .. import repo
from ..auth import User
from ..config import get_settings
from ..ratelimit import default_limit
from ..services import ingest_radar
from ..services.grid import ZOOM

router = APIRouter(tags=["live"])

ATTRIBUTION = "Weather radar by RainViewer"
SOURCE_KEYS = {"radar": "radar", "open_meteo": "open_meteo", "met_warnings": "met_warnings"}


def _data_status(run: dict | None) -> dict:
    sources = (run or {}).get("sources") or {}
    out = {}
    for key in SOURCE_KEYS:
        v = sources.get(key)
        out[key] = "ok" if v in ("ok", "stale", "synthetic", "archive", "skipped") else "degraded"
    return out


def zone_live(z: dict, p: dict | None, subscribed: bool) -> dict:
    p = p or {}
    return {"id": z["id"], "name": z["name"], "slug": z["slug"], "state": z.get("state"),
            "district": z.get("district"), "lat": z["lat"], "lon": z["lon"], "radius_m": z.get("radius_m"),
            "polygon": z.get("polygon"), "level": p.get("level"), "rain_rate_max": p.get("rain_rate_max"),
            "eta_min": p.get("eta_min"), "p_ml": p.get("p_ml"), "official_warning": p.get("official_warning"),
            "replay": bool((p.get("explanation") or {}).get("replay_of")),
            "subscribed": subscribed, "updated_at": p.get("ts")}


@router.get("/live/summary")
def live_summary(user: User = Depends(default_limit)):
    zones = repo.list_zones()
    latest = repo.latest_predictions()
    subscribed = {s["zone_id"] for s in repo.get_subscriptions(user.id)}
    items = [zone_live(z, latest.get(z["id"]), z["id"] in subscribed) for z in zones]
    items.sort(key=lambda z: (not z["subscribed"], z["name"]))  # subscribed zones pinned first
    counts = {"GREEN": 0, "AMBER": 0, "RED": 0}
    for z in items:
        if z["level"] in counts:
            counts[z["level"]] += 1
    return {"generated_at": repo.iso(repo.now()), "data_status": _data_status(repo.last_finished_run()),
            "counts": counts, "zones": items}


@router.get("/radar/frames")
def radar_frames(user: User = Depends(default_limit)):
    display = get_settings().rainviewer_display_options
    try:
        observed = [{"ts": repo.iso(f.ts), "tile_url": f.tile_url(display), "max_native_zoom": ZOOM}
                    for f in ingest_radar.list_frames()]
    except Exception:  # noqa: BLE001 — fall back to what the last run saw
        run = repo.last_finished_run()
        observed = [{"ts": r["ts"], "tile_url": r["source_url"], "max_native_zoom": ZOOM}
                    for r in (repo.frames_for_run(run["id"], "observed") if run else [])]
    run = repo.last_run_with_nowcast()
    nowcast = [{"ts": r["ts"], "image_url": r["image_path"], "bounds": r["bounds"]}
               for r in (repo.frames_for_run(run["id"], "nowcast") if run else [])]
    return {"observed": observed, "nowcast": nowcast, "attribution": ATTRIBUTION}
