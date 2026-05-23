from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Job
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def job_data(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "priority": job.priority,
        "status": job.status,
        "error_type": job.error_type,
        "error_message": job.error_message,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("")
def list_jobs(
    status: str = "all",
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = select(Job).order_by(Job.priority, Job.created_at, Job.id)
    if status != "all":
        statement = statement.where(Job.status == status)

    jobs = session.scalars(statement).all()
    return {"ok": True, "data": {"items": [job_data(job) for job in jobs]}}


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    job = session.get(Job, job_id)
    if job is None:
        raise json_error(404, "NOT_FOUND", "Job not found.")
    if job.status != "failed":
        raise json_error(409, "CONFLICT", "Only failed jobs can be retried.")

    job.status = "pending"
    job.retry_count += 1
    job.locked_by = None
    job.locked_at = None
    job.heartbeat_at = None
    job.started_at = None
    job.finished_at = None
    job.updated_at = jst_iso()
    session.commit()
    return {"ok": True, "data": job_data(job)}
