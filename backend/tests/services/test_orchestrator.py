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


def test_orchestrator_retries_transient_openai_provider_error(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_orchestrator_openai_retry",
        status="pending",
        job_type="test_job",
    )

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    llm_provider_module = importlib.import_module("caseclosed.services.llm_provider")

    def fail_handler(_job) -> dict[str, object]:
        raise llm_provider_module.OpenAIProviderError(
            "OpenAI API request failed: <urlopen error [Errno 11001] getaddrinfo failed>"
        )

    orchestrator = orchestrator_module.Orchestrator(
        handlers={"test_job": fail_handler},
        worker_id="worker-orchestrator",
    )

    assert orchestrator.run_once() == "job_orchestrator_openai_retry"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, error_type, error_message, retry_count, available_at,
                   locked_by, started_at, finished_at
            FROM jobs
            WHERE id = ?
            """,
            ("job_orchestrator_openai_retry",),
        ).fetchone()

    assert row[0:4] == (
        "pending",
        "OpenAIProviderError",
        "OpenAI API request failed: <urlopen error [Errno 11001] getaddrinfo failed>",
        1,
    )
    assert row[4].endswith("+09:00")
    assert row[5:] == (None, None, None)


def test_orchestrator_fails_non_transient_openai_provider_error(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_orchestrator_openai_non_transient",
        status="pending",
        job_type="test_job",
    )

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    llm_provider_module = importlib.import_module("caseclosed.services.llm_provider")

    def fail_handler(_job) -> dict[str, object]:
        raise llm_provider_module.OpenAIProviderError("OpenAI response JSON was not an object.")

    orchestrator = orchestrator_module.Orchestrator(
        handlers={"test_job": fail_handler},
        worker_id="worker-orchestrator",
    )

    assert orchestrator.run_once() == "job_orchestrator_openai_non_transient"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, error_type, error_message, retry_count FROM jobs WHERE id = ?",
            ("job_orchestrator_openai_non_transient",),
        ).fetchone()

    assert row == (
        "failed",
        "OpenAIProviderError",
        "OpenAI response JSON was not an object.",
        0,
    )


def test_orchestrator_stops_retrying_transient_openai_provider_error_at_limit(
    client,
    database_path: Path,
) -> None:
    del client
    insert_phase_2_job(
        database_path,
        job_id="job_orchestrator_openai_retry_limit",
        status="pending",
        job_type="test_job",
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET retry_count = 3, max_retries = 3 WHERE id = ?",
            ("job_orchestrator_openai_retry_limit",),
        )
        connection.commit()

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    llm_provider_module = importlib.import_module("caseclosed.services.llm_provider")

    def fail_handler(_job) -> dict[str, object]:
        raise llm_provider_module.OpenAIProviderError("OpenAI API request failed: timed out")

    orchestrator = orchestrator_module.Orchestrator(
        handlers={"test_job": fail_handler},
        worker_id="worker-orchestrator",
    )

    assert orchestrator.run_once() == "job_orchestrator_openai_retry_limit"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, error_type, error_message, retry_count FROM jobs WHERE id = ?",
            ("job_orchestrator_openai_retry_limit",),
        ).fetchone()

    assert row == ("failed", "OpenAIProviderError", "OpenAI API request failed: timed out", 3)


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
