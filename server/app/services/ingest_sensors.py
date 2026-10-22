"""JPS Public InfoBanjir rain gauges and river levels (implementation-plan-v2 D20, architecture §3.2).

InfoBanjir has no API. Both pages are HTML tables with no opening <tr> per row, so a row
starts at each <td data-th='No'>. Rain-gauge cells are mapped through the expanded header
(the 6-day "Daily Rainfall" header spans 6 columns); water-level cells carry their own
data-th name. If an expected column is missing the fetch raises, so the run records the
source as failed instead of reading the wrong column.

data.gov.my's flood-warning list is used only as a coordinate lookup: its readings were
all more than a day old when checked (22 Oct 2026).
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import httpx

from ..config import check_fault
from .ingest_weather import fetch_flood_warnings

log = logging.getLogger("huda")

RAIN_URL = "https://publicinfobanjir.water.gov.my/wp-content/themes/shapely/agency/searchresultrainfall.php"
RIVER_URL = "https://publicinfobanjir.water.gov.my/aras-air/data-paras-air/aras-air-data/"
STATES = ("SEL", "WLH", "NSN", "JHR")  # the states that have zones (spec §5)
STATE_NAMES = {"SEL": "Selangor", "WLH": "Kuala Lumpur", "NSN": "Negeri Sembilan", "JHR": "Johor"}
HEADERS = {"User-Agent": "HUDA/1.0 (flood-rain early warning; contact: tuanwisam@gmail.com)"}
MYT = timezone(timedelta(hours=8))

TTL = timedelta(minutes=15)        # stations update every 15 min
STALE_MAX = timedelta(minutes=45)  # on failure, serve the last good page up to this old
_cache: dict[tuple, tuple[datetime, list[dict]]] = {}


class _RowParser(HTMLParser):
    """Header cells (text, colspan, rowspan) and body rows [(data_th, text), …]."""

    def __init__(self):
        super().__init__()
        self.headers: list[tuple[str, int, bool]] = []
        self.rows: list[list[tuple[str | None, str]]] = []
        self._cell: list[str] | None = None
        self._cell_th: str | None = None
        self._in_th = False
        self._th_attrs: dict = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "th":
            self._in_th, self._th_attrs, self._cell = True, a, []
        elif tag == "td":
            if a.get("data-th") == "No":
                self.rows.append([])
            self._cell, self._cell_th = [], a.get("data-th")
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag == "th" and self._in_th:
            text = _clean("".join(self._cell or []))
            spans = "colspan" in self._th_attrs or "rowspan" in self._th_attrs
            self.headers.append((text, int(self._th_attrs.get("colspan") or 1), spans))
            self._in_th, self._cell = False, None
        elif tag == "td" and self._cell is not None:
            if self.rows:
                self.rows[-1].append((self._cell_th, _clean("".join(self._cell))))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _num(s: str | None) -> float | None:
    try:
        return float(s.replace(",", "")) if s not in (None, "", "-") else None
    except ValueError:
        return None


def _myt(s: str | None) -> datetime | None:
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s or "", fmt).replace(tzinfo=MYT).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _find(columns: list[str], *names: str) -> int:
    for i, c in enumerate(columns):
        if any(c.lower().startswith(n) for n in names):
            return i
    raise ValueError(f"InfoBanjir layout changed: no column {names[0]!r} in {columns}")


def parse_rain(html: str, state: str) -> list[dict]:
    """Rain-gauge page → [{station_id, name, district, state, ts, rain_1h_mm, rain_today_mm}]."""
    p = _RowParser()
    p.feed(html)
    columns = [text for text, span, top in p.headers if top for _ in range(span)]
    idx = {k: _find(columns, *n) for k, n in {
        "id": ("station id",), "name": ("station",), "district": ("district",),
        "updated": ("last updated",), "midnight": ("rainfall from midnight",), "hour": ("total 1 hour",)}.items()}
    idx["name"] = next(i for i, c in enumerate(columns) if c.lower() == "station")
    out = []
    for row in p.rows:
        cells = [text for _, text in row]
        if len(cells) < len(columns):
            continue
        sid = cells[idx["id"]]
        if not sid:
            continue
        out.append({"station_id": sid, "name": cells[idx["name"]], "district": cells[idx["district"]],
                    "state": STATE_NAMES.get(state, state), "ts": _myt(cells[idx["updated"]]),
                    "rain_1h_mm": _num(cells[idx["hour"]]), "rain_today_mm": _num(cells[idx["midnight"]])})
    if p.rows and not out:
        raise ValueError("InfoBanjir rain page had rows but none could be read")
    return out


def river_indicator(level: float | None, alert: float | None, warning: float | None,
                    danger: float | None) -> str | None:
    """NORMAL · ALERT · WARNING · DANGER from the station's own thresholds."""
    if level is None or not all(v is not None and v > 0 for v in (alert, warning, danger)):
        return None
    if level >= danger:
        return "DANGER"
    if level >= warning:
        return "WARNING"
    if level >= alert:
        return "ALERT"
    return "NORMAL"


def parse_river(html: str, state: str) -> list[dict]:
    """Water-level page → [{station_id, name, district, state, ts, water_level_m, indicator}]."""
    p = _RowParser()
    p.feed(html)
    out = []
    for row in p.rows:
        cells = {th: text for th, text in row if th}
        if "Station ID" not in cells:
            continue
        missing = {"Last Update", "wl", "Alert", "Warning", "Danger"} - cells.keys()
        if missing:
            raise ValueError(f"InfoBanjir layout changed: no water-level cells {sorted(missing)}")
        level = _num(cells["wl"])
        out.append({"station_id": cells["Station ID"], "name": cells.get("Station Name"),
                    "district": cells.get("District"), "state": STATE_NAMES.get(state, state),
                    "ts": _myt(cells["Last Update"]), "water_level_m": level,
                    "indicator": river_indicator(level, _num(cells["Alert"]), _num(cells["Warning"]),
                                                 _num(cells["Danger"]))})
    return out


def _get(kind: str, state: str) -> list[dict]:
    check_fault("infobanjir")
    key = (kind, state)
    now = datetime.now(timezone.utc)
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]
    try:
        if kind == "rain":
            r = httpx.get(RAIN_URL, params={"state": state, "district": "ALL", "station": "ALL",
                                            "language": "1", "loginStatus": "0"},
                          headers=HEADERS, timeout=20, follow_redirects=True)
            r.raise_for_status()
            rows = parse_rain(r.text, state)
        else:
            r = httpx.get(RIVER_URL, params={"state": state, "district": "ALL", "station": "ALL", "lang": "en"},
                          headers=HEADERS, timeout=20, follow_redirects=True)
            r.raise_for_status()
            rows = parse_river(r.text, state)
    except (httpx.HTTPError, ValueError) as exc:
        if hit and now - hit[0] < STALE_MAX:
            log.warning("InfoBanjir %s %s failed (%s); using page from %s", kind, state, exc, hit[0].isoformat())
            return hit[1]
        raise
    _cache[key] = (now, rows)
    return rows


def fetch_all(states: tuple[str, ...] = STATES) -> tuple[list[dict], dict[str, str]]:
    """Every gauge and river station for the given states.

    Returns (readings, status) where each reading has `kind` ('rain' | 'river') and status is
    {"rain:SEL": "ok" | "failed", …}. One failing page doesn't stop the others.
    """
    readings, status = [], {}
    for state in states:
        for kind in ("rain", "river"):
            try:
                readings += [{**r, "kind": kind} for r in _get(kind, state)]
                status[f"{kind}:{state}"] = "ok"
            except Exception as exc:  # noqa: BLE001
                status[f"{kind}:{state}"] = "failed"
                log.warning("InfoBanjir %s %s failed: %s", kind, state, exc)
    return readings, status


def coords_from_station_id(station_id: str) -> tuple[float, float] | None:
    """JPS 7-digit IDs encode a 0.1° cell: 3717101 → 3.7° N, 101.7° E (D21). Returns the cell centre."""
    m = re.fullmatch(r"(\d{2})(\d{2})\d{3}", station_id.strip("_"))
    if not m:
        return None
    lat, lon = int(m[1]) / 10 + 0.05, 100 + int(m[2]) / 10 + 0.05
    return (round(lat, 2), round(lon, 2)) if 1.0 <= lat <= 7.5 and 99.5 <= lon <= 105 else None


def name_key(name: str | None, state: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{state or ''}|{name or ''}".lower())


def official_coords() -> dict[str, tuple[float, float]]:
    """Coordinates from the data.gov.my station list, keyed by JPS station ID and by name_key().

    Readings in that list are stale; only the coordinates are used.
    """
    out = {}
    for s in fetch_flood_warnings():
        lat, lon = s.get("latitude"), s.get("longitude")
        if lat is None or lon is None:
            continue
        for key in (s.get("station_id"), s.get("station_code")):
            if key:
                out[str(key).strip("_")] = (float(lat), float(lon))
        state = {v.upper(): v for v in STATE_NAMES.values()}.get(
            "KUALA LUMPUR" if "KUALA LUMPUR" in str(s.get("state")) else str(s.get("state")).upper())
        if state and s.get("station_name"):
            out.setdefault(name_key(s["station_name"], state), (float(lat), float(lon)))
    return out
