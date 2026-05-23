from __future__ import annotations

from pathlib import Path

import sqlite3

from conftest import insert_phase_2_job

JOBS_URL = "/api/v1/jobs"


def test_jobs_list_reports_phase_2_jobs(client, database_path: Path) -> None:
    insert_phase_2_job(database_path, job_id="job_failed", status="failed")
    insert_phase_2_job(database_path, job_id="job_pending", status="pending")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET error_type = ?, error_message = ?
            WHERE id = ?
            """,
            ("WorkerError", "Gmail request failed.", "job_failed"),
        )
        connection.commit()

    response = client.get(f"{JOBS_URL}?status=failed")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [job["id"] for job in response.json()["data"]["items"]] == [
        "job_failed"
    ]
    assert response.json()["data"]["items"][0]["error_type"] == "WorkerError"
    assert response.json()["data"]["items"][0]["error_message"] == (
        "Gmail request failed."
    )


def test_failed_job_can_be_manually_retried(client, database_path: Path) -> None:
    insert_phase_2_job(database_path, job_id="job_failed", status="failed")

    response = client.post(f"{JOBS_URL}/job_failed/retry")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, retry_count, locked_by FROM jobs WHERE id = ?",
            ("job_failed",),
        ).fetchone()

    assert row == ("pending", 1, None)


def test_pending_job_is_not_retried(client, database_path: Path) -> None:
    insert_phase_2_job(database_path, job_id="job_pending", status="pending")

    response = client.post(f"{JOBS_URL}/job_pending/retry")

    assert response.status_code == 409
    assert response.json()["ok"] is False


def test_run_next_job_reports_when_no_job_exists(client) -> None:
    response = client.post(f"{JOBS_URL}/run-next")

    assert response.status_code == 200
    assert response.json()["data"]["job_id"] is None
