"""Risk engine: spec §6.2 rules, evaluated per zone each run. Pure function.

This is the ONLY place a risk level is decided. The LLM agents never set levels
(spec §6.4 guardrail).
"""

from ..models import LEVEL_ORDER, Level, Thresholds, raise_level


def classify(rain_rate_max: float | None, p_ml: float | None, warning: dict | None,
             accum_24h: float | None, th: Thresholds,
             top_features: list | None = None) -> tuple[Level, dict]:
    """Returns (level, explanation).

    rain_rate_max: nowcast max rain rate (mm/h) over the next 60 min, None if radar failed.
    p_ml: classifier probability, None if the model is unavailable.
    warning: matched MET warning {"severity": "severe"|"active", ...} or None.
    """
    red, amber = [], []
    if rain_rate_max is not None:
        if rain_rate_max >= th.red_rate_mmh:
            red.append(f"nowcast_rate>={th.red_rate_mmh:g}")
        elif rain_rate_max >= th.amber_rate_mmh:
            amber.append(f"nowcast_rate>={th.amber_rate_mmh:g}")
    if p_ml is not None:
        if p_ml >= th.red_p:
            red.append(f"p_ml>={th.red_p:.2f}")
        elif p_ml >= th.amber_p:
            amber.append(f"p_ml>={th.amber_p:.2f}")
    if warning:
        (red if warning.get("severity") == "severe" else amber).append(
            "met_severe_warning" if warning.get("severity") == "severe" else "met_warning")

    level = Level.RED if red else Level.AMBER if amber else Level.GREEN
    fired = red + amber
    bumped = accum_24h is not None and accum_24h >= th.wet_ground_mm24h and level != Level.RED
    if bumped:
        level = raise_level(level)
        if not fired:
            fired = [f"accum_24h>={th.wet_ground_mm24h:g}"]

    explanation = {
        "rule": fired[0] if fired else None,
        "rules_fired": fired,
        "wet_ground_bump": bumped,
        "top_features": top_features or [],
        "inputs": {"rain_rate_max": rain_rate_max, "p_ml": p_ml, "accum_24h": accum_24h,
                   "warning": warning.get("title") if warning else None},
    }
    return level, explanation


def is_raise(prev: Level | None, new: Level) -> bool:
    return new != Level.GREEN and LEVEL_ORDER[new] > LEVEL_ORDER[prev or Level.GREEN]
