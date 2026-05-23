from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from typing import Protocol

from sqlalchemy import or_
from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import Job


class QueueInterface(Protocol):
    def claim_next(self, worker_id: str) -> Job | None: ...

    def heartbeat(self, job_id: str, worker_id: str) -> Job: ...

    def succeed(self, job_id: str, result: dict[str, object]) -> Job: ...

    def fail(self, job_id: str, *, error_type: str, error_message: str) -> Job: ...

    def mark_stale_jobs(
        self,
        *,
        now: datetime,
        heartbeat_timeout: timedelta,
    ) -> list[str]: ...


class SQLiteQueue:
    def claim_next(self, worker_id: str) -> Job | None:
        claimed_at = runtime.jst_iso()
        with runtime.SessionLocal() as session:
            job = session.scalar(
                select(Job)
                .where(
                    Job.status == "pending",
                    or_(Job.available_at.is_(None), Job.available_at <= claimed_at),
                )
                .order_by(Job.priority, Job.created_at, Job.id)
            )
            if job is None:
                return None

            job.status = "running"
            job.locked_by = worker_id
            job.locked_at = claimed_at
            job.heartbeat_at = claimed_at
            job.started_at = claimed_at
            job.finished_at = None
            job.updated_at = claimed_at
            session.commit()
            return job

    def heartbeat(self, job_id: str, worker_id: str) -> Job:
        heartbeat_at = runtime.jst_iso()
        with runtime.SessionLocal() as session:
            job = self._require_running_job(session, job_id)
            if job.locked_by != worker_id:
                raise ValueError(f"Job is locked by another worker: {job_id}")

            job.heartbeat_at = heartbeat_at
            job.updated_at = heartbeat_at
            session.commit()
            return job

    def succeed(self, job_id: str, result: dict[str, object]) -> Job:
        finished_at = runtime.jst_iso()
        with runtime.SessionLocal() as session:
            job = self._require_running_job(session, job_id)
            job.status = "succeeded"
            job.result_json = json.dumps(result)
            job.error_type = None
            job.error_message = None
            job.finished_at = finished_at
            job.updated_at = finished_at
            session.commit()
            return job

    def fail(self, job_id: str, *, error_type: str, error_message: str) -> Job:
        finished_at = runtime.jst_iso()
        with runtime.SessionLocal() as session:
            job = self._require_running_job(session, job_id)
            job.status = "failed"
            job.error_type = error_type
            job.error_message = error_message
            job.finished_at = finished_at
            job.updated_at = finished_at
            session.commit()
            return job

    def mark_stale_jobs(
        self,
        *,
        now: datetime,
        heartbeat_timeout: timedelta,
    ) -> list[str]:
        stale_ids: list[str] = []
        stale_at = runtime.jst_iso(now)
        with runtime.SessionLocal() as session:
            jobs = session.scalars(
                select(Job).where(Job.status == "running").order_by(Job.id)
            ).all()
            for job in jobs:
                last_heartbeat = job.heartbeat_at or job.locked_at or job.started_at
                if last_heartbeat is None:
                    continue
                if now - runtime.parse_iso_datetime(last_heartbeat) <= heartbeat_timeout:
                    continue

                job.status = "stale"
                job.updated_at = stale_at
                stale_ids.append(job.id)

            session.commit()
        return stale_ids

    @staticmethod
    def _require_running_job(session, job_id: str) -> Job:
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError(f"Job not found: {job_id}")
        if job.status != "running":
            raise ValueError(f"Job is not running: {job_id}")
        return job
