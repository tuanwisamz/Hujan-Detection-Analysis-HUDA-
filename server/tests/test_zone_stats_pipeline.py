"""Zone stats, nowcast fallback, and the pure pipeline core on the synthetic storm (D2)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from app.models import AppSettings, Level
from app.services import nowcast, palette, synthetic
from app.services.grid import REGION, lonlat_to_tile, region_bounds, tile_to_lonlat
from app.services.pipeline import compute_zone_results
from app.services.zone_stats import zone_mask, zone_stats

NOW = datetime(2026, 10, 18, 6, 40, tzinfo=timezone.utc)
ELMINA = {"id": "elmina", "name": "City of Elmina", "slug": "city-of-elmina", "lat": 3.183, "lon": 101.486,
          "radius_m": 2500, "district": "Petaling", "state": "Selangor"}
PASIR_PUTIH = {"id": "pp", "name": "Taman Pasir Putih", "slug": "taman-pasir-putih", "lat": 1.470,
               "lon": 103.890, "radius_m": 2500, "district": "Johor Bahru", "state": "Johor"}


def test_mosaic_covers_peninsular_malaysia():
    b = region_bounds()
    (south, west), (north, east) = b.latlon
    assert south <= REGION["south"] and north >= REGION["north"]
    assert west <= REGION["west"] and east >= REGION["east"]
    assert b.nx * b.ny <= 9  # within the ~6–9 tile budget
    assert 1.1 < b.km_per_px(3.0) < 1.3


def test_tile_math_round_trip():
    x, y = lonlat_to_tile(101.486, 3.183)
    lon, lat = tile_to_lonlat(x, y)
    assert abs(lon - 101.486) < 1e-9 and abs(lat - 3.183) < 1e-9


def test_circle_mask_size():
    mask = zone_mask(ELMINA, region_bounds())
    # 2.5 km radius at ~1.22 km/px plus a 1-px buffer: roughly 25–45 pixels
    assert 20 <= mask.sum() <= 50


def test_polygon_mask():
    poly = {"type": "Polygon", "coordinates": [[[101.46, 3.16], [101.51, 3.16], [101.51, 3.20],
                                                [101.46, 3.20], [101.46, 3.16]]]}
    mask = zone_mask({**ELMINA, "polygon": poly}, region_bounds(), buffer_px=0)
    assert 10 <= mask.sum() <= 25


def test_zone_stats_eta_and_max():
    b = region_bounds()
    mask = {"z": zone_mask(ELMINA, b)}
    h, w = b.shape
    dry, wet = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    wet[mask["z"]] = 35.0
    s = zone_stats(dry, [dry, dry, wet, dry, dry, dry], mask)["z"]
    assert s == {"rain_rate_max": 35.0, "eta_min": 30, "accum_1h": 5.8,
                 "red_sustained_min": 10, "red_area_max": 1.0, "very_heavy_sustained_min": 0}
    assert zone_stats(wet, [dry] * 6, mask)["z"]["eta_min"] == 0
    assert zone_stats(dry, [dry] * 6, mask)["z"]["eta_min"] is None


def test_zone_stats_sustained_needs_area_and_consecutive_steps():
    b = region_bounds()
    m = zone_mask(ELMINA, b)
    h, w = b.shape
    dry, full, spike = (np.zeros((h, w), np.float32) for _ in range(3))
    full[m] = 35.0
    spike[np.argwhere(m)[0][0], np.argwhere(m)[0][1]] = 273.0  # one noisy pixel
    s = zone_stats(full, [full, dry, full, full, full, dry], {"z": m})["z"]
    assert s["red_sustained_min"] == 30  # longest run is 3 steps, not 4 in total
    s = zone_stats(spike, [spike] * 6, {"z": m})["z"]
    assert s["rain_rate_max"] == 273.0 and s["red_sustained_min"] == 0 and s["very_heavy_sustained_min"] == 0


def test_phase_correlation_finds_shift():
    a = np.zeros((64, 64))
    a[20:28, 10:18] = 1
    b = np.roll(np.roll(a, 3, axis=0), 5, axis=1)
    assert nowcast.estimate_shift(a, b) == (3, 5)


def test_synthetic_storm_moves_east_and_nowcast_follows():
    grids = synthetic.storm_grids(NOW)
    assert len(grids) == 6 and grids[-1].ts == NOW
    cols = [np.nanargmax(np.nan_to_num(g.dbz, nan=-1)) % g.dbz.shape[1] for g in grids]
    assert all(c2 > c1 for c1, c2 in zip(cols, cols[1:]))
    forecast, method = nowcast.nowcast(grids)
    assert len(forecast) == 6 and method in ("pysteps_lk", "global_shift")
    f_cols = [np.nanargmax(np.nan_to_num(g.dbz, nan=-1)) % g.dbz.shape[1] for g in forecast]
    assert f_cols[0] > cols[-1]


def test_nowcast_method_global_shift_skips_pysteps(monkeypatch):
    def no_pysteps(*_):
        raise AssertionError("pySTEPS must not run when NOWCAST_METHOD=global_shift")
    monkeypatch.setattr(nowcast, "_pysteps", no_pysteps)
    monkeypatch.setattr(nowcast, "get_settings", lambda: SimpleNamespace(nowcast_method="global_shift"))
    forecast, method = nowcast.nowcast(synthetic.storm_grids(NOW))
    assert method == "global_shift" and len(forecast) == 6


def test_synthetic_storm_turns_elmina_red_end_to_end():
    observed = synthetic.storm_grids(NOW)
    forecast, _ = nowcast.nowcast(observed)
    results = compute_zone_results([ELMINA, PASIR_PUTIH], observed, forecast, {}, {}, {}, AppSettings(), NOW)
    elmina = results["elmina"]
    assert elmina["level"] == Level.RED.value
    assert elmina["explanation"]["rule"] == "nowcast_sustained>=30"
    assert elmina["explanation"]["inputs"]["red_sustained_min"] >= 30
    assert 10 <= elmina["eta_min"] <= 30
    assert elmina["rain_rate_max"] >= 30
    assert results["pp"]["level"] == Level.GREEN.value


def test_pipeline_core_survives_missing_sources():
    # radar down + no weather: every zone still gets a (GREEN) row, nothing raises (NFR-07)
    results = compute_zone_results([ELMINA], [], [], {}, {}, {}, AppSettings(), NOW)
    assert results["elmina"]["level"] == "GREEN" and results["elmina"]["rain_rate_max"] is None


def test_png_render_is_transparent_where_dry():
    g = synthetic.storm_grids(NOW)[-1]
    from io import BytesIO

    from PIL import Image

    img = np.asarray(Image.open(BytesIO(nowcast.render_png(g))))
    assert img.shape[2] == 4 and (img[..., 3] == 0).mean() > 0.95
    decoded = palette.rgba_to_dbz(img)
    assert np.nanmax(decoded) == np.nanmax(np.round(g.dbz))  # PNG decodes back to the same peak
