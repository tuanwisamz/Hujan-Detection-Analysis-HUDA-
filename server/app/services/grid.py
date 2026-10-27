"""The radar grid: a Web Mercator mosaic of zoom-7 RainViewer tiles.

The grid is kept in Web Mercator (not reprojected). Leaflet's ImageOverlay places it
correctly as long as `bounds` are the stitched tiles' edge coordinates
(architecture.md §3, step 1).
"""

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

ZOOM = 7
TILE = 256
# Peninsular Malaysia (spec FR-01)
REGION = {"south": 1.2, "west": 99.6, "north": 6.8, "east": 104.5}


def lonlat_to_tile(lon: float, lat: float, z: int = ZOOM) -> tuple[float, float]:
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_to_lonlat(x: float, y: float, z: int = ZOOM) -> tuple[float, float]:
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def region_tiles(region: dict = REGION, z: int = ZOOM) -> tuple[range, range]:
    x0, y0 = lonlat_to_tile(region["west"], region["north"], z)
    x1, y1 = lonlat_to_tile(region["east"], region["south"], z)
    return range(int(x0), int(x1) + 1), range(int(y0), int(y1) + 1)


@dataclass
class Bounds:
    """Tile-aligned mosaic extent, in tile coordinates and lat/lon."""
    x0: int
    y0: int
    nx: int
    ny: int
    z: int = ZOOM

    @property
    def shape(self) -> tuple[int, int]:
        return self.ny * TILE, self.nx * TILE

    @property
    def latlon(self) -> list[list[float]]:
        """[[south, west], [north, east]] — the Leaflet bounds for an ImageOverlay."""
        west, north = tile_to_lonlat(self.x0, self.y0, self.z)
        east, south = tile_to_lonlat(self.x0 + self.nx, self.y0 + self.ny, self.z)
        return [[round(south, 5), round(west, 5)], [round(north, 5), round(east, 5)]]

    def to_pixel(self, lat: float, lon: float) -> tuple[float, float]:
        """(row, col) pixel coordinates of a lat/lon inside the mosaic."""
        x, y = lonlat_to_tile(lon, lat, self.z)
        return (y - self.y0) * TILE, (x - self.x0) * TILE

    def km_per_px(self, lat: float) -> float:
        return 40075.016686 * math.cos(math.radians(lat)) / (2 ** self.z * TILE)

    def to_json(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "nx": self.nx, "ny": self.ny, "z": self.z,
                "latlon": self.latlon}


def region_bounds(region: dict = REGION) -> Bounds:
    xs, ys = region_tiles(region)
    return Bounds(xs.start, ys.start, len(xs), len(ys))


@dataclass
class DbzGrid:
    ts: datetime
    dbz: np.ndarray  # float32[H, W], NaN = no echo
    bounds: Bounds
