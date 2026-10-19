"""Per-zone rain statistics from the radar grid (architecture.md §3 step 4). Pure functions."""

import numpy as np

from .grid import Bounds

STEP_MIN = 10


def zone_mask(zone: dict, bounds: Bounds, buffer_px: int = 1) -> np.ndarray:
    """Boolean mask of the zone's circle (or GeoJSON polygon) on the grid.

    At ~1.2 km/px a 2.5 km circle covers only ~15 pixels, so a 1-pixel buffer makes
    a cell clipping the edge count.
    """
    h, w = bounds.shape
    rows, cols = np.ogrid[:h, :w]
    polygon = zone.get("polygon")
    if polygon:
        ring = polygon.get("coordinates", [[]])[0] if polygon.get("type") == "Polygon" else []
        if len(ring) >= 3:
            pts = np.array([bounds.to_pixel(lat, lon) for lon, lat in ring])  # GeoJSON is lon,lat
            mask = _point_in_polygon(pts, h, w)
            return _dilate(mask, buffer_px)
    r0, c0 = bounds.to_pixel(zone["lat"], zone["lon"])
    radius_px = (zone.get("radius_m") or 2500) / 1000 / bounds.km_per_px(zone["lat"]) + buffer_px
    return (rows + 0.5 - r0) ** 2 + (cols + 0.5 - c0) ** 2 <= radius_px ** 2


def _point_in_polygon(pts: np.ndarray, h: int, w: int) -> np.ndarray:
    """Even-odd rule on pixel centres, limited to the polygon's bounding box."""
    mask = np.zeros((h, w), dtype=bool)
    r_lo, c_lo = np.floor(pts.min(axis=0)).astype(int)
    r_hi, c_hi = np.ceil(pts.max(axis=0)).astype(int)
    r_lo, c_lo, r_hi, c_hi = max(r_lo, 0), max(c_lo, 0), min(r_hi, h - 1), min(c_hi, w - 1)
    if r_lo > r_hi or c_lo > c_hi:
        return mask
    rr, cc = np.mgrid[r_lo:r_hi + 1, c_lo:c_hi + 1]
    y, x = rr + 0.5, cc + 0.5
    inside = np.zeros_like(y, dtype=bool)
    n = len(pts)
    for i in range(n):
        y1, x1 = pts[i]
        y2, x2 = pts[(i + 1) % n]
        crosses = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1)
        inside ^= crosses
    mask[r_lo:r_hi + 1, c_lo:c_hi + 1] = inside
    return mask


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(px):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def zone_stats(current_rate: np.ndarray | None, forecast_rates: list[np.ndarray],
               masks: dict[str, np.ndarray], heavy_mmh: float = 10.0) -> dict[str, dict]:
    """Rain stats per zone.

    current_rate: latest observed rain rate (mm/h) or None if radar is missing.
    forecast_rates: nowcast rain rates for +10…+60 min.
    rain_rate_max: max over now and the next 60 min. eta_min: minutes until the first
    zone pixel ≥ heavy_mmh (0 = already raining that hard; None = not within 60 min).
    accum_1h: expected rain over the next hour from the zone-mean rate (mm).
    """
    out = {}
    for zone_id, mask in masks.items():
        if not mask.any():
            out[zone_id] = {"rain_rate_max": None, "eta_min": None, "accum_1h": None}
            continue
        steps = ([current_rate] if current_rate is not None else []) + list(forecast_rates)
        if not steps:
            out[zone_id] = {"rain_rate_max": None, "eta_min": None, "accum_1h": None}
            continue
        maxes = [float(s[mask].max()) for s in steps]
        offset = 0 if current_rate is not None else 1
        eta = next(((k + offset) * STEP_MIN for k, m in enumerate(maxes) if m >= heavy_mmh), None)
        accum = sum(float(s[mask].mean()) for s in forecast_rates) * STEP_MIN / 60
        out[zone_id] = {"rain_rate_max": round(max(maxes), 1), "eta_min": eta, "accum_1h": round(accum, 1)}
    return out
