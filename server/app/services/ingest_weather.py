"""Open-Meteo forecast + data.gov.my MET/flood warnings (architecture.md §3 step 2)."""

import logging
import math
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..config import check_fault
from .features import HOURLY_VARS

log = logging.getLogger("huda")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MET_WARNING_URL = "https://api.data.gov.my/weather/warning/"
FLOOD_WARNING_URL = "https://api.data.gov.my/flood-warning/"

RAIN_WORDS = ("rain", "thunderstorm", "hujan", "ribut petir")
MARINE_WORDS = ("sea", "laut", "waters", "perairan")
FLOOD_LEVELS = ("WARNING", "DANGER")
FLOOD_RADIUS_KM = 15.0
FLOOD_MAX_AGE = timedelta(hours=6)
SEVERE_WORDS = ("danger", "severe", "bahaya", "teruk")


def _parse_hourly(loc: dict, variables: list[str]) -> dict:
    hourly = loc.get("hourly", {})
    series = {v: hourly.get(v, []) for v in variables}
    series["time"] = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly.get("time", [])]
    return series


def fetch_open_meteo(zones: list[dict], at: datetime | None = None, model: str | None = None,
                     variables: list[str] | None = None) -> dict[str, dict]:
    """One multi-coordinate request for all zones -> {zone_id: hourly series (UTC)}.

    Live: forecast API with past_days=1 (gives the 24 h accumulation, D8).
    Backfill (`at` set): Historical Forecast API around that time, so features use
    what the model forecast then, not what happened.
    """
    check_fault("open_meteo")
    if not zones:
        return {}
    params = {
        "latitude": ",".join(f"{z['lat']:.4f}" for z in zones),
        "longitude": ",".join(f"{z['lon']:.4f}" for z in zones),
        "hourly": ",".join(variables or HOURLY_VARS),
        "timezone": "GMT",
    }
    if model:
        params["models"] = model
    if at is None:
        url = FORECAST_URL
        params |= {"past_days": 1, "forecast_days": 2}
    else:
        url = HISTORICAL_FORECAST_URL
        params |= {"start_date": (at - timedelta(days=1)).date().isoformat(),
                   "end_date": (at + timedelta(days=1)).date().isoformat()}
    r = httpx.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    locations = data if isinstance(data, list) else [data]
    return {z["id"]: _parse_hourly(loc, variables or HOURLY_VARS) for z, loc in zip(zones, locations)}


def fetch_met_warnings(now: datetime | None = None) -> list[dict]:
    """Active MET Malaysia warnings (free text; no location id — implementation-plan D7)."""
    check_fault("met_warnings")
    now = now or datetime.now(timezone.utc)
    r = httpx.get(MET_WARNING_URL, params={"limit": 50}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    active = []
    for w in r.json():
        valid_from = _ts(w.get("valid_from"))
        valid_to = _ts(w.get("valid_to"))
        if (valid_from is None or valid_from <= now) and (valid_to is None or now <= valid_to):
            active.append(w)
    return active


def fetch_flood_warnings() -> list[dict]:
    check_fault("flood")
    r = httpx.get(FLOOD_WARNING_URL, params={"limit": 200}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def _ts(value) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # data.gov.my timestamps without an offset are Malaysia time.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=8)))


def _text(w: dict) -> str:
    issue = w.get("warning_issue") or {}
    parts = [issue.get("title_en"), issue.get("title_bm"), w.get("heading_en"), w.get("heading_bm"),
             w.get("text_en"), w.get("text_bm")]
    return " ".join(p for p in parts if p)


def _mentions(text: str, name: str) -> bool:
    return bool(name) and re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) is not None


def _mentions_whole_state(text: str, state: str) -> bool:
    """State named without a district list right after it, e.g. "Selangor." not "Selangor (Klang)"."""
    return bool(state) and re.search(rf"\b{re.escape(state)}\b(?!\s*[(:])", text, re.IGNORECASE) is not None


def match_warnings(warnings: list[dict], zones: list[dict]) -> dict[str, dict]:
    """{zone_id: {"severity": "severe"|"active", "title": ...}} for rain/thunderstorm warnings.

    A zone matches when the warning text names its district or one of its
    match_terms, or names its state as a whole (no district list after it).
    """
    matched: dict[str, dict] = {}
    for w in warnings:
        text = _text(w)
        issue = w.get("warning_issue") or {}
        # Classify by title only: marine/wind bulletins mention rain words deep in their body text.
        heading = " ".join(p for p in (issue.get("title_en"), issue.get("title_bm"),
                                       w.get("heading_en"), w.get("heading_bm")) if p).lower()
        if not any(word in heading for word in RAIN_WORDS) or any(word in heading for word in MARINE_WORDS):
            continue
        title = issue.get("title_en") or w.get("heading_en") or "MET warning"
        severity = "severe" if any(word in title.lower() for word in SEVERE_WORDS) else "active"
        for z in zones:
            names = [z.get("district")] + list(z.get("match_terms") or [])
            if any(_mentions(text, n) for n in names if n) or _mentions_whole_state(text, z.get("state", "")):
                current = matched.get(z["id"])
                if current is None or (severity == "severe" and current["severity"] != "severe"):
                    label = f"{title} – {z.get('district') or z.get('state')}"
                    matched[z["id"]] = {"severity": severity, "title": label}
    return matched


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def match_flood(flood: list[dict], zones: list[dict], now: datetime | None = None) -> dict[str, str]:
    """River stations at WARNING/DANGER within 15 km of a zone, updated in the last 6 h.

    Informational only (shown in the zone panel); doesn't change levels. Some
    stations report stale readings for years, hence the freshness check.
    """
    now = now or datetime.now(timezone.utc)
    out: dict[str, str] = {}
    for f in flood:
        indicator = str(f.get("water_level_indicator") or "").upper()
        updated = _ts(f.get("water_level_update_datetime"))
        if indicator not in FLOOD_LEVELS or updated is None or now - updated > FLOOD_MAX_AGE:
            continue
        lat, lon = f.get("latitude"), f.get("longitude")
        if lat is None or lon is None:
            continue
        for z in zones:
            if _km(z["lat"], z["lon"], float(lat), float(lon)) <= FLOOD_RADIUS_KM:
                out.setdefault(z["id"], f"River {indicator.lower()} – {f.get('station_name', 'station')}")
    return out
