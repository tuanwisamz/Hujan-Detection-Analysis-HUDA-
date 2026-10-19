"""HUDA Assistant / Report Analyst tools (architecture.md §4).

Each tool is a Python function plus its Gemini declaration. Tools read through
repo.py — the same data the dashboards show. `draft_warning` is admin-only and
only creates a pending_approval row; it never sends (spec FR-22).
"""

from datetime import timedelta

from .. import repo
from ..auth import User
from ..services import ingest_weather


def _zone_or_error(zone: str) -> dict:
    z = repo.resolve_zone(zone)
    if not z:
        raise ValueError(f"Unknown or ambiguous zone '{zone}'. Use a township name or slug.")
    return z


def _status_row(z: dict, p: dict | None) -> dict:
    p = p or {}
    return {"zone": z["name"], "slug": z["slug"], "district": z.get("district"), "level": p.get("level"),
            "rain_rate_max_mmh": p.get("rain_rate_max"), "eta_min": p.get("eta_min"), "p_ml": p.get("p_ml"),
            "official_warning": p.get("official_warning"), "updated_at": p.get("ts"),
            "why": (p.get("explanation") or {}).get("rule")}


def get_zone_status(user: User, zone: str | None = None) -> dict:
    latest = repo.latest_predictions()
    if zone:
        z = _zone_or_error(zone)
        return _status_row(z, latest.get(z["id"]))
    return {"zones": [_status_row(z, latest.get(z["id"])) for z in repo.list_zones()]}


def get_nowcast(user: User, zone: str) -> dict:
    z = _zone_or_error(zone)
    p = repo.latest_predictions().get(z["id"]) or {}
    return {"zone": z["name"], "window": "next 60 min (radar nowcast)",
            "rain_rate_max_mmh": p.get("rain_rate_max"), "eta_heavy_rain_min": p.get("eta_min"),
            "expected_accum_1h_mm": p.get("accum_1h"), "updated_at": p.get("ts")}


def get_forecast(user: User, zone: str, hours: int = 3) -> dict:
    z = _zone_or_error(zone)
    series = ingest_weather.fetch_open_meteo([z])[z["id"]]
    now = repo.now()
    rows = [{"time": repo.iso(t), "precip_mm": series["precipitation"][i], "cape": series["cape"][i]}
            for i, t in enumerate(series["time"]) if now - timedelta(hours=1) < t <= now + timedelta(hours=hours)]
    return {"zone": z["name"], "source": "Open-Meteo hourly forecast", "hours": rows}


def get_official_warnings(user: User, zone: str | None = None) -> dict:
    zones = [_zone_or_error(zone)] if zone else repo.list_zones()
    matched = ingest_weather.match_warnings(ingest_weather.fetch_met_warnings(), zones)
    return {"source": "MET Malaysia via data.gov.my",
            "warnings": [{"zone": z["name"], **matched[z["id"]]} for z in zones if z["id"] in matched]}


def list_recent_alerts(user: User, hours: int = 24) -> dict:
    res = repo.sent_alerts(None, frm=repo.now() - timedelta(hours=hours), limit=20)
    return {"alerts": [{"zone": (a.get("zones") or {}).get("name"), "level": a["level"],
                        "sent_at": a["sent_at"], "source": a["source"]} for a in res["items"]]}


def draft_warning(user: User, zone: str, level: str, message_en: str | None = None,
                  message_ms: str | None = None) -> dict:
    if not user.is_admin:
        raise PermissionError("draft_warning is admin-only")
    if level not in ("AMBER", "RED"):
        raise ValueError("level must be AMBER or RED")
    z = _zone_or_error(zone)
    row = repo.create_warning({"zone_id": z["id"], "level": level, "status": "pending_approval",
                               "source": "agent", "created_by": user.id,
                               "message_en": message_en, "message_ms": message_ms,
                               "expires_at": repo.iso(repo.now() + timedelta(hours=2))})
    repo.log_event("admin", f"Assistant drafted {level} warning for {z['name']}", actor=user.id,
                   meta={"zone_id": z["id"], "warning_id": row["id"]})
    return {"pending_warning_id": row["id"], "status": "pending_approval",
            "note": "Not sent. An admin must approve it on the Warnings page."}


ZONE_ARG = {"zone": {"type": "string", "description": "Township name or slug, e.g. 'Elmina' or 'city-of-elmina'"}}

DECLARATIONS = {
    "get_zone_status": ("Current risk level and key numbers for one township, or all townships if zone is omitted.",
                        {"type": "object", "properties": ZONE_ARG}),
    "get_nowcast": ("Radar nowcast for the next 60 minutes: max rain rate and ETA of heavy rain.",
                    {"type": "object", "properties": ZONE_ARG, "required": ["zone"]}),
    "get_forecast": ("Hourly Open-Meteo forecast (precipitation, CAPE) for the next few hours.",
                     {"type": "object", "properties": {**ZONE_ARG, "hours": {"type": "integer", "minimum": 1,
                                                                            "maximum": 12}},
                      "required": ["zone"]}),
    "get_official_warnings": ("Active MET Malaysia rain/thunderstorm warnings matched to townships.",
                              {"type": "object", "properties": ZONE_ARG}),
    "list_recent_alerts": ("HUDA alerts sent to Telegram in the last N hours.",
                           {"type": "object", "properties": {"hours": {"type": "integer", "minimum": 1,
                                                                       "maximum": 168}}}),
    "draft_warning": ("ADMIN ONLY. Create a warning that waits for human approval. It is never sent automatically.",
                      {"type": "object", "properties": {**ZONE_ARG,
                                                        "level": {"type": "string", "enum": ["AMBER", "RED"]},
                                                        "message_en": {"type": "string"},
                                                        "message_ms": {"type": "string"}},
                       "required": ["zone", "level"]}),
}

FUNCTIONS = {
    "get_zone_status": get_zone_status, "get_nowcast": get_nowcast, "get_forecast": get_forecast,
    "get_official_warnings": get_official_warnings, "list_recent_alerts": list_recent_alerts,
    "draft_warning": draft_warning,
}

ADMIN_ONLY = {"draft_warning"}


def available(user: User) -> list[str]:
    return [n for n in FUNCTIONS if n not in ADMIN_ONLY or user.is_admin]


def gemini_tools(user: User):
    from google.genai import types

    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=n, description=DECLARATIONS[n][0], parameters_json_schema=DECLARATIONS[n][1])
        for n in available(user)])]


def call(user: User, name: str, args: dict) -> dict:
    if name not in available(user):
        return {"error": f"tool '{name}' is not available"}
    try:
        return FUNCTIONS[name](user, **(args or {}))
    except (ValueError, PermissionError, TypeError) as exc:
        return {"error": str(exc)}
    except Exception as exc:  # upstream failure: tell the model, don't guess
        return {"error": f"data unavailable: {exc}"}
