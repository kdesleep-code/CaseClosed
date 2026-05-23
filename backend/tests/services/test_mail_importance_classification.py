from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"


def test_mock_mail_importance_classification_marks_high_mail(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.high@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_high_1",
            "gmail_thread_id": "thread_high",
            "subject": "URGENT: response needed",
            "from_address": "known.high@example.com",
            "received_at": "2026-05-23T12:00:00+09:00",
            "body_text": "Please respond today.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            "SELECT status, result_json FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT provider_name, model_name, input_source_json, output_json, status
            FROM llm_runs
            WHERE function_type = 'mail_importance_classification'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT suggested_importance, effective_importance, llm_run_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert job_row[0] == "succeeded"
    result = json.loads(job_row[1])
    assert result["message_id"] == message_id
    assert result["suggested_importance"] == "high"
    assert result["provider"] == "mock"
    assert result["llm_run_id"].startswith("llm_run_")
    assert llm_run_row[0:2] == ("mock", "deterministic-mail-importance-v1")
    assert json.loads(llm_run_row[2]) == {
        "gmail_message_id": "gmail_high_1",
        "message_id": message_id,
        "subject": "URGENT: response needed",
    }
    assert "Please respond today." not in llm_run_row[2]
    assert json.loads(llm_run_row[3])["importance"] == "high"
    assert llm_run_row[4] == "succeeded"
    assert auto_row[0:2] == ("high", "high")
    assert auto_row[2] == result["llm_run_id"]

    list_response = client.get("/api/v1/mails")
    mail_item = list_response.json()["data"]["items"][0]
    assert mail_item["id"] == message_id
    assert mail_item["effective_importance"] == "high"
    assert mail_item["pending_reason"] is None


def test_mock_mail_importance_classification_keeps_external_star_high(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.star@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_star_1",
            "gmail_thread_id": "thread_star",
            "subject": "routine FYI",
            "from_address": "known.star@example.com",
            "received_at": "2026-05-23T12:10:00+09:00",
            "external_starred": True,
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT external_importance, suggested_importance, effective_importance,
                   llm_run_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert auto_row[0:3] == ("high", "low", "high")
    assert auto_row[3].startswith("llm_run_")
