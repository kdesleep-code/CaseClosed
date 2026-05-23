from __future__ import annotations

import importlib
import sqlite3
from datetime import timedelta
from pathlib import Path

from caseclosed.db.runtime import parse_iso_datetime

from conftest import insert_phase_2_job


def test_sqlite_queue_claims_and_finishes_a_pending_job(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(database_path, job_id="job_later", status="pending")
    insert_phase_2_job(database_path, job_id="job_first", status="pending")

    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE jobs SET priority = 10 WHERE id = 'job_first'")
        connection.commit()

    queue_module = importlib.import_module("caseclosed.services.queue")
    queue = queue_module.SQLiteQueue()

    claimed_job = queue.claim_next("worker-1")
    queue.succeed(claimed_job.id, {"finished": True})

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, locked_by, result_json, started_at, finished_at
            FROM jobs
            WHERE id = ?
            """,
            ("job_first",),
        ).fetchone()

    assert claimed_job.id == "job_first"
    assert row[0:3] == ("succeeded", "worker-1", '{"finished": true}')
    assert row[3].endswith("+09:00")
    assert row[4].endswith("+09:00")


def test_sqlite_queue_failure_records_error(client, database_path: Path) -> None:
    del client
    insert_phase_2_job(database_path, job_id="job_fail", status="pending")

    queue_module = importlib.import_module("caseclosed.services.queue")
    queue = queue_module.SQLiteQueue()

    claimed_job = queue.claim_next("worker-1")
    queue.fail(claimed_job.id, error_type="WorkerError", error_message="boom")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, error_type, error_message FROM jobs WHERE id = ?",
            ("job_fail",),
        ).fetchone()

    assert row == ("failed", "WorkerError", "boom")


def test_sqlite_queue_refreshes_worker_heartbeat(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(database_path, job_id="job_heartbeat", status="pending")

    queue_module = importlib.import_module("caseclosed.services.queue")
    queue = queue_module.SQLiteQueue()

    claimed_job = queue.claim_next("worker-1")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?",
            ("2026-05-22T10:00:00+09:00", claimed_job.id),
        )
        connection.commit()

    queue.heartbeat(claimed_job.id, "worker-1")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT heartbeat_at, updated_at FROM jobs WHERE id = ?",
            ("job_heartbeat",),
        ).fetchone()

    assert row[0] != "2026-05-22T10:00:00+09:00"
    assert row[0].endswith("+09:00")
    assert row[1] == row[0]


def test_sqlite_queue_marks_old_running_jobs_stale(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(database_path, job_id="job_stale", status="running")
    insert_phase_2_job(database_path, job_id="job_fresh", status="running")

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?",
            ("2026-05-22T10:00:00+09:00", "job_stale"),
        )
        connection.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?",
            ("2026-05-22T10:09:00+09:00", "job_fresh"),
        )
        connection.commit()

    queue_module = importlib.import_module("caseclosed.services.queue")
    queue = queue_module.SQLiteQueue()

    stale_ids = queue.mark_stale_jobs(
        now=parse_iso_datetime("2026-05-22T10:10:00+09:00"),
        heartbeat_timeout=timedelta(minutes=5),
    )

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT id, status FROM jobs ORDER BY id",
        ).fetchall()

    assert stale_ids == ["job_stale"]
    assert rows == [("job_fresh", "running"), ("job_stale", "stale")]
