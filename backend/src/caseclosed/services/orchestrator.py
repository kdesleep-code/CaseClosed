from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta

from caseclosed.db.models import Job
from caseclosed.services.contact_registration_prefill import (
    handle_contact_registration_prefill,
)
from caseclosed.services.queue import QueueInterface
from caseclosed.services.queue import SQLiteQueue

JobHandler = Callable[[Job], dict[str, object]]

DEFAULT_HANDLERS: dict[str, JobHandler] = {
    "contact_registration_prefill": handle_contact_registration_prefill,
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
            self.queue.fail(
                job.id,
                error_type=type(error).__name__,
                error_message=str(error),
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
