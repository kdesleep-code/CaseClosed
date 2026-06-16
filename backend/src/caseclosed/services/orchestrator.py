from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta

from caseclosed.db import runtime
from caseclosed.db.models import Job
from caseclosed.services.contact_ai_memo_update import (
    handle_contact_ai_memo_update,
)
from caseclosed.services.contact_resolution_followup import (
    handle_contact_resolution_followup,
)
from caseclosed.services.contact_registration_prefill import (
    handle_contact_registration_prefill,
)
from caseclosed.services.mail_importance_classification import (
    handle_mail_importance_classification,
)
from caseclosed.services.mail_attachment_fetch import handle_mail_attachment_fetch
from caseclosed.services.mail_sending import handle_mail_send_mock
from caseclosed.services.mail_summary import handle_mail_summary
from caseclosed.services.mail_thread_summary import handle_mail_thread_summary
from caseclosed.services.llm_provider import OpenAIProviderError
from caseclosed.services.queue import QueueInterface
from caseclosed.services.queue import SQLiteQueue

JobHandler = Callable[[Job], dict[str, object]]

TRANSIENT_OPENAI_ERROR_MARKERS = (
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "name resolution",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "network is unreachable",
    "temporarily unavailable",
    "HTTP 408",
    "HTTP 409",
    "HTTP 429",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
)

MAX_TRANSIENT_RETRY_DELAY_MINUTES = 30

DEFAULT_HANDLERS: dict[str, JobHandler] = {
    "contact_ai_memo_update": handle_contact_ai_memo_update,
    "contact_registration_prefill": handle_contact_registration_prefill,
    "contact_resolution_followup": handle_contact_resolution_followup,
    "mail_importance_classification": handle_mail_importance_classification,
    "mail_attachment_fetch": handle_mail_attachment_fetch,
    "mail_summary": handle_mail_summary,
    "mail_thread_summary": handle_mail_thread_summary,
    "mail_send_mock": handle_mail_send_mock,
}


class Orchestrator:
    def __init__(
        self,
        *,
        handlers: dict[str, JobHandler] | None = None,
        queue: QueueInterface | None = None,
        worker_id: str = "worker-main",
    ) -> None:
        self.handlers = handlers if handlers is not None else DEFAULT_HANDLERS
        self.queue = queue or SQLiteQueue()
        self.worker_id = worker_id

    def run_once(self) -> str | None:
        job = self.queue.claim_next(self.worker_id)
        if job is None:
            return None

        handler = self.handlers.get(job.job_type)
        if handler is None:
            self.queue.fail(
                job.id,
                error_type="UnknownJobType",
                error_message=f"No handler registered for job type: {job.job_type}",
            )
            return job.id

        try:
            result = handler(job)
        except Exception as error:
            error_type = type(error).__name__
            error_message = str(error)
            if should_retry_job_error(job, error):
                self.queue.retry_later(
                    job.id,
                    error_type=error_type,
                    error_message=error_message,
                    available_at=next_retry_available_at(job),
                )
            else:
                self.queue.fail(
                    job.id,
                    error_type=error_type,
                    error_message=error_message,
                )
        else:
            self.queue.succeed(job.id, result)
        return job.id

    def mark_stale_jobs(
        self,
        *,
        now: datetime,
        heartbeat_timeout: timedelta,
    ) -> list[str]:
        return self.queue.mark_stale_jobs(
            now=now,
            heartbeat_timeout=heartbeat_timeout,
        )


def should_retry_job_error(job: Job, error: Exception) -> bool:
    if job.retry_count >= job.max_retries:
        return False
    if not isinstance(error, OpenAIProviderError):
        return False
    message = str(error).lower()
    return any(marker.lower() in message for marker in TRANSIENT_OPENAI_ERROR_MARKERS)


def next_retry_available_at(job: Job) -> str:
    delay_minutes = min(
        MAX_TRANSIENT_RETRY_DELAY_MINUTES,
        2 ** job.retry_count * 2,
    )
    return runtime.jst_iso(runtime.jst_now() + timedelta(minutes=delay_minutes))
