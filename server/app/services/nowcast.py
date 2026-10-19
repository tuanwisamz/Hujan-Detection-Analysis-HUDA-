"""0–60 min radar nowcast (spec FR-10, architecture.md §5.1).

Primary: pySTEPS Lucas–Kanade motion field + semi-Lagrangian extrapolation.
Fallback (pySTEPS not installed, e.g. local Windows dev): one global motion vector
from FFT phase correlation, then whole-field advection. Cruder, but keeps the
pipeline and tests running anywhere. The method used is recorded per run.
"""

import logging
from datetime import timedelta

import numpy as np

from . import palette
from .grid import DbzGrid

log = logging.getLogger("huda")

STEP_MIN = 10


def nowcast(grids: list[DbzGrid], n_steps: int = 6) -> tuple[list[DbzGrid], str]:
    """Last observed grids (oldest first) -> n_steps forecast grids (dBZ) and the method name."""
    if len(grids) < 2:
        raise ValueError("need at least 2 radar frames to nowcast")
    rates = np.stack([palette.dbz_to_rate(g.dbz) for g in grids])
    try:
        forecast, method = _pysteps(rates, n_steps), "pysteps_lk"
    except ImportError:
        forecast, method = _global_shift(rates, n_steps), "global_shift"
    last = grids[-1]
    out = [DbzGrid(last.ts + timedelta(minutes=STEP_MIN * (k + 1)), palette.rate_to_dbz(forecast[k]), last.bounds)
           for k in range(n_steps)]
    return out, method


def _pysteps(rates: np.ndarray, n_steps: int) -> np.ndarray:
    from pysteps import motion, nowcasts
    from pysteps.utils import transformation

    r_db, _ = transformation.dB_transform(rates.copy(), threshold=0.1, zerovalue=-15.0)
    r_db[~np.isfinite(r_db)] = -15.0
    velocity = motion.get_method("lucaskanade")(r_db)
    forecast = nowcasts.get_method("extrapolation")(rates[-1], velocity, n_steps)
    return np.nan_to_num(np.asarray(forecast), nan=0.0).clip(min=0)


def estimate_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """Integer (dy, dx) that moves field a onto field b, via FFT phase correlation."""
    fa, fb = np.fft.fft2(a), np.fft.fft2(b)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.ifft2(cross).real
    dy, dx = np.unravel_index(np.argmax(corr), corr.shape)
    h, w = a.shape
    return (dy - h if dy > h // 2 else dy), (dx - w if dx > w // 2 else dx)


def _shift(field: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(field)
    h, w = field.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = field[ys, xs]
    return out


def _global_shift(rates: np.ndarray, n_steps: int) -> np.ndarray:
    # Average the per-step motion over the available frame pairs for stability.
    shifts = [estimate_shift(np.log1p(rates[i]), np.log1p(rates[i + 1])) for i in range(len(rates) - 1)]
    dy = float(np.median([s[0] for s in shifts]))
    dx = float(np.median([s[1] for s in shifts]))
    return np.stack([_shift(rates[-1], round(dy * (k + 1)), round(dx * (k + 1))) for k in range(n_steps)])


def render_png(grid: DbzGrid) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(palette.dbz_to_rgba(grid.dbz), "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
