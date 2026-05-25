from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

from conftest import insert_unresolved_contact_email

CONTACTS_URL = "/api/v1/contacts"


def test_contact_registration_prefill_job_creates_suggestion(
    client,
    database_path: Path,
) -> None:
    insert_unresolved_contact_email(
        database_path,
        email_address="unknown.sender@example.com",
        email_address_id="email_unknown_sender",
    )
    response = client.post(
        f"{CONTACTS_URL}/unresolved-from-addresses/unknown.sender%40example.com/generate-prefill",
        json={"message_id": "mail_dummy"},
    )
    job_id = response.json()["data"]["job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-contact-prefill",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            "SELECT status, result_json FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        suggestion_row = connection.execute(
            """
            SELECT email_address_id, source_message_id, suggested_display_name,
                   suggested_tags_json, confidence, status, llm_run_id
            FROM contact_registration_suggestions
            WHERE email_address_id = ?
            """,
            ("email_unknown_sender",),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT provider_name, model_name, input_source_json, output_json, status
            FROM llm_runs
            WHERE function_type = 'contact_registration_prefill'
            """
        ).fetchone()

    assert job_row[0] == "succeeded"
    result = json.loads(job_row[1])
    assert result["suggestion_id"].startswith("contact_suggestion_")
    assert result["provider"] == "mock"
    assert result["llm_run_id"].startswith("llm_run_")
    assert suggestion_row[0:6] == (
        "email_unknown_sender",
        "mail_dummy",
        "Unknown Sender",
        '["unknown-domain"]',
        0.5,
        "suggested",
    )
    assert suggestion_row[6] == result["llm_run_id"]
    assert llm_run_row[0:2] == ("mock", "deterministic-contact-prefill-v1")
    assert json.loads(llm_run_row[2]) == {
        "email_address": "unknown.sender@example.com",
        "email_address_id": "email_unknown_sender",
        "message_id": "mail_dummy",
    }
    assert json.loads(llm_run_row[3])["suggested_display_name"] == "Unknown Sender"
    assert llm_run_row[4] == "succeeded"

    list_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")
    item = list_response.json()["data"]["items"][0]
    assert item["suggestion_status"] == "succeeded"
    assert item["suggestion"]["suggested_display_name"] == "Unknown Sender"


def test_contact_registration_prefill_does_not_store_mail_body_in_llm_run(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_prefill_body_1",
            "gmail_thread_id": "thread_prefill_body",
            "subject": "Prefill source",
            "from_address": "body.prefill@example.com",
            "received_at": "2026-05-23T13:30:00+09:00",
            "body_text": "Sensitive body text must stay out of llm_runs input source.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    response = client.post(
        f"{CONTACTS_URL}/unresolved-from-addresses/body.prefill%40example.com/generate-prefill",
        json={"message_id": message_id},
    )
    job_id = response.json()["data"]["job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-contact-prefill",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        input_source = connection.execute(
            """
            SELECT input_source_json
            FROM llm_runs
            WHERE function_type = 'contact_registration_prefill'
            """
        ).fetchone()[0]

    assert message_id in input_source
    assert "Sensitive body text" not in input_source


def test_linking_unresolved_contact_email_releases_pending_mail(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_link_release_1",
            "gmail_thread_id": "thread_link_release",
            "subject": "Link release test",
            "from_address": "pending.sender@example.com",
            "received_at": "2026-05-23T10:50:00+09:00",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    contact_id = client.post(
        CONTACTS_URL,
        json={"display_name": "Pending Sender", "status": "active"},
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{contact_id}/email-addresses",
        json={"email_address": "Pending.Sender@Example.com", "is_primary": True},
    )

    assert response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        followup_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'contact_resolution_followup'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT pending_reason, pending_from_address_id, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        importance_job = connection.execute(
            """
            SELECT status, payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert contact_id is not None
    assert followup_count == (0,)
    assert auto_row == (None, None, "unclassified")
    assert importance_job[0] == "pending"
    assert message_id in importance_job[1]


def test_contact_creation_releases_pending_mail(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_followup_1",
            "gmail_thread_id": "thread_followup",
            "subject": "Followup test",
            "from_address": "followup.sender@example.com",
            "received_at": "2026-05-23T11:00:00+09:00",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Followup Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "followup.sender@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, pending_from_address_id, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        importance_job = connection.execute(
            """
            SELECT status, payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()
        followup_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'contact_resolution_followup'
            """
        ).fetchone()

    assert contact_id is not None
    assert followup_count == (0,)
    assert auto_row == (None, None, "unclassified")
    assert importance_job[0] == "pending"
    assert message_id in importance_job[1]


def test_contact_creation_releases_pending_mail_from_display_address(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_followup_display_1",
            "gmail_thread_id": "thread_followup_display",
            "subject": "Display address followup test",
            "from_address": "Display Sender <display.sender@example.com>",
            "received_at": "2026-05-23T11:05:00+09:00",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]

    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Display Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "display.sender@example.com", "is_primary": True}
            ],
        },
    )

    assert create_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, pending_from_address_id, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        email_rows = connection.execute(
            """
            SELECT normalized_email_address, resolution_status, contact_id
            FROM contact_email_addresses
            WHERE normalized_email_address = 'display.sender@example.com'
            """
        ).fetchall()
        importance_job = connection.execute(
            """
            SELECT status, payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert auto_row == (None, None, "unclassified")
    assert len(email_rows) == 1
    assert email_rows[0][1] == "linked"
    assert email_rows[0][2] == create_response.json()["data"]["id"]
    assert importance_job[0] == "pending"
    assert message_id in importance_job[1]


def test_contact_creation_releases_pending_mail_even_if_address_was_prelinked(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_followup_prelinked_1",
            "gmail_thread_id": "thread_followup_prelinked",
            "subject": "Prelinked stale pending test",
            "from_address": "prelinked.pending@example.com",
            "received_at": "2026-05-23T11:07:00+09:00",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contact_email_addresses
            SET resolution_status = 'linked'
            WHERE normalized_email_address = 'prelinked.pending@example.com'
            """
        )
        connection.commit()

    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Prelinked Pending",
            "status": "active",
            "email_addresses": [
                {"email_address": "prelinked.pending@example.com", "is_primary": True}
            ],
        },
    )

    assert create_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, pending_from_address_id, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        importance_job = connection.execute(
            """
            SELECT status, payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert auto_row == (None, None, "unclassified")
    assert importance_job[0] == "pending"
    assert message_id in importance_job[1]


def test_released_pending_mail_keeps_email_contact_after_merge(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_followup_merged_1",
            "gmail_thread_id": "thread_followup_merged",
            "subject": "Followup merge test",
            "from_address": "followup.merged@example.com",
            "received_at": "2026-05-23T11:10:00+09:00",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    source_contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Merged Source",
            "status": "active",
            "email_addresses": [
                {"email_address": "followup.merged@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]
    target_contact_id = client.post(
        CONTACTS_URL,
        json={"display_name": "Merged Target", "status": "active"},
    ).json()["data"]["id"]

    merge_response = client.post(
        f"{CONTACTS_URL}/{source_contact_id}/merge",
        json={"target_contact_id": target_contact_id},
    )
    assert merge_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, pending_from_address_id, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        email_contact_row = connection.execute(
            """
            SELECT contact_id
            FROM contact_email_addresses
            WHERE normalized_email_address = 'followup.merged@example.com'
            """
        ).fetchone()
        followup_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'contact_resolution_followup'
            """
        ).fetchone()

    assert followup_count == (0,)
    assert auto_row == (None, None, "unclassified")
    assert email_contact_row == (target_contact_id,)


def test_mock_mail_to_prefilled_contact_to_classified_mail_pipeline(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_pipeline_1",
            "gmail_thread_id": "thread_pipeline",
            "subject": "Urgent pipeline review",
            "from_address": "pipeline.review@example.com",
            "received_at": "2026-05-23T12:00:00+09:00",
            "body_text": "Please review this today.",
        },
    )
    assert ingest_response.status_code == 200
    message_id = ingest_response.json()["data"]["message_id"]

    pending_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")
    assert pending_response.status_code == 200
    pending_item = pending_response.json()["data"]["items"][0]
    assert pending_item["email_address"] == "pipeline.review@example.com"
    assert pending_item["latest_message_id"] == message_id

    prefill_response = client.post(
        (
            f"{CONTACTS_URL}/unresolved-from-addresses/"
            "pipeline.review%40example.com/generate-prefill"
        ),
        json={"message_id": message_id},
    )
    prefill_job_id = prefill_response.json()["data"]["job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-phase-4-pipeline",
    )
    assert orchestrator.run_once() == prefill_job_id

    suggested_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")
    suggested_item = suggested_response.json()["data"]["items"][0]
    assert suggested_item["suggestion_status"] == "succeeded"
    suggestion = suggested_item["suggestion"]
    assert suggestion["suggested_display_name"] == "Pipeline Review"

    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": suggestion["suggested_display_name"],
            "status": "active",
            "tags": suggestion["suggested_tags"],
            "source_suggestion_id": suggestion["id"],
            "email_addresses": [
                {"email_address": "pipeline.review@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200

    classification_job_id = orchestrator.run_once()
    assert classification_job_id is not None

    mail_response = client.get(f"/api/v1/mails/{message_id}")
    assert mail_response.status_code == 200
    auto_state = mail_response.json()["data"]["auto_state"]
    assert auto_state["pending_reason"] is None
    assert auto_state["effective_importance"] == "high"
    assert auto_state["suggested_importance"] == "high"
    assert auto_state["llm_run_id"] is not None

    with sqlite3.connect(database_path) as connection:
        suggestion_row = connection.execute(
            """
            SELECT status
            FROM contact_registration_suggestions
            WHERE id = ?
            """,
            (suggestion["id"],),
        ).fetchone()
        job_rows = connection.execute(
            """
            SELECT job_type, status
            FROM jobs
            WHERE id = ?
            ORDER BY job_type
            """,
            (classification_job_id,),
        ).fetchall()

    assert suggestion_row == ("adopted",)
    assert job_rows == [
        ("mail_importance_classification", "succeeded"),
    ]
