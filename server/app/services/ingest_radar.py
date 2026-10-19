"""RainViewer frames -> decoded dBZ mosaics (architecture.md §3 step 1).

RainViewer frames never change once published, so decoded grids are cached by
frame path (memory + disk). Each 10-min run then downloads only the newest frame
(~9 tiles) instead of the whole history.
"""

import io
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import numpy as np
from PIL import Image

from ..config import check_fault, get_settings
from . import palette
from .grid import TILE, ZOOM, Bounds, DbzGrid, region_bounds

log = logging.getLogger("huda")

MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
COLOR_SCHEME = 2  # Universal Blue

_memory: "OrderedDict[str, DbzGrid]" = OrderedDict()
_MEMORY_MAX = 24
_frame_list: tuple[float, list] = (0.0, [])


@dataclass
class Frame:
    ts: datetime
    host: str
    path: str

    def tile_url(self, options: str, z="{z}", x="{x}", y="{y}") -> str:
        return f"{self.host}{self.path}/{TILE}/{z}/{x}/{y}/{COLOR_SCHEME}/{options}.png"


def list_frames(max_age_s: int = 60) -> list[Frame]:
    """Past radar frames (~2 h, 10-min steps), oldest first. Cached for max_age_s."""
    global _frame_list
    check_fault("radar")
    fetched_at, frames = _frame_list
    if frames and time.monotonic() - fetched_at < max_age_s:
        return frames
    r = httpx.get(MAPS_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    frames = [Frame(datetime.fromtimestamp(f["time"], tz=timezone.utc), data["host"], f["path"])
              for f in data.get("radar", {}).get("past", [])]
    _frame_list = (time.monotonic(), frames)
    return frames


def _disk_path(frame: Frame):
    return get_settings().radar_cache_dir / (frame.path.strip("/").replace("/", "_") + ".npz")


def load_grid(frame: Frame, client: httpx.Client | None = None) -> DbzGrid:
    """Download, stitch and decode the zoom-7 tiles covering Peninsular Malaysia."""
    if frame.path in _memory:
        _memory.move_to_end(frame.path)
        return _memory[frame.path]
    bounds = region_bounds()
    disk = _disk_path(frame)
    if disk.exists():
        dbz = np.load(disk)["dbz"]
    else:
        dbz = _fetch_mosaic(frame, bounds, client)
        disk.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(disk, dbz=dbz)
    grid = DbzGrid(frame.ts, dbz, bounds)
    _memory[frame.path] = grid
    while len(_memory) > _MEMORY_MAX:
        _memory.popitem(last=False)
    return grid


def _fetch_mosaic(frame: Frame, bounds: Bounds, client: httpx.Client | None) -> np.ndarray:
    options = get_settings().rainviewer_decode_options
    h, w = bounds.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        for j in range(bounds.ny):
            for i in range(bounds.nx):
                url = frame.tile_url(options, z=ZOOM, x=bounds.x0 + i, y=bounds.y0 + j)
                r = client.get(url)
                r.raise_for_status()
                tile = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))
                rgba[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE] = tile
    finally:
        if own:
            client.close()
    return palette.rgba_to_dbz(rgba)


def load_recent_grids(frames: list[Frame], n: int = 6) -> list[DbzGrid]:
    with httpx.Client(timeout=15) as client:
        return [load_grid(f, client) for f in frames[-n:]]


def prune_disk_cache(keep: list[Frame]) -> None:
    keep_paths = {_disk_path(f) for f in keep}
    cache_dir = get_settings().radar_cache_dir
    if cache_dir.exists():
        for p in cache_dir.glob("*.npz"):
            if p not in keep_paths:
                p.unlink(missing_ok=True)
