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
    assert response.json()["data"]["items"][0]["related_mail"] is None


def test_jobs_list_reports_related_mail_from_payload(
    client,
    database_path: Path,
) -> None:
    client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Job Mail Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "job.mail.sender@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_job_related_1",
            "gmail_thread_id": "thread_job_related",
            "subject": "Related job mail",
            "from_address": "job.mail.sender@example.com",
            "received_at": "2026-05-28T09:10:00+09:00",
            "body_text": "This message has a failed job.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed', error_type = 'WorkerError', error_message = 'boom'
            WHERE id = ?
            """,
            (job_id,),
        )
        connection.commit()

    response = client.get(f"{JOBS_URL}?status=failed")

    assert response.status_code == 200
    job = response.json()["data"]["items"][0]
    assert job["id"] == job_id
    assert job["related_mail"]["context_type"] == "message"
    assert job["related_mail"]["message_id"] == message_id
    assert job["related_mail"]["thread_id"].startswith("gmail_thread_")
    assert job["related_mail"]["gmail_message_id"] == "gmail_job_related_1"
    assert job["related_mail"]["gmail_thread_id"] == "thread_job_related"
    assert job["related_mail"]["subject"] == "Related job mail"
    assert job["related_mail"]["received_at"] == "2026-05-28T09:10:00+09:00"
    assert job["related_mail"]["from_address"] == "job.mail.sender@example.com"
    assert job["related_mail"]["mail_url"] == f"/mail/{message_id}"


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


def test_failed_job_can_be_discarded(client, database_path: Path) -> None:
    insert_phase_2_job(database_path, job_id="job_failed", status="failed")

    response = client.post(f"{JOBS_URL}/job_failed/discard")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "discarded"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, locked_by, finished_at FROM jobs WHERE id = ?",
            ("job_failed",),
        ).fetchone()

    assert row[0] == "discarded"
    assert row[1] is None
    assert row[2] is not None


def test_pending_job_is_not_discarded(client, database_path: Path) -> None:
    insert_phase_2_job(database_path, job_id="job_pending", status="pending")

    response = client.post(f"{JOBS_URL}/job_pending/discard")

    assert response.status_code == 409
    assert response.json()["ok"] is False


def test_run_next_job_reports_when_no_job_exists(client) -> None:
    response = client.post(f"{JOBS_URL}/run-next")

    assert response.status_code == 200
    assert response.json()["data"]["job_id"] is None
