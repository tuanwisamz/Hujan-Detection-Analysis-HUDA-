"""Risk engine: spec §6.2 rules, evaluated per zone each run. Pure function.

This is the ONLY place a risk level is decided. The LLM agents never set levels
(spec §6.4 guardrail).
"""

from ..models import LEVEL_ORDER, Level, Thresholds

RIVER_ORDER = {"NORMAL": 0, "ALERT": 1, "WARNING": 2, "DANGER": 3}


def sensor_check(sensor: dict | None, th: Thresholds) -> str:
    """confirmed · not_yet · no_sensor (implementation-plan-v2 D18).

    Any fresh gauge counts here, including ones placed by their station-ID grid cell.
    """
    if not sensor or not sensor.get("fresh_count"):
        return "no_sensor"
    rain = sensor.get("rain_1h")
    if (rain is not None and rain >= th.sensor_confirm_1h_mm) or RIVER_ORDER.get(sensor.get("river") or "", 0) >= 1:
        return "confirmed"
    return "not_yet"


def classify(stats: dict | None, p_ml: float | None, warning: dict | None,
             accum_24h: float | None, th: Thresholds,
             top_features: list | None = None, sensor: dict | None = None) -> tuple[Level, dict]:
    """Returns (level, explanation).

    stats: zone_stats() output for the zone (None or empty values if radar failed).
    p_ml: classifier probability, None if the model is unavailable.
    warning: matched MET warning {"severity": "severe"|"active", ...} or None.
    sensor: sensors.zone_evidence() output for the zone, or None.
    """
    s = stats or {}
    red, amber = [], []

    # Radar nowcast (D16): duration + area, accumulation, or a very heavy core
    rate = s.get("rain_rate_max")
    if (s.get("red_sustained_min") or 0) >= th.red_duration_min:
        red.append(f"nowcast_sustained>={th.red_rate_mmh:g}")
    if (s.get("accum_1h") or 0) >= th.red_accum_1h_mm:
        red.append(f"nowcast_accum_1h>={th.red_accum_1h_mm:g}")
    if (s.get("very_heavy_sustained_min") or 0) >= th.very_heavy_duration_min:
        red.append(f"nowcast_rate>={th.very_heavy_mmh:g}")
    if not red and rate is not None and rate >= th.amber_rate_mmh:
        amber.append(f"nowcast_rate>={th.amber_rate_mmh:g}")  # includes heavy cells too brief or small for RED

    # MET warnings
    if warning:
        if warning.get("severity") == "severe":
            red.append("met_severe_warning")
        else:
            amber.append("met_warning")

    # Sensor alarms (D19): river stations, and gauges with a verified location
    if sensor:
        river = RIVER_ORDER.get(sensor.get("river") or "", 0)
        if river >= RIVER_ORDER["DANGER"]:
            red.append("river_danger")
        elif river >= RIVER_ORDER["WARNING"]:
            amber.append("river_warning")
        g1, g3 = sensor.get("rain_1h_verified"), sensor.get("rain_3h_verified")
        if g1 is not None and g1 >= th.gauge_red_1h_mm:
            red.append(f"gauge_1h>={th.gauge_red_1h_mm:g}")
        if g3 is not None and g3 >= th.gauge_red_3h_mm:
            red.append(f"gauge_3h>={th.gauge_red_3h_mm:g}")
        if g1 is not None and th.gauge_amber_1h_mm <= g1 < th.gauge_red_1h_mm:
            amber.append(f"gauge_1h>={th.gauge_amber_1h_mm:g}")

    # Classifier: an ML-only RED needs a sensor to agree (D18)
    check = sensor_check(sensor, th)
    if p_ml is not None:
        if p_ml >= th.red_p:
            if check == "confirmed":
                red.append(f"p_ml>={th.red_p:.2f}")
            else:
                amber.append("p_ml_unconfirmed")
        elif p_ml >= th.amber_p:
            amber.append(f"p_ml>={th.amber_p:.2f}")

    level = Level.RED if red else Level.AMBER if amber else Level.GREEN
    fired = red + amber
    # Wet-ground bump (D17): GREEN -> AMBER only, never AMBER -> RED
    bumped = accum_24h is not None and accum_24h >= th.wet_ground_mm24h and level == Level.GREEN
    if bumped:
        level = Level.AMBER
        fired = [f"accum_24h>={th.wet_ground_mm24h:g}"]

    explanation = {
        "rule": fired[0] if fired else None,
        "rules_fired": fired,
        "red_rules": red,
        "wet_ground_bump": bumped,
        "sensor_check": check,
        "sensors": (sensor or {}).get("stations", []),
        "top_features": top_features or [],
        "inputs": {"rain_rate_max": rate, "accum_1h": s.get("accum_1h"),
                   "red_sustained_min": s.get("red_sustained_min"), "red_area_max": s.get("red_area_max"),
                   "very_heavy_sustained_min": s.get("very_heavy_sustained_min"),
                   "p_ml": p_ml, "accum_24h": accum_24h,
                   "warning": warning.get("title") if warning else None},
    }
    return level, explanation


def is_raise(prev: Level | None, new: Level) -> bool:
    return new != Level.GREEN and LEVEL_ORDER[new] > LEVEL_ORDER[prev or Level.GREEN]
