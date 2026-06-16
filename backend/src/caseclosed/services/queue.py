from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from typing import Protocol

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update

from caseclosed.db import runtime
from caseclosed.db.models import Job


class QueueInterface(Protocol):
    def claim_next(self, worker_id: str) -> Job | None: ...

    def heartbeat(self, job_id: str, worker_id: str) -> Job: ...

    def succeed(self, job_id: str, result: dict[str, object]) -> Job: ...

    def fail(self, job_id: str, *, error_type: str, error_message: str) -> Job: ...

    def retry_later(
        self,
        job_id: str,
        *,
        error_type: str,
        error_message: str,
        available_at: str,
    ) -> Job: ...

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
            for _ in range(3):
                job_id = session.scalar(
                    select(Job.id)
                    .where(
                        Job.status == "pending",
                        or_(Job.available_at.is_(None), Job.available_at <= claimed_at),
                    )
                    .order_by(Job.priority, Job.created_at, Job.id)
                )
                if job_id is None:
                    return None

                result = session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "pending")
                    .values(
                        status="running",
                        locked_by=worker_id,
                        locked_at=claimed_at,
                        heartbeat_at=claimed_at,
                        started_at=claimed_at,
                        finished_at=None,
                        updated_at=claimed_at,
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue

                session.commit()
                return session.get(Job, job_id)

            return None

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

    def retry_later(
        self,
        job_id: str,
        *,
        error_type: str,
        error_message: str,
        available_at: str,
    ) -> Job:
        updated_at = runtime.jst_iso()
        with runtime.SessionLocal() as session:
            job = self._require_running_job(session, job_id)
            job.status = "pending"
            job.error_type = error_type
            job.error_message = error_message
            job.retry_count += 1
            job.locked_by = None
            job.locked_at = None
            job.heartbeat_at = None
            job.started_at = None
            job.finished_at = None
            job.available_at = available_at
            job.updated_at = updated_at
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

                stale_ids.append(job.id)
                next_retry_count = job.retry_count + 1
                if next_retry_count > job.max_retries:
                    job.status = "failed"
                    job.error_type = "StaleJobTimeout"
                    job.error_message = "Running job exceeded heartbeat timeout."
                    job.finished_at = stale_at
                else:
                    job.status = "pending"
                    job.error_type = "StaleJobTimeout"
                    job.error_message = "Running job exceeded heartbeat timeout and was requeued."
                    job.locked_by = None
                    job.locked_at = None
                    job.heartbeat_at = None
                    job.started_at = None
                    job.finished_at = None
                    job.retry_count = next_retry_count
                job.updated_at = stale_at

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
