from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import ExternalOperation
from caseclosed.db.models import Job
from caseclosed.db.models import WriteRequest
from caseclosed.db.runtime import get_session

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])


@router.get("/status")
def maintenance_status(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {
        "ok": True,
        "data": {
            "job_accepting": True,
            "running_jobs": count_rows(session, Job, Job.status == "running"),
            "pending_write_requests": count_rows(
                session,
                WriteRequest,
                WriteRequest.status == "pending",
            ),
            "external_unknown_count": count_rows(
                session,
                ExternalOperation,
                ExternalOperation.status == "unknown",
            ),
            "backup_status": "not_configured",
        },
    }


def count_rows(session: DatabaseSession, model, condition) -> int:
    return session.scalar(select(func.count()).select_from(model).where(condition)) or 0
