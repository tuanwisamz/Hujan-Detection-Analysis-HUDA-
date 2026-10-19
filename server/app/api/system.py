from fastapi import APIRouter

from .. import repo
from ..services import classifier

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    try:
        last = repo.last_finished_run()
    except Exception:  # noqa: BLE001 — health must answer even if the DB is down
        last = None
    return {
        "status": "ok",
        "last_run_at": last["finished_at"] if last else None,
        "last_run_status": last["status"] if last else None,
        "model_version": classifier.model_version() or "rules_only",
    }
