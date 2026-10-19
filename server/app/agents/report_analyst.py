"""Report Analyst (spec FR-21): daily 08:00 MYT summary and on-demand reports.

Every number in a report is computed here in Python and inserted verbatim. Gemini
writes only the short narrative; if it fails, the report is the table alone.
"""

import csv
import io
import json
import logging
from datetime import datetime, timedelta

from .. import repo
from .gemini_client import GeminiUnavailable, generate

log = logging.getLogger("huda")

MYT = timedelta(hours=8)

SYSTEM = """You summarise flood-rain monitoring statistics for estate managers.
Write 3–5 sentences of plain English. Use ONLY the numbers in the JSON you are given;
do not add numbers, causes or forecasts that are not in it. Mention the zones with the most
RED/AMBER time and any alerts sent. No headings, no lists, no markdown tables."""

CSV_FIELDS = ["zone", "runs", "amber_runs", "red_runs", "alerts_sent", "peak_rain_rate_mmh", "peak_p_ml"]


def compute_stats(zones: list[dict], predictions: list[dict], warnings: list[dict]) -> dict:
    """Pure: per-zone counts and peaks for the period."""
    by_zone = {z["id"]: {"zone": z["name"], "runs": 0, "amber_runs": 0, "red_runs": 0, "alerts_sent": 0,
                         "peak_rain_rate_mmh": None, "peak_p_ml": None} for z in zones}
    for p in predictions:
        row = by_zone.get(p["zone_id"])
        if not row:
            continue
        row["runs"] += 1
        row["amber_runs"] += p["level"] == "AMBER"
        row["red_runs"] += p["level"] == "RED"
        for field, key in (("rain_rate_max", "peak_rain_rate_mmh"), ("p_ml", "peak_p_ml")):
            if p.get(field) is not None and (row[key] is None or p[field] > row[key]):
                row[key] = round(p[field], 2)
    events = []
    for w in warnings:
        row = by_zone.get(w["zone_id"])
        if row and w["level"] != "GREEN":
            row["alerts_sent"] += 1
            events.append({"zone": row["zone"], "level": w["level"], "sent_at": w["sent_at"]})
    rows = sorted(by_zone.values(), key=lambda r: (-r["red_runs"], -r["amber_runs"], r["zone"]))
    totals = {"alerts_sent": sum(r["alerts_sent"] for r in rows),
              "red_alerts": sum(1 for e in events if e["level"] == "RED"),
              "zones_with_red": sum(1 for r in rows if r["red_runs"])}
    return {"rows": rows, "totals": totals, "notable": [e for e in events if e["level"] == "RED"][:5]}


def _fmt(v) -> str:
    return "–" if v is None else f"{v:g}" if isinstance(v, float) else str(v)


def to_markdown(title: str, start: datetime, end: datetime, stats: dict, narrative: str | None) -> str:
    myt = lambda d: (d + MYT).strftime("%d %b %Y %H:%M")  # noqa: E731
    lines = [f"# {title}", "", f"**Period:** {myt(start)} – {myt(end)} MYT", ""]
    if narrative:
        lines += [narrative.strip(), ""]
    t = stats["totals"]
    lines += [f"**Alerts sent:** {t['alerts_sent']} ({t['red_alerts']} RED) · "
              f"**Zones reaching RED:** {t['zones_with_red']}", "",
              "| Zone | Runs | AMBER runs | RED runs | Alerts sent | Peak rain rate (mm/h) | Peak ML probability |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    lines += [f"| {r['zone']} | {r['runs']} | {r['amber_runs']} | {r['red_runs']} | {r['alerts_sent']} | "
              f"{_fmt(r['peak_rain_rate_mmh'])} | {_fmt(r['peak_p_ml'])} |" for r in stats["rows"]]
    if stats["notable"]:
        lines += ["", "## Notable events", ""]
        lines += [f"- 🔴 RED · {e['zone']} · {(repo.parse_ts(e['sent_at']) + MYT).strftime('%d %b %H:%M')} MYT"
                  for e in stats["notable"]]
    lines += ["", "_Weather radar by RainViewer · Weather data by Open-Meteo.com (CC BY 4.0) · "
              "MET Malaysia via data.gov.my_"]
    return "\n".join(lines)


def to_csv(stats: dict) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(stats["rows"])
    return buf.getvalue()


def gather(zone_ids: list[str] | None, start: datetime, end: datetime) -> dict:
    zones = [z for z in repo.list_zones(active=None) if not zone_ids or z["id"] in zone_ids]
    ids = [z["id"] for z in zones]
    return compute_stats(zones, repo.predictions_between(start, end, ids), repo.warnings_between(start, end, ids))


def generate_report(report_id: str) -> None:
    report = repo.get_report(report_id)
    try:
        start, end = repo.parse_ts(report["period_start"]), repo.parse_ts(report["period_end"])
        stats = gather(report.get("zone_ids") or None, start, end)
        narrative = None
        try:
            payload = {"period_myt": [(start + MYT).isoformat(), (end + MYT).isoformat()],
                       "totals": stats["totals"], "zones": stats["rows"][:8]}
            narrative = (generate(json.dumps(payload), system=SYSTEM, agent="report_analyst").text or "").strip()
        except GeminiUnavailable as exc:
            log.info("report analyst: table-only fallback (%s)", exc)
        title = {"daily": "HUDA Daily Summary", "event": "HUDA Event Report"}.get(report["type"], "HUDA Report")
        repo.update_report(report_id, {"content_md": to_markdown(title, start, end, stats, narrative),
                                       "status": "ready"})
        repo.log_event("agent", f"report {report_id} ready", meta={"report_id": report_id})
    except Exception as exc:  # noqa: BLE001
        repo.update_report(report_id, {"status": "failed", "error": str(exc)[:500]})
        repo.log_event("agent", f"report {report_id} failed: {exc}", "error", meta={"report_id": report_id})


def daily_period(now: datetime) -> tuple[datetime, datetime]:
    """Previous full MYT day, as UTC datetimes."""
    local_midnight = (now + MYT).replace(hour=0, minute=0, second=0, microsecond=0)
    end = local_midnight - MYT
    return end - timedelta(days=1), end
