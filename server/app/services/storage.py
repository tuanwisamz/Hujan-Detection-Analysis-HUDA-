"""Supabase Storage: nowcast PNGs (public), storm archive (private), pruning (D2, D9)."""

import io
import logging
from datetime import datetime, timedelta

import numpy as np

from .. import repo
from ..db import public_storage_url, sb
from .grid import Bounds, DbzGrid
from .nowcast import render_png

log = logging.getLogger("huda")

NOWCAST_BUCKET = "radar"
ARCHIVE_BUCKET = "radar-archive"
ARCHIVE_MIN_DBZ = 40.0


def upload_nowcast(run_id: str, grids: list[DbzGrid]) -> list[dict]:
    """Upload +10…+60 min PNGs; return radar_frames rows."""
    rows = []
    for step, g in enumerate(grids, start=1):
        path = f"nowcast/{run_id}/{step}.png"
        sb().storage.from_(NOWCAST_BUCKET).upload(
            path, render_png(g), {"content-type": "image/png", "upsert": "true"})
        rows.append({"run_id": run_id, "ts": repo.iso(g.ts), "kind": "nowcast",
                     "image_path": public_storage_url(NOWCAST_BUCKET, path),
                     "bounds": g.bounds.latlon})
    return rows


def should_archive(grids: list[DbzGrid]) -> bool:
    latest = grids[-1].dbz
    return bool(np.nanmax(latest) >= ARCHIVE_MIN_DBZ) if np.isfinite(latest).any() else False


def archive_storm(grids: list[DbzGrid]) -> str:
    """Storm recorder (D2): save the observed grids so backfill can replay them later."""
    buf = io.BytesIO()
    np.savez_compressed(buf, dbz=np.stack([g.dbz for g in grids]).astype(np.float16),
                        ts=np.array([g.ts.timestamp() for g in grids]),
                        bounds=np.array([grids[0].bounds.x0, grids[0].bounds.y0,
                                         grids[0].bounds.nx, grids[0].bounds.ny, grids[0].bounds.z]))
    name = grids[-1].ts.strftime("%Y%m%dT%H%MZ") + ".npz"
    sb().storage.from_(ARCHIVE_BUCKET).upload(
        name, buf.getvalue(), {"content-type": "application/octet-stream", "upsert": "true"})
    return name


def load_archived(at: datetime, tolerance_min: int = 30) -> list[DbzGrid] | None:
    """Recorded storm grids closest to `at` (within tolerance), or None."""
    files = sb().storage.from_(ARCHIVE_BUCKET).list("", {"limit": 1000})
    best, best_delta = None, timedelta(minutes=tolerance_min)
    for f in files:
        try:
            ts = datetime.strptime(f["name"], "%Y%m%dT%H%MZ.npz").replace(tzinfo=at.tzinfo)
        except ValueError:
            continue
        if abs(ts - at) <= best_delta:
            best, best_delta = f["name"], abs(ts - at)
    if not best:
        return None
    data = np.load(io.BytesIO(sb().storage.from_(ARCHIVE_BUCKET).download(best)))
    x0, y0, nx, ny, z = (int(v) for v in data["bounds"])
    bounds = Bounds(x0, y0, nx, ny, z)
    return [DbzGrid(datetime.fromtimestamp(float(t), tz=at.tzinfo), d.astype(np.float32), bounds)
            for t, d in zip(data["ts"], data["dbz"])]


def prune_nowcasts(older_than: timedelta = timedelta(hours=24)) -> int:
    """Delete nowcast folders for live runs older than 24 h (D9). Backfill runs are kept."""
    bucket = sb().storage.from_(NOWCAST_BUCKET)
    folders = [f["name"] for f in bucket.list("nowcast", {"limit": 1000})]
    if not folders:
        return 0
    cutoff = repo.now() - older_than
    removed = 0
    for run in repo.runs_by_ids(folders):
        if run.get("backfill_ts") or repo.parse_ts(run["started_at"]) > cutoff:
            continue
        files = bucket.list(f"nowcast/{run['id']}")
        if files:
            bucket.remove([f"nowcast/{run['id']}/{f['name']}" for f in files])
            removed += 1
    return removed
