"""Open-Meteo forecast + data.gov.my MET warnings (architecture.md §3 step 2)."""

import logging
import re
import time
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
SEVERE_WORDS = ("danger", "severe", "bahaya", "teruk")

# Live Open-Meteo results are reused across 10-min runs: the model updates hourly, and
# shared egress IPs (Render free) hit its per-IP limits (429). Backfill is never cached.
OPEN_METEO_TTL = timedelta(minutes=30)
OPEN_METEO_STALE_MAX = timedelta(hours=3)   # on failure, serve the last good result up to this old
# The daily limit only resets at 00:00 UTC. The last result still covers the next 48 h
# (forecast_days=2), so it stays usable for a day; runs record it as "stale" with its age.
OPEN_METEO_DAILY_STALE_MAX = timedelta(hours=24)
OPEN_METEO_RETRY_S = 10.0
_open_meteo_cache: dict[tuple, tuple[datetime, dict]] = {}
last_stale_min: int | None = None  # age of the result the last live call served, None if fresh


def _parse_hourly(loc: dict, variables: list[str]) -> dict:
    hourly = loc.get("hourly", {})
    series = {v: hourly.get(v, []) for v in variables}
    series["time"] = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly.get("time", [])]
    return series


def fetch_open_meteo(zones: list[dict], at: datetime | None = None, model: str | None = None,
                     variables: list[str] | None = None) -> dict[str, dict]:
    """One multi-coordinate request for all zones -> {zone_id: hourly series (UTC)}.

    Live: forecast API with past_days=1 (gives the 24 h accumulation, D8), cached for
    OPEN_METEO_TTL. Backfill (`at` set): Historical Forecast API around that time, so
    features use what the model forecast then, not what happened.
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
    if at is not None:
        return _parse_locations(zones, _get_open_meteo(url, params), variables)

    global last_stale_min
    key = tuple(sorted(params.items()))
    now = datetime.now(timezone.utc)
    hit = _open_meteo_cache.get(key)
    last_stale_min = None
    if hit and now - hit[0] < OPEN_METEO_TTL:
        return hit[1]
    try:
        result = _parse_locations(zones, _get_open_meteo(url, params), variables)
    except httpx.HTTPError as exc:
        limit = OPEN_METEO_DAILY_STALE_MAX if "daily" in str(exc).lower() else OPEN_METEO_STALE_MAX
        if hit and now - hit[0] < limit:
            log.warning("Open-Meteo failed (%s); using result from %s", exc, hit[0].isoformat())
            last_stale_min = int((now - hit[0]).total_seconds() // 60)
            return hit[1]
        raise
    _open_meteo_cache[key] = (now, result)
    return result


def _get_open_meteo(url: str, params: dict):
    """GET with one retry on 429; errors carry Open-Meteo's own reason (e.g. which limit)."""
    for attempt in range(2):
        r = httpx.get(url, params=params, timeout=20)
        if r.status_code == 429 and attempt == 0:
            time.sleep(OPEN_METEO_RETRY_S)
            continue
        if r.is_error:
            try:
                reason = r.json().get("reason") or r.reason_phrase
            except ValueError:
                reason = r.reason_phrase
            raise httpx.HTTPStatusError(f"Open-Meteo HTTP {r.status_code}: {reason}",
                                        request=r.request, response=r)
        return r.json()


def _parse_locations(zones: list[dict], data, variables: list[str] | None) -> dict[str, dict]:
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


def fetch_flood_warnings(limit: int = 2000) -> list[dict]:
    """data.gov.my station list. Its readings are stale; only the coordinates are used (v2 D20)."""
    check_fault("flood")
    r = httpx.get(FLOOD_WARNING_URL, params={"limit": limit}, timeout=30, follow_redirects=True)
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
