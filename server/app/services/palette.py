"""RainViewer "Universal Blue" colours <-> dBZ (architecture.md §3 step 1).

The LUT is RainViewer's published colour table (data/universal_blue.csv). Decoding
uses exact matches first, then the nearest table colour within a tolerance, so
PNG quantisation doesn't drop pixels. The same LUT renders the nowcast PNGs, so
forecast frames look identical to the observed layer.
"""

from functools import lru_cache
from pathlib import Path

import numpy as np

LUT_PATH = Path(__file__).parent / "data" / "universal_blue.csv"
MAX_COLOUR_DISTANCE = 24.0  # RGBA euclidean distance; beyond this a pixel is "no echo"
MIN_DBZ, MAX_DBZ = -32, 95


@lru_cache
def _table() -> tuple[np.ndarray, np.ndarray]:
    """(dbz[int16], rgba[uint8, 4]) for every visible table row, lowest dBZ first per colour."""
    dbz, rgba, seen = [], [], set()
    for line in LUT_PATH.read_text().splitlines():
        if not line or line.startswith("#") or line.startswith("dbz"):
            continue
        value, hexcode = line.split(",")
        h = hexcode.strip().lstrip("#")
        colour = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
        if colour[3] == 0 or colour in seen:  # transparent or duplicate (e.g. ≥65 dBZ all white)
            continue
        seen.add(colour)
        dbz.append(int(value))
        rgba.append(colour)
    return np.array(dbz, dtype=np.int16), np.array(rgba, dtype=np.uint8)


@lru_cache
def _render_lut() -> np.ndarray:
    """rgba for every integer dBZ in [MIN_DBZ, MAX_DBZ] (index = dbz - MIN_DBZ)."""
    dbz, rgba = _table()
    out = np.zeros((MAX_DBZ - MIN_DBZ + 1, 4), dtype=np.uint8)
    for d, c in zip(dbz, rgba):
        out[d - MIN_DBZ] = c
    # Fill gaps (dBZ values that share a colour) with the previous visible colour.
    last = np.zeros(4, dtype=np.uint8)
    for i in range(len(out)):
        if out[i, 3]:
            last = out[i]
        elif i + MIN_DBZ >= int(dbz.min()):
            out[i] = last
    return out


def rgba_to_dbz(rgba: np.ndarray) -> np.ndarray:
    """uint8[H, W, 4] -> float32[H, W] dBZ; NaN where there is no echo."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an RGBA image array")
    table_dbz, table_rgba = _table()
    flat = rgba.reshape(-1, 4)
    out = np.full(flat.shape[0], np.nan, dtype=np.float32)

    # Work on unique colours only (a radar tile has at most a few hundred).
    colours, inverse = np.unique(flat, axis=0, return_inverse=True)
    inverse = inverse.reshape(-1)
    values = np.full(len(colours), np.nan, dtype=np.float32)
    visible = colours[:, 3] > 0
    if visible.any():
        diff = colours[visible, None, :].astype(np.float32) - table_rgba[None, :, :].astype(np.float32)
        dist = np.sqrt((diff ** 2).sum(axis=2))
        best = dist.argmin(axis=1)
        ok = dist[np.arange(len(best)), best] <= MAX_COLOUR_DISTANCE
        v = np.where(ok, table_dbz[best].astype(np.float32), np.nan)
        values[visible] = v
    out[:] = values[inverse]
    return out.reshape(rgba.shape[:2])


def dbz_to_rgba(dbz: np.ndarray, min_dbz: float = 15.0) -> np.ndarray:
    """float[H, W] dBZ -> uint8[H, W, 4]. Below min_dbz (and NaN) is transparent."""
    lut = _render_lut()
    idx = np.clip(np.nan_to_num(np.round(dbz), nan=MIN_DBZ), MIN_DBZ, MAX_DBZ).astype(np.int16) - MIN_DBZ
    out = lut[idx]
    out[~(np.nan_to_num(dbz, nan=-999) >= min_dbz)] = 0
    return out


# ---- Marshall–Palmer, Z = 200 R^1.6 (spec FR-10) ----

def dbz_to_rate(dbz: np.ndarray, min_dbz: float = 15.0) -> np.ndarray:
    """dBZ -> rain rate mm/h. Below min_dbz (and NaN) -> 0 (architecture.md §5.1)."""
    d = np.nan_to_num(np.asarray(dbz, dtype=np.float32), nan=-999.0)
    rate = (10 ** (np.clip(d, -32, 95) / 10) / 200) ** (1 / 1.6)
    return np.where(d >= min_dbz, rate, 0.0).astype(np.float32)


def rate_to_dbz(rate: np.ndarray) -> np.ndarray:
    r = np.asarray(rate, dtype=np.float32)
    with np.errstate(divide="ignore"):
        d = 10 * np.log10(200 * np.power(np.maximum(r, 1e-6), 1.6))
    return np.where(r > 0, d, np.nan).astype(np.float32)
