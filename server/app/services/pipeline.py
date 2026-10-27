"""The 10-minute pipeline run (architecture.md §3, steps 1–8).

Every source is isolated: a failure is recorded in runs.sources and the run
continues with what's left (NFR-07). `compute_zone_results` is the pure core
(steps 4–6) so tests and backfill exercise exactly the production logic.
"""

import logging
import time
from datetime import datetime, timedelta

import numpy as np

from .. import repo
from ..config import get_settings
from ..models import AppSettings, Level
from . import (alerts, classifier, ingest_radar, ingest_sensors, ingest_weather, nowcast, palette, sensors,
               sirens, storage, synthetic)
from .features import accum_24h, build_features, current_index
from .grid import DbzGrid
from .risk import classify
from .zone_stats import EMPTY, zone_mask, zone_stats

log = logging.getLogger("huda")

_mask_cache: dict[tuple, np.ndarray] = {}


def _masks(zones: list[dict], grid: DbzGrid) -> dict[str, np.ndarray]:
    out = {}
    for z in zones:
        key = (z["id"], z["lat"], z["lon"], z.get("radius_m"), str(z.get("polygon")), grid.bounds.x0,
               grid.bounds.y0, grid.bounds.nx, grid.bounds.ny)
        if key not in _mask_cache:
            _mask_cache[key] = zone_mask(z, grid.bounds)
        out[z["id"]] = _mask_cache[key]
    return out


def compute_zone_results(zones: list[dict], observed: list[DbzGrid], forecast: list[DbzGrid],
                         weather: dict[str, dict], met: dict[str, dict], sensor_ev: dict[str, dict],
                         settings: AppSettings, now: datetime,
                         weather_fcst: dict[str, dict] | None = None) -> dict[str, dict]:
    """Steps 4–6: zone stats -> features + classifier -> risk rules. Pure (no IO).

    sensor_ev: sensors.zone_evidence() output, {} when sensors are off or failed.
    """
    th = settings.thresholds
    stats: dict[str, dict] = {}
    if observed or forecast:
        ref = (observed or forecast)[-1]
        current = palette.dbz_to_rate(observed[-1].dbz) if observed else None
        rates = [palette.dbz_to_rate(g.dbz) for g in forecast]
        stats = zone_stats(current, rates, _masks(zones, ref), heavy_mmh=th.amber_rate_mmh,
                           red_mmh=th.red_rate_mmh, red_area_frac=th.red_area_frac,
                           very_heavy_mmh=th.very_heavy_mmh, very_heavy_area_frac=th.very_heavy_area_frac)

    results = {}
    for z in zones:
        s = stats.get(z["id"], EMPTY)
        series = weather.get(z["id"])
        p_ml, top, acc24 = None, [], None
        if series and series.get("time"):
            t = current_index(series["time"], now)
            acc24 = accum_24h(series, t)
            fcst = (weather_fcst or {}).get(z["id"])
            fcst_t = current_index(fcst["time"], now) if fcst and fcst.get("time") else None
            feats = build_features(series, t, z["lat"], z["lon"], series["time"][t],
                                   fcst=fcst if fcst_t is not None else None, fcst_t=fcst_t)
            p_ml, top = classifier.predict(feats)
        warning = met.get(z["id"])
        ev = sensor_ev.get(z["id"])
        level, explanation = classify(s, p_ml, warning, acc24, th, top, sensor=ev)
        official = "; ".join(x for x in (warning["title"] if warning else None, sensors.official_text(ev)) if x) or None
        results[z["id"]] = {"zone_id": z["id"], "rain_rate_max": s["rain_rate_max"], "eta_min": s["eta_min"],
                            "accum_1h": s["accum_1h"], "accum_24h": acc24, "p_ml": p_ml,
                            "official_warning": official, "level": level.value, "explanation": explanation}
    return results


def station_row(r: dict) -> dict:
    """A new sensor_stations row, placed at the station ID's 0.1° cell until an admin checks it (D21)."""
    coords = ingest_sensors.coords_from_station_id(r["station_id"])
    return {"id": repo.station_key(r["kind"], r["station_id"]), "kind": r["kind"], "source": "infobanjir",
            "station_code": r["station_id"], "name": r.get("name"), "district": r.get("district"),
            "state": r.get("state"), "lat": coords[0] if coords else None, "lon": coords[1] if coords else None,
            "location_quality": "grid", "location_source": "station_id" if coords else None}


def _sensor_evidence(zones: list[dict], now: datetime, sources: dict) -> dict[str, dict]:
    """Fetch InfoBanjir, store the readings, and build per-zone evidence."""
    readings, pages = ingest_sensors.fetch_all()
    ok = sum(v == "ok" for v in pages.values())
    sources["infobanjir"] = "ok" if ok == len(pages) else "partial" if ok else "failed"
    sources["infobanjir_pages"] = pages
    stations = {s["id"]: s for s in repo.list_stations()}
    new = {}
    for r in readings:
        sid = repo.station_key(r["kind"], r["station_id"])
        if sid not in stations and sid not in new:
            new[sid] = station_row(r)
    repo.add_stations(list(new.values()))
    stations |= new
    repo.insert_sensor_readings([
        {"station_id": repo.station_key(r["kind"], r["station_id"]), "ts": repo.iso(r["ts"]),
         "rain_1h_mm": r.get("rain_1h_mm"), "rain_today_mm": r.get("rain_today_mm"),
         "water_level_m": r.get("water_level_m"), "indicator": r.get("indicator")}
        for r in readings if r.get("ts")])
    near = sorted({s["id"] for z in zones for s, _ in sensors.stations_near(z, list(stations.values()))})
    history = repo.sensor_readings_since(near, now - timedelta(hours=2, minutes=20))
    return sensors.zone_evidence(zones, list(stations.values()), history, now)


def _status(sources: dict) -> str:
    core = [sources.get(k) for k in ("radar", "open_meteo", "nowcast")]
    if all(v in ("ok", "stale", "synthetic", "archive") for v in core) and sources.get("met_warnings") in ("ok", "skipped"):
        return "ok"
    return "degraded"


def run(run_id: str, backfill_ts: datetime | None = None, fixture: str | None = None) -> None:
    started = time.monotonic()
    sources: dict = {"mode": "backfill" if (backfill_ts or fixture) else "live"}
    replay = sources["mode"] == "backfill"
    try:
        settings = repo.get_app_settings()
        if not settings.pipeline_enabled and not replay:
            repo.finish_run(run_id, "skipped", {"reason": "pipeline_enabled is false"})
            return
        zones = repo.list_zones()
        now = repo.now()

        # 1. Radar
        observed: list[DbzGrid] = []
        frames: list[ingest_radar.Frame] = []
        try:
            if fixture == "synthetic":
                observed = synthetic.storm_grids(synthetic.floor_10min(backfill_ts or now))
                sources["radar"] = "synthetic"
            elif backfill_ts:
                observed = storage.load_archived(backfill_ts) or []
                if not observed:
                    raise LookupError(f"no archived storm within 30 min of {repo.iso(backfill_ts)}")
                sources["radar"] = "archive"
            else:
                frames = ingest_radar.list_frames()
                observed = ingest_radar.load_recent_grids(frames, 6)
                sources["radar"] = "ok"
        except Exception as exc:  # noqa: BLE001
            sources["radar"] = "failed"
            repo.log_event("ingest", f"radar failed: {exc}", "error", meta={"run_id": run_id})

        display = get_settings().rainviewer_display_options
        frame_rows = [{"run_id": run_id, "ts": repo.iso(f.ts), "kind": "observed",
                       "source_url": f.tile_url(display)} for f in frames]

        if not replay and observed:  # storm recorder (D2)
            try:
                if storage.should_archive(observed):
                    sources["archive"] = storage.archive_storm(observed)
            except Exception as exc:  # noqa: BLE001
                repo.log_event("ingest", f"storm archive failed: {exc}", "warn", meta={"run_id": run_id})

        # 2. Weather
        weather: dict = {}
        weather_fcst: dict = {}
        try:
            weather = ingest_weather.fetch_open_meteo(zones, at=backfill_ts)
            age = ingest_weather.last_stale_min if not backfill_ts else None
            sources["open_meteo"] = "stale" if age is not None else "ok"
            if age is not None:  # Open-Meteo limited this IP; the last good forecast is still in use
                sources["open_meteo_age_min"] = age
        except Exception as exc:  # noqa: BLE001
            sources["open_meteo"] = "failed"
            repo.log_event("ingest", f"Open-Meteo failed: {exc}", "error", meta={"run_id": run_id})
        if weather and classifier.forecast_model():  # forecast features from a different model (D3)
            try:
                weather_fcst = ingest_weather.fetch_open_meteo(zones, at=backfill_ts, model=classifier.forecast_model(),
                                                               variables=["precipitation"])
                sources["forecast_model"] = "ok"
            except Exception as exc:  # noqa: BLE001 — classifier then sees NaN forecast features
                sources["forecast_model"] = "failed"
                repo.log_event("ingest", f"forecast-model fetch failed: {exc}", "warn", meta={"run_id": run_id})
        met: dict = {}
        sensor_ev: dict = {}
        if replay:
            sources["met_warnings"] = "skipped"  # data.gov.my is live-only
            sources["infobanjir"] = "skipped"
        else:
            try:
                met = ingest_weather.match_warnings(ingest_weather.fetch_met_warnings(now), zones)
                sources["met_warnings"] = "ok"
            except Exception as exc:  # noqa: BLE001
                sources["met_warnings"] = "failed"
                repo.log_event("ingest", f"data.gov.my warning fetch failed: {exc}", "warn", meta={"run_id": run_id})
            try:  # an extra check: a failure never makes the run degraded (architecture.md §3 step 2)
                sensor_ev = _sensor_evidence(zones, now, sources)
            except Exception as exc:  # noqa: BLE001
                sources["infobanjir"] = "failed"
                repo.log_event("ingest", f"InfoBanjir sensors failed: {exc}", "warn", meta={"run_id": run_id})

        # 3. Nowcast
        forecast: list[DbzGrid] = []
        if len(observed) >= 2:
            try:
                t0 = time.monotonic()
                forecast, method = nowcast.nowcast(observed)
                sources |= {"nowcast": "ok", "nowcast_method": method,
                            "nowcast_ms": int((time.monotonic() - t0) * 1000)}
                frame_rows += storage.upload_nowcast(run_id, forecast)
            except Exception as exc:  # noqa: BLE001
                sources["nowcast"] = sources.get("nowcast") or "failed"
                repo.log_event("model", f"nowcast/upload failed: {exc}", "error", meta={"run_id": run_id})
        else:
            sources["nowcast"] = "failed"
        repo.insert_frames(frame_rows)

        # 4–6. Zone stats, classifier, risk
        results = compute_zone_results(zones, observed, forecast, weather, met, sensor_ev, settings, now, weather_fcst)
        prev = {zid: Level(p["level"]) for zid, p in repo.latest_predictions().items()}
        rows = []
        for r in results.values():
            if replay:
                r["explanation"]["replay_of"] = repo.iso(backfill_ts) if backfill_ts else "synthetic"
            rows.append({**r, "run_id": run_id, "ts": repo.iso(now)})
        repo.insert_predictions(rows)
        sources["model"] = classifier.model_version() or "rules_only"

        # 7. Alerts
        try:
            alerts.process_run(run_id, {z["id"]: z for z in zones}, results, prev, settings)
            sources["alerts"] = "ok"
        except Exception as exc:  # noqa: BLE001
            sources["alerts"] = "failed"
            repo.log_event("alert", f"alert manager failed: {exc}", "error", meta={"run_id": run_id})

        # 7b. Sirens (architecture.md §3.3)
        try:
            sirens.process_run(run_id, {z["id"]: z for z in zones}, results, settings)
        except Exception as exc:  # noqa: BLE001
            sources["sirens"] = "failed"
            repo.log_event("siren", f"siren manager failed: {exc}", "error", meta={"run_id": run_id})

        # Housekeeping (D9)
        if not replay:
            try:
                storage.prune_nowcasts()
                ingest_radar.prune_disk_cache(frames[-8:])
            except Exception as exc:  # noqa: BLE001
                repo.log_event("ingest", f"prune failed: {exc}", "warn", meta={"run_id": run_id})

        # 8. Log
        sources["duration_s"] = round(time.monotonic() - started, 1)
        status = _status(sources)
        repo.finish_run(run_id, status, sources)
        repo.log_event("ingest", f"run {status} in {sources['duration_s']} s",
                       "info" if status == "ok" else "warn", meta={"run_id": run_id, **sources})
    except Exception as exc:  # noqa: BLE001
        log.exception("pipeline run failed")
        sources["duration_s"] = round(time.monotonic() - started, 1)
        repo.finish_run(run_id, "failed", sources, str(exc)[:500])
        repo.log_event("ingest", f"run failed: {exc}", "error", meta={"run_id": run_id})
