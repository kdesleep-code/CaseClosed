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
                   suggested_tags_json, confidence, status
            FROM contact_registration_suggestions
            WHERE email_address_id = ?
            """,
            ("email_unknown_sender",),
        ).fetchone()

    assert job_row[0] == "succeeded"
    assert json.loads(job_row[1])["suggestion_id"].startswith("contact_suggestion_")
    assert suggestion_row == (
        "email_unknown_sender",
        "mail_dummy",
        "Unknown Sender",
        '["unknown-domain"]',
        0.5,
        "suggested",
    )

    list_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")
    item = list_response.json()["data"]["items"][0]
    assert item["suggestion_status"] == "succeeded"
    assert item["suggestion"]["suggested_display_name"] == "Unknown Sender"


def test_linking_unresolved_contact_email_enqueues_followup_job(
    client,
    database_path: Path,
) -> None:
    insert_unresolved_contact_email(
        database_path,
        email_address="pending.sender@example.com",
        email_address_id="email_pending_sender",
    )
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
        row = connection.execute(
            """
            SELECT job_type, status, payload_json
            FROM jobs
            WHERE job_type = 'contact_resolution_followup'
            """
        ).fetchone()

    assert row[0] == "contact_resolution_followup"
    assert row[1] == "pending"
    payload = json.loads(row[2])
    assert payload == {
        "contact_id": contact_id,
        "email_address_id": "email_pending_sender",
        "email_address": "Pending.Sender@Example.com",
        "normalized_email_address": "pending.sender@example.com",
        "reason": "unresolved_contact_linked",
    }
