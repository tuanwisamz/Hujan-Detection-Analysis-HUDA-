"""Classifier features (architecture.md §5.2). SHARED by the backend and the Colab notebook.

Hourly series follow Open-Meteo semantics: the value at hour t is the total over
the hour ending at t. Index t is the latest hour <= now.

Leakage guard (implementation-plan D3): `obs` supplies everything up to and
including t; `fcst` supplies the forecast precipitation for t+1…t+3 from a
DIFFERENT model (features.json "forecast_model", default GFS). From 2017 the
Open-Meteo Archive is the stitched ECMWF IFS forecast, so an ECMWF/best_match
"forecast" is byte-identical to the label. Training: obs = Archive, fcst =
Historical Forecast API with that model. Serving: obs = live best_match
forecast, fcst = live forecast with that model.
"""

import math
from datetime import datetime, timedelta

# Open-Meteo hourly variables the features need.
HOURLY_VARS = [
    "precipitation", "cape", "relative_humidity_2m", "dew_point_2m", "temperature_2m",
    "surface_pressure", "cloud_cover_low", "cloud_cover_mid", "wind_speed_10m", "wind_direction_10m",
]

FEATURE_NAMES = [
    "precip_lag_1h", "precip_lag_3h", "precip_lag_6h", "precip_lag_24h",
    "fcst_precip_1h", "fcst_precip_3h",
    "cape", "rh", "dewpoint_depression", "surface_pressure", "pressure_tendency_3h",
    "cloud_cover_low", "cloud_cover_mid", "wind_speed_10m", "wind_dir_sin", "wind_dir_cos",
    "hour_sin", "hour_cos", "month_sin", "month_cos", "monsoon",
    "lat", "lon",
]

NAN = float("nan")
MYT = timedelta(hours=8)


def monsoon_phase(month: int) -> int:
    """0 = NE monsoon (Nov–Mar), 1 = SW monsoon (May–Sep), 2 = inter-monsoon (Apr, Oct)."""
    if month in (11, 12, 1, 2, 3):
        return 0
    if month in (5, 6, 7, 8, 9):
        return 1
    return 2


def _val(series: dict, var: str, i: int) -> float:
    values = series.get(var) or []
    if 0 <= i < len(values) and values[i] is not None:
        return float(values[i])
    return NAN


def _sum(series: dict, var: str, start: int, end: int) -> float:
    """Sum of series[var][start..end] inclusive; NaN if any value is missing."""
    vals = [_val(series, var, i) for i in range(start, end + 1)]
    return NAN if not vals or any(math.isnan(v) for v in vals) else sum(vals)


def build_features(obs: dict, t: int, lat: float, lon: float, ts_utc: datetime,
                   fcst: dict | None = None, fcst_t: int | None = None) -> dict[str, float]:
    """Feature dict for hour index t of `obs` (see module docstring for obs/fcst)."""
    ft = t if fcst_t is None else fcst_t
    local = ts_utc + MYT
    wind_dir = _val(obs, "wind_direction_10m", t)
    temp, dew = _val(obs, "temperature_2m", t), _val(obs, "dew_point_2m", t)
    pressure, pressure_3h = _val(obs, "surface_pressure", t), _val(obs, "surface_pressure", t - 3)
    return {
        "precip_lag_1h": _sum(obs, "precipitation", t, t),
        "precip_lag_3h": _sum(obs, "precipitation", t - 2, t),
        "precip_lag_6h": _sum(obs, "precipitation", t - 5, t),
        "precip_lag_24h": _sum(obs, "precipitation", t - 23, t),
        "fcst_precip_1h": _sum(fcst, "precipitation", ft + 1, ft + 1) if fcst else NAN,
        "fcst_precip_3h": _sum(fcst, "precipitation", ft + 1, ft + 3) if fcst else NAN,
        "cape": _val(obs, "cape", t),
        "rh": _val(obs, "relative_humidity_2m", t),
        "dewpoint_depression": temp - dew,
        "surface_pressure": pressure,
        "pressure_tendency_3h": pressure - pressure_3h,
        "cloud_cover_low": _val(obs, "cloud_cover_low", t),
        "cloud_cover_mid": _val(obs, "cloud_cover_mid", t),
        "wind_speed_10m": _val(obs, "wind_speed_10m", t),
        "wind_dir_sin": math.sin(math.radians(wind_dir)) if not math.isnan(wind_dir) else NAN,
        "wind_dir_cos": math.cos(math.radians(wind_dir)) if not math.isnan(wind_dir) else NAN,
        "hour_sin": math.sin(2 * math.pi * local.hour / 24),
        "hour_cos": math.cos(2 * math.pi * local.hour / 24),
        "month_sin": math.sin(2 * math.pi * (local.month - 1) / 12),
        "month_cos": math.cos(2 * math.pi * (local.month - 1) / 12),
        "monsoon": float(monsoon_phase(local.month)),
        "lat": lat,
        "lon": lon,
    }


def label(obs: dict, t: int, threshold_mm: float = 30.0) -> int | None:
    """Proxy flood-rain label: >= threshold_mm over the next 3 h (t+1…t+3). None if unknown."""
    total = _sum(obs, "precipitation", t + 1, t + 3)
    return None if math.isnan(total) else int(total >= threshold_mm)


def accum_24h(obs: dict, t: int) -> float | None:
    """Past-24 h rainfall for the wet-ground bump (implementation-plan D8)."""
    v = _sum(obs, "precipitation", t - 23, t)
    return None if math.isnan(v) else round(v, 1)


def current_index(times: list[datetime], now: datetime) -> int:
    """Index of the latest hour <= now."""
    idx = [i for i, ts in enumerate(times) if ts <= now]
    return idx[-1] if idx else 0
