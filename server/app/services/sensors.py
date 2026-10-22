"""Sensor evidence per zone (implementation-plan-v2 D18–D21, architecture §3.2). Pure functions.

Turns JPS station readings into what risk.classify needs: the heaviest recent gauge
rain near the zone, the worst river level, and the nearest stations for the zone panel.
"""

import math
from datetime import datetime, timedelta

GAUGE_RADIUS_KM = 10.0
RIVER_RADIUS_KM = 15.0
GAUGE_MAX_AGE = timedelta(minutes=45)
RIVER_MAX_AGE = timedelta(hours=2)
HOUR_TOLERANCE = timedelta(minutes=10)  # how far an "hour ago" reading may be from exactly 1 h
RIVER_ORDER = ("NORMAL", "ALERT", "WARNING", "DANGER")


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def stations_near(zone: dict, stations: list[dict]) -> list[tuple[dict, float]]:
    """Active stations inside the gauge/river radius of the zone centre, nearest first."""
    out = []
    for s in stations:
        if not s.get("active", True) or s.get("lat") is None or s.get("lon") is None:
            continue
        d = km(zone["lat"], zone["lon"], s["lat"], s["lon"])
        if d <= (GAUGE_RADIUS_KM if s["kind"] == "rain" else RIVER_RADIUS_KM):
            out.append((s, d))
    return sorted(out, key=lambda x: x[1])


def rain_3h(history: list[dict]) -> float | None:
    """Sum of the 1-h totals at t, t − 1 h and t − 2 h, or None if any is missing.

    history: one station's readings, any order, each with ts and rain_1h_mm.
    """
    rows = sorted((r for r in history if r.get("ts") and r.get("rain_1h_mm") is not None), key=lambda r: r["ts"])
    if not rows:
        return None
    latest = rows[-1]
    total = latest["rain_1h_mm"]
    for h in (1, 2):
        target = latest["ts"] - timedelta(hours=h)
        best = min(rows, key=lambda r: abs(r["ts"] - target))
        if abs(best["ts"] - target) > HOUR_TOLERANCE:
            return None
        total += best["rain_1h_mm"]
    return round(total, 1)


def zone_evidence(zones: list[dict], stations: list[dict], readings: dict[str, list[dict]],
                  now: datetime) -> dict[str, dict]:
    """{zone_id: evidence} for zones with at least one station nearby.

    readings: {station_id: [reading, …]} covering at least the last ~2 h 15 min.
    Evidence: rain_1h (any fresh gauge), rain_1h_verified / rain_3h_verified (fresh gauges
    with an exact location only; D21), river (worst fresh indicator), fresh_count, and
    stations (nearest 3 fresh ones, for the explanation and the zone panel).
    """
    out = {}
    for z in zones:
        ev = {"rain_1h": None, "rain_1h_verified": None, "rain_3h_verified": None, "river": None,
              "fresh_count": 0, "stations": []}
        for s, dist in stations_near(z, stations):
            hist = readings.get(s["id"]) or []
            latest = max(hist, key=lambda r: r["ts"], default=None)
            if latest is None:
                continue
            age = now - latest["ts"]
            if age > (GAUGE_MAX_AGE if s["kind"] == "rain" else RIVER_MAX_AGE) or age < -timedelta(minutes=30):
                continue
            verified = s.get("location_quality") == "verified"
            item = {"id": s["id"], "station": s.get("name"), "kind": s["kind"], "distance_km": round(dist, 1),
                    "age_min": max(0, int(age.total_seconds() // 60)), "location_quality": s.get("location_quality")}
            if s["kind"] == "rain":
                v = latest.get("rain_1h_mm")
                if v is None:
                    continue
                item["value"] = v
                ev["rain_1h"] = max(ev["rain_1h"] or 0, v)
                if verified:
                    ev["rain_1h_verified"] = max(ev["rain_1h_verified"] or 0, v)
                    r3 = rain_3h(hist)
                    if r3 is not None:
                        ev["rain_3h_verified"] = max(ev["rain_3h_verified"] or 0, r3)
            else:
                ind = latest.get("indicator")
                if ind not in RIVER_ORDER:
                    continue
                item |= {"value": latest.get("water_level_m"), "indicator": ind}
                if ev["river"] is None or RIVER_ORDER.index(ind) > RIVER_ORDER.index(ev["river"]):
                    ev["river"] = ind
            ev["fresh_count"] += 1
            if len(ev["stations"]) < 3:
                ev["stations"].append(item)
        if ev["fresh_count"]:
            out[z["id"]] = ev
    return out


def official_text(ev: dict | None) -> str | None:
    """'River warning – Sg. Buloh' for the zone panel's official-warnings line."""
    if not ev or ev.get("river") not in ("WARNING", "DANGER"):
        return None
    station = next((s["station"] for s in ev["stations"] if s.get("indicator") == ev["river"]), None)
    return f"River {ev['river'].lower()} – {station or 'JPS station'}"
