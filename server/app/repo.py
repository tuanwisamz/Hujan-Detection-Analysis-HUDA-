"""Data access. API routes, the pipeline and agent tools all read through here,
so the Assistant sees exactly what the dashboards see."""

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone

from .db import sb
from .models import AppSettings

log = logging.getLogger("huda")


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---- Cursor pagination: ?limit=&cursor=<base64 "ts|id"> ----

def encode_cursor(row: dict, ts_field: str = "ts") -> str:
    return base64.urlsafe_b64encode(f"{row[ts_field]}|{row['id']}".encode()).decode()


def apply_cursor(query, cursor: str | None, ts_field: str = "ts"):
    if cursor:
        ts, rid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        query = query.or_(f"{ts_field}.lt.{ts},and({ts_field}.eq.{ts},id.lt.{rid})")
    return query.order(ts_field, desc=True).order("id", desc=True)


def page(rows: list[dict], limit: int, ts_field: str = "ts") -> dict:
    items = rows[:limit]
    next_cursor = encode_cursor(items[-1], ts_field) if len(rows) > limit and items else None
    return {"items": items, "next_cursor": next_cursor}


# ---- Logs (never raise: logging must not break a run) ----

def log_event(category: str, message: str, severity: str = "info",
              actor: str = "system", meta: dict | None = None) -> None:
    getattr(log, "warning" if severity == "warn" else severity, log.info)("[%s] %s", category, message)
    try:
        sb().table("logs").insert({"category": category, "message": message, "severity": severity,
                                   "actor": actor, "meta": meta or {}}).execute()
    except Exception:  # noqa: BLE001
        log.exception("failed to write log row")


# ---- Settings ----

def get_app_settings() -> AppSettings:
    rows = sb().table("settings").select("key,value").execute().data
    return AppSettings.model_validate({r["key"]: r["value"] for r in rows})


def save_app_settings(values: dict, by: str) -> None:
    rows = [{"key": k, "value": v, "updated_by": by, "updated_at": iso(now())} for k, v in values.items()]
    sb().table("settings").upsert(rows, on_conflict="key").execute()


# ---- Profiles & subscriptions ----

def get_profile(user_id: str) -> dict | None:
    rows = sb().table("profiles").select("*").eq("id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def upsert_profile(row: dict) -> dict:
    return sb().table("profiles").upsert(row, on_conflict="id").execute().data[0]


def update_profile(user_id: str, patch: dict) -> dict:
    return sb().table("profiles").update(patch).eq("id", user_id).execute().data[0]


def profile_by_link_code(code: str) -> dict | None:
    rows = (sb().table("profiles").select("*").eq("telegram_link_code", code)
            .gt("telegram_link_expires_at", iso(now())).limit(1).execute().data)
    return rows[0] if rows else None


def profile_by_chat(chat_id: int) -> dict | None:
    rows = sb().table("profiles").select("*").eq("telegram_chat_id", chat_id).limit(1).execute().data
    return rows[0] if rows else None


def get_subscriptions(user_id: str) -> list[dict]:
    return sb().table("subscriptions").select("zone_id,min_level").eq("user_id", user_id).execute().data


def put_subscriptions(user_id: str, subs: list[dict]) -> list[dict]:
    sb().table("subscriptions").delete().eq("user_id", user_id).execute()
    if subs:
        sb().table("subscriptions").insert([{"user_id": user_id, **s} for s in subs]).execute()
    return get_subscriptions(user_id)


def subscribers_for_zone(zone_id: str) -> list[dict]:
    """Linked Telegram users subscribed to a zone (FR-33 personal DMs)."""
    subs = sb().table("subscriptions").select("user_id,min_level").eq("zone_id", zone_id).execute().data
    if not subs:
        return []
    ids = [s["user_id"] for s in subs]
    profiles = (sb().table("profiles").select("id,telegram_chat_id,language").in_("id", ids)
                .not_.is_("telegram_chat_id", "null").execute().data)
    by_id = {p["id"]: p for p in profiles}
    return [{**by_id[s["user_id"]], "min_level": s["min_level"]} for s in subs if s["user_id"] in by_id]


# ---- Zones ----

def list_zones(active: bool | None = True, state: str | None = None) -> list[dict]:
    q = sb().table("zones").select("*")
    if active is not None:
        q = q.eq("active", active)
    if state:
        q = q.eq("state", state)
    return q.order("name").execute().data


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def get_zone(zone_id: str) -> dict | None:
    if not _is_uuid(zone_id):  # slugs are resolved by resolve_zone; a uuid column rejects them
        return None
    rows = sb().table("zones").select("*").eq("id", zone_id).limit(1).execute().data
    return rows[0] if rows else None


def resolve_zone(text: str) -> dict | None:
    """Find a zone by id, slug or (partial) name — e.g. "Elmina" → City of Elmina."""
    t = text.strip().lower()
    zones = list_zones(active=None)
    for z in zones:
        if t in (z["id"], z["slug"], z["name"].lower()):
            return z
    matches = [z for z in zones if t in z["name"].lower() or t.replace(" ", "-") in z["slug"]]
    return matches[0] if len(matches) == 1 else None


def create_zone(row: dict) -> dict:
    return sb().table("zones").insert(row).execute().data[0]


def update_zone(zone_id: str, patch: dict) -> dict | None:
    rows = sb().table("zones").update(patch).eq("id", zone_id).execute().data
    return rows[0] if rows else None


# ---- Runs & frames ----

def start_run(backfill_ts: datetime | None = None, min_gap_min: int = 8) -> str | None:
    """D12: returns a new run id, or None if a run is in progress / too recent."""
    return sb().rpc("start_run", {"p_min_gap_min": min_gap_min,
                                  "p_backfill_ts": iso(backfill_ts) if backfill_ts else None}).execute().data


def finish_run(run_id: str, status: str, sources: dict, error: str | None = None) -> None:
    sb().table("runs").update({"finished_at": iso(now()), "status": status,
                               "sources": sources, "error": error}).eq("id", run_id).execute()


def last_finished_run() -> dict | None:
    rows = (sb().table("runs").select("*").not_.is_("finished_at", "null")
            .order("started_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def last_run_with_nowcast() -> dict | None:
    rows = (sb().table("runs").select("*").in_("status", ["ok", "degraded"])
            .order("started_at", desc=True).limit(5).execute().data)
    for r in rows:
        if (r.get("sources") or {}).get("nowcast") == "ok":
            return r
    return None


def list_runs(limit: int = 50) -> list[dict]:
    return sb().table("runs").select("*").order("started_at", desc=True).limit(limit).execute().data


def runs_by_ids(ids: list[str]) -> list[dict]:
    return sb().table("runs").select("id,started_at,backfill_ts").in_("id", ids).execute().data if ids else []


def insert_frames(rows: list[dict]) -> None:
    if rows:
        sb().table("radar_frames").insert(rows).execute()


def frames_for_run(run_id: str, kind: str) -> list[dict]:
    return (sb().table("radar_frames").select("*").eq("run_id", run_id).eq("kind", kind)
            .order("ts").execute().data)


# ---- Predictions ----

def insert_predictions(rows: list[dict]) -> None:
    if rows:
        sb().table("predictions").insert(rows).execute()


def latest_predictions() -> dict[str, dict]:
    return {r["zone_id"]: r for r in sb().table("latest_predictions").select("*").execute().data}


def zone_timeseries(zone_id: str, hours: int) -> list[dict]:
    since = iso(now() - timedelta(hours=hours))
    return (sb().table("predictions").select("ts,level,rain_rate_max,p_ml").eq("zone_id", zone_id)
            .gte("ts", since).order("ts").execute().data)


def recent_levels(zone_id: str, minutes: int) -> list[dict]:
    since = iso(now() - timedelta(minutes=minutes))
    return (sb().table("predictions").select("ts,level").eq("zone_id", zone_id)
            .gte("ts", since).order("ts", desc=True).execute().data)


def query_predictions(zone_id=None, frm=None, to=None, level=None, limit=50, cursor=None) -> dict:
    q = sb().table("predictions").select("*")
    if zone_id:
        q = q.eq("zone_id", zone_id)
    if frm:
        q = q.gte("ts", iso(frm))
    if to:
        q = q.lte("ts", iso(to))
    if level:
        q = q.eq("level", level)
    rows = apply_cursor(q, cursor).limit(limit + 1).execute().data
    return page(rows, limit)


def predictions_between(start: datetime, end: datetime, zone_ids: list[str] | None = None) -> list[dict]:
    q = (sb().table("predictions").select("zone_id,ts,level,rain_rate_max,p_ml")
         .gte("ts", iso(start)).lte("ts", iso(end)))
    if zone_ids:
        q = q.in_("zone_id", zone_ids)
    return q.order("ts").limit(20000).execute().data


# ---- Warnings ----

def create_warning(row: dict) -> dict:
    return sb().table("warnings").insert(row).execute().data[0]


def update_warning(warning_id: str, patch: dict) -> dict:
    return sb().table("warnings").update(patch).eq("id", warning_id).execute().data[0]


def get_warning(warning_id: str) -> dict | None:
    if not _is_uuid(warning_id):
        return None
    rows = sb().table("warnings").select("*").eq("id", warning_id).limit(1).execute().data
    return rows[0] if rows else None


def zone_warnings(zone_id: str, since: datetime) -> list[dict]:
    return (sb().table("warnings").select("*").eq("zone_id", zone_id)
            .gte("created_at", iso(since)).order("created_at", desc=True).execute().data)


def last_sent_warning(zone_id: str) -> dict | None:
    rows = (sb().table("warnings").select("*").eq("zone_id", zone_id).eq("status", "sent")
            .order("sent_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def list_warnings(status: str | None = None, limit: int = 100) -> list[dict]:
    q = sb().table("warnings").select("*, zones(name, slug)")
    if status:
        q = q.eq("status", status)
    return q.order("created_at", desc=True).limit(limit).execute().data


def sent_alerts(zone_ids: list[str] | None, frm=None, to=None, level=None, limit=50, cursor=None) -> dict:
    q = sb().table("warnings").select("*, zones(name, slug)").eq("status", "sent")
    if zone_ids is not None:
        if not zone_ids:
            return {"items": [], "next_cursor": None}
        q = q.in_("zone_id", zone_ids)
    if frm:
        q = q.gte("sent_at", iso(frm))
    if to:
        q = q.lte("sent_at", iso(to))
    if level:
        q = q.eq("level", level)
    rows = apply_cursor(q, cursor, "sent_at").limit(limit + 1).execute().data
    return page(rows, limit, "sent_at")


def warnings_between(start: datetime, end: datetime, zone_ids: list[str] | None = None) -> list[dict]:
    q = (sb().table("warnings").select("zone_id,level,status,source,sent_at,message_en")
         .eq("status", "sent").gte("sent_at", iso(start)).lte("sent_at", iso(end)))
    if zone_ids:
        q = q.in_("zone_id", zone_ids)
    return q.order("sent_at").execute().data


# ---- Logs (read) ----

def query_logs(category=None, severity=None, frm=None, to=None, q_text=None,
               zone_ids: list[str] | None = None, limit=50, cursor=None) -> dict:
    q = sb().table("logs").select("*")
    if category:
        q = q.eq("category", category)
    if severity:
        q = q.eq("severity", severity)
    if frm:
        q = q.gte("ts", iso(frm))
    if to:
        q = q.lte("ts", iso(to))
    if q_text:
        q = q.ilike("message", f"%{q_text}%")
    if zone_ids is not None:
        if not zone_ids:
            return {"items": [], "next_cursor": None}
        q = q.in_("meta->>zone_id", zone_ids)
    rows = apply_cursor(q, cursor).limit(limit + 1).execute().data
    return page(rows, limit)


# ---- Reports ----

def create_report(row: dict) -> dict:
    return sb().table("reports").insert(row).execute().data[0]


def update_report(report_id: str, patch: dict) -> None:
    sb().table("reports").update(patch).eq("id", report_id).execute()


def get_report(report_id: str) -> dict | None:
    if not _is_uuid(report_id):
        return None
    rows = sb().table("reports").select("*").eq("id", report_id).limit(1).execute().data
    return rows[0] if rows else None


def station_key(kind: str, code: str) -> str:
    return f"jps-{kind}:{code}"


# ---- Sensors (implementation-plan-v2 §6.2) ----

STATION_FIELDS = ("id,kind,source,station_code,name,district,state,lat,lon,location_quality,"
                  "location_source,active,note,updated_at")


def list_stations(kind: str | None = None) -> list[dict]:
    q = sb().table("sensor_stations").select(STATION_FIELDS)
    if kind:
        q = q.eq("kind", kind)
    return q.limit(5000).execute().data


def get_station(station_id: str) -> dict | None:
    rows = sb().table("sensor_stations").select(STATION_FIELDS).eq("id", station_id).limit(1).execute().data
    return rows[0] if rows else None


def add_stations(rows: list[dict]) -> None:
    """Insert stations that don't exist yet; existing rows (and admin-checked locations) are kept."""
    if rows:
        sb().table("sensor_stations").upsert(rows, on_conflict="id", ignore_duplicates=True).execute()


def update_station(station_id: str, patch: dict) -> dict | None:
    rows = sb().table("sensor_stations").update(patch).eq("id", station_id).execute().data
    return rows[0] if rows else None


def insert_sensor_readings(rows: list[dict]) -> None:
    for i in range(0, len(rows), 500):
        sb().table("sensor_readings").upsert(rows[i:i + 500], on_conflict="station_id,ts",
                                             ignore_duplicates=True).execute()


def sensor_readings_since(station_ids: list[str], since: datetime) -> dict[str, list[dict]]:
    """{station_id: [reading, …]} with ts parsed, for the given stations since `since`."""
    out: dict[str, list[dict]] = {}
    for i in range(0, len(station_ids), 150):
        rows = (sb().table("sensor_readings").select("station_id,ts,rain_1h_mm,rain_today_mm,water_level_m,indicator")
                .in_("station_id", station_ids[i:i + 150]).gte("ts", iso(since)).limit(10000).execute().data)
        for r in rows:
            out.setdefault(r["station_id"], []).append({**r, "ts": parse_ts(r["ts"])})
    return out


# ---- Sirens (implementation-plan-v2 §6.3) ----

def list_sirens() -> list[dict]:
    return sb().table("sirens").select("*").order("created_at").execute().data


def get_siren(siren_id: str) -> dict | None:
    if not _is_uuid(siren_id):
        return None
    rows = sb().table("sirens").select("*").eq("id", siren_id).limit(1).execute().data
    return rows[0] if rows else None


def create_siren(row: dict) -> dict:
    return sb().table("sirens").insert(row).execute().data[0]


def update_siren(siren_id: str, patch: dict) -> dict | None:
    rows = sb().table("sirens").update(patch).eq("id", siren_id).execute().data
    return rows[0] if rows else None


def create_siren_activation(row: dict) -> dict:
    return sb().table("siren_activations").insert(row).execute().data[0]


def update_siren_activation(activation_id: str, patch: dict) -> dict:
    return sb().table("siren_activations").update(patch).eq("id", activation_id).execute().data[0]


def get_siren_activation(activation_id: str) -> dict | None:
    if not _is_uuid(activation_id):
        return None
    rows = sb().table("siren_activations").select("*").eq("id", activation_id).limit(1).execute().data
    return rows[0] if rows else None


def list_siren_activations(status: str | None = None, zone_id: str | None = None, limit: int = 100) -> list[dict]:
    q = sb().table("siren_activations").select("*, sirens(name, endpoint_url), zones(name, slug)")
    if status:
        q = q.eq("status", status)
    if zone_id:
        q = q.eq("zone_id", zone_id)
    return q.order("created_at", desc=True).limit(limit).execute().data


def open_siren_activations(zone_id: str | None = None) -> list[dict]:
    q = sb().table("siren_activations").select("*").in_("status", ["pending_approval", "active"])
    if zone_id:
        q = q.eq("zone_id", zone_id)
    return q.execute().data


def siren_activations_since(zone_id: str, since: datetime) -> list[dict]:
    return (sb().table("siren_activations").select("*").eq("zone_id", zone_id)
            .gte("created_at", iso(since)).execute().data)


def list_reports(created_by: str | None, limit: int = 100) -> list[dict]:
    q = sb().table("reports").select("id,type,zone_ids,period_start,period_end,created_by,created_at,status")
    if created_by:
        q = q.eq("created_by", created_by)
    return q.order("created_at", desc=True).limit(limit).execute().data
