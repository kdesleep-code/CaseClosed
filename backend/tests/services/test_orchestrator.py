from __future__ import annotations

import importlib
import sqlite3
from datetime import timedelta
from pathlib import Path

from caseclosed.db.runtime import parse_iso_datetime

from conftest import insert_phase_2_job


def test_orchestrator_runs_registered_job_handler(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_orchestrated",
        status="pending",
        job_type="test_job",
    )

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        handlers={"test_job": lambda job: {"handled_job_id": job.id}},
        worker_id="worker-orchestrator",
    )

    assert orchestrator.run_once() == "job_orchestrated"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, locked_by, result_json FROM jobs WHERE id = ?",
            ("job_orchestrated",),
        ).fetchone()

    assert row == (
        "succeeded",
        "worker-orchestrator",
        '{"handled_job_id": "job_orchestrated"}',
    )


def test_orchestrator_records_handler_failure(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_orchestrator_failure",
        status="pending",
        job_type="test_job",
    )

    def fail_handler(_job) -> dict[str, object]:
        raise RuntimeError("handler failed")

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        handlers={"test_job": fail_handler},
        worker_id="worker-orchestrator",
    )

    assert orchestrator.run_once() == "job_orchestrator_failure"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, error_type, error_message FROM jobs WHERE id = ?",
            ("job_orchestrator_failure",),
        ).fetchone()

    assert row == ("failed", "RuntimeError", "handler failed")


def test_orchestrator_checks_stale_jobs(client, database_path: Path) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_stale_by_orchestrator",
        status="running",
        job_type="test_job",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET heartbeat_at = ? WHERE id = ?",
            ("2026-05-22T10:00:00+09:00", "job_stale_by_orchestrator"),
        )
        connection.commit()

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator()

    stale_ids = orchestrator.mark_stale_jobs(
        now=parse_iso_datetime("2026-05-22T10:10:00+09:00"),
        heartbeat_timeout=timedelta(minutes=5),
    )

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE id = ?",
            ("job_stale_by_orchestrator",),
        ).fetchone()

    assert stale_ids == ["job_stale_by_orchestrator"]
    assert row == ("pending",)
