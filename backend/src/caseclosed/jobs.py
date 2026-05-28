from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import GmailThread
from caseclosed.db.models import Job
from caseclosed.db.models import MailSendRequest
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.services.orchestrator import Orchestrator

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def job_data(job: Job, session: DatabaseSession | None = None) -> dict[str, object]:
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
        "related_mail": related_mail_data(session, job) if session is not None else None,
    }


def related_mail_data(
    session: DatabaseSession | None,
    job: Job,
) -> dict[str, object] | None:
    if session is None:
        return None
    try:
        payload = json.loads(job.payload_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    message = related_message_from_payload(session, payload)
    if message is not None:
        return gmail_message_job_context(message)

    thread = related_thread_from_payload(session, payload)
    if thread is not None:
        latest_message = session.scalar(
            select(GmailMessage)
            .where(GmailMessage.thread_id == thread.id)
            .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
        )
        if latest_message is not None:
            context = gmail_message_job_context(latest_message)
            context["thread_id"] = thread.id
            context["gmail_thread_id"] = thread.gmail_thread_id
            context["context_type"] = "thread"
            return context
        return {
            "context_type": "thread",
            "message_id": None,
            "thread_id": thread.id,
            "gmail_message_id": None,
            "gmail_thread_id": thread.gmail_thread_id,
            "subject": thread.subject_snapshot,
            "received_at": None,
            "from_address": None,
            "mail_url": None,
        }

    send_request_id = string_value(payload.get("send_request_id"))
    if send_request_id is not None:
        send_request = session.get(MailSendRequest, send_request_id)
        if send_request is None:
            return None
        if send_request.reply_to_message_id is not None:
            reply_message = session.get(GmailMessage, send_request.reply_to_message_id)
            if reply_message is not None:
                context = gmail_message_job_context(reply_message)
                context["context_type"] = "send_reply"
                return context
        return {
            "context_type": "send_request",
            "message_id": send_request.id,
            "thread_id": None,
            "gmail_message_id": None,
            "gmail_thread_id": None,
            "subject": send_request.subject,
            "received_at": send_request.created_at,
            "from_address": None,
            "mail_url": f"/mail/{send_request.id}",
        }

    return None


def related_message_from_payload(
    session: DatabaseSession,
    payload: dict[str, object],
) -> GmailMessage | None:
    for key in ("message_id", "reply_to_message_id"):
        message_id = string_value(payload.get(key))
        if message_id is None:
            continue
        message = session.get(GmailMessage, message_id)
        if message is not None:
            return message
    gmail_message_id = string_value(payload.get("gmail_message_id"))
    if gmail_message_id is not None:
        return session.scalar(
            select(GmailMessage).where(GmailMessage.gmail_message_id == gmail_message_id)
        )
    return None


def related_thread_from_payload(
    session: DatabaseSession,
    payload: dict[str, object],
) -> GmailThread | None:
    thread_id = string_value(payload.get("thread_id"))
    if thread_id is not None:
        thread = session.get(GmailThread, thread_id)
        if thread is not None:
            return thread
    gmail_thread_id = string_value(payload.get("gmail_thread_id"))
    if gmail_thread_id is not None:
        return session.scalar(
            select(GmailThread).where(GmailThread.gmail_thread_id == gmail_thread_id)
        )
    return None


def gmail_message_job_context(message: GmailMessage) -> dict[str, object]:
    return {
        "context_type": "message",
        "message_id": message.id,
        "thread_id": message.thread_id,
        "gmail_message_id": message.gmail_message_id,
        "gmail_thread_id": message.gmail_thread_id,
        "subject": message.subject,
        "received_at": message.received_at,
        "from_address": message.from_address,
        "mail_url": f"/mail/{message.id}",
    }


def string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


@router.get("")
def list_jobs(
    status: str = "all",
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = (
        select(Job)
        .where(Job.status != "succeeded")
        .order_by(Job.priority, Job.created_at, Job.id)
    )
    if status != "all":
        statement = select(Job).where(Job.status == status).order_by(
            Job.priority,
            Job.created_at,
            Job.id,
        )

    jobs = session.scalars(statement).all()
    return {"ok": True, "data": {"items": [job_data(job, session) for job in jobs]}}


@router.post("/run-next")
def run_next_job() -> dict[str, object]:
    job_id = Orchestrator(worker_id="worker-manual-api").run_once()
    return {"ok": True, "data": {"job_id": job_id}}


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
    return {"ok": True, "data": job_data(job, session)}
