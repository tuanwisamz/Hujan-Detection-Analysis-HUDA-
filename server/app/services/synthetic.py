"""Synthetic storm fixture: the guaranteed demo path (implementation-plan D2).

A convective cell (peak 52 dBZ ≈ 65 mm/h) moving east at ~30 km/h. In the last
observed frame it is 15 km west of City of Elmina, so the nowcast brings heavy
rain over the township within 10–20 min and the zone turns RED.
"""

import math
from datetime import datetime, timedelta

import numpy as np

from .grid import DbzGrid, region_bounds

TARGET = {"lat": 3.183, "lon": 101.486}  # City of Elmina (spec §5)
PEAK_DBZ = 52.0
SIGMA_KM = 2.5
SPEED_KMH = 30.0
DISTANCE_KM = 15.0


def storm_grids(end_ts: datetime, n: int = 6, target: dict = TARGET) -> list[DbzGrid]:
    bounds = region_bounds()
    h, w = bounds.shape
    km_px = bounds.km_per_px(target["lat"])
    r0, c0 = bounds.to_pixel(target["lat"], target["lon"])
    step_px = SPEED_KMH / 6 / km_px  # distance per 10 min
    sigma_px = SIGMA_KM / km_px
    rows, cols = np.ogrid[:h, :w]
    grids = []
    for k in range(n):
        ts = end_ts - timedelta(minutes=10 * (n - 1 - k))
        centre_c = c0 - DISTANCE_KM / km_px - step_px * (n - 1 - k)
        d2 = (rows - r0) ** 2 + (cols - centre_c) ** 2
        z = 10 ** (PEAK_DBZ / 10) * np.exp(-d2 / (2 * sigma_px ** 2))
        with np.errstate(divide="ignore"):
            dbz = (10 * np.log10(z)).astype(np.float32)
        dbz[dbz < 15] = np.nan
        grids.append(DbzGrid(ts, dbz, bounds))
    return grids


def floor_10min(ts: datetime) -> datetime:
    return ts.replace(minute=math.floor(ts.minute / 10) * 10, second=0, microsecond=0)
