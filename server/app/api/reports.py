from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import repo
from ..agents import report_analyst
from ..auth import User
from ..errors import ApiError, not_found
from ..models import ReportIn
from ..ratelimit import default_limit

router = APIRouter(prefix="/reports", tags=["reports"])


def _owned(report_id: str, user: User) -> dict:
    r = repo.get_report(report_id)
    if not r:
        raise not_found("Report")
    if not user.is_admin and r.get("created_by") != user.id:
        raise ApiError(403, "Not your report")
    return r


@router.get("")
def list_reports(user: User = Depends(default_limit)):
    return {"items": repo.list_reports(None if user.is_admin else user.id)}


@router.post("", status_code=202)
def create_report(body: ReportIn, tasks: BackgroundTasks, user: User = Depends(default_limit)):
    if (body.period_end - body.period_start).days > 92:
        raise ApiError(422, "Report period can be at most 92 days")
    r = repo.create_report({"type": body.type, "zone_ids": body.zone_ids or None,
                            "period_start": repo.iso(body.period_start), "period_end": repo.iso(body.period_end),
                            "created_by": user.id, "status": "generating"})
    tasks.add_task(report_analyst.generate_report, r["id"])
    return {"id": r["id"], "status": "generating"}


@router.get("/{report_id}")
def get_report(report_id: str, user: User = Depends(default_limit)):
    return _owned(report_id, user)


@router.get("/{report_id}/download")
def download(report_id: str, format: str = Query("md", pattern="^(md|csv)$"), user: User = Depends(default_limit)):
    r = _owned(report_id, user)
    if r["status"] != "ready":
        raise ApiError(409, f"Report is {r['status']}")
    name = f"huda-report-{r['created_at'][:10]}-{report_id[:8]}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if format == "md":
        return PlainTextResponse(r["content_md"] or "", media_type="text/markdown; charset=utf-8", headers=headers)
    stats = report_analyst.gather(r.get("zone_ids") or None, repo.parse_ts(r["period_start"]),
                                  repo.parse_ts(r["period_end"]))
    return PlainTextResponse(report_analyst.to_csv(stats), media_type="text/csv; charset=utf-8", headers=headers)
