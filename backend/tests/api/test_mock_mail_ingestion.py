from __future__ import annotations

from pathlib import Path

import sqlite3

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"


def test_mock_mail_ingestion_marks_unknown_from_as_pending(
    client,
    database_path: Path,
) -> None:
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_unknown_1",
            "gmail_thread_id": "thread_unknown",
            "message_id_header": "<unknown-1@example.com>",
            "subject": "Unknown sender test",
            "from_address": "unknown.sender@example.com",
            "received_at": "2026-05-23T10:00:00+09:00",
            "body_text": "Hello from an unknown sender.",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending"] is True
    assert data["pending_address"] == "unknown.sender@example.com"
    assert data["queued_job_id"] is None

    with sqlite3.connect(database_path) as connection:
        email_row = connection.execute(
            """
            SELECT resolution_status, has_inbound_message_history
            FROM contact_email_addresses
            WHERE normalized_email_address = 'unknown.sender@example.com'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id
            FROM mail_auto_state
            """
        ).fetchone()
        job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert email_row == ("unresolved", 1)
    assert auto_row[0] == "unresolved_from_contact"
    assert auto_row[1] == "pending"
    assert auto_row[2] is not None
    assert job_count == (0,)

    pending_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")

    assert pending_response.status_code == 200
    pending_item = pending_response.json()["data"]["items"][0]
    assert pending_item["email_address"] == "unknown.sender@example.com"
    assert pending_item["message_count"] == 1
    assert pending_item["latest_message_id"] == data["message_id"]
    assert pending_item["latest_subject"] == "Unknown sender test"
    assert pending_item["inferred_kind"] == "person"
    assert pending_item["inferred_sender_resolution"] == "self"


def test_mock_mail_ingestion_queues_importance_job_for_known_person(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.sender@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_known_1",
            "gmail_thread_id": "thread_known",
            "subject": "Known sender test",
            "from_address": "known.sender@example.com",
            "received_at": "2026-05-23T10:10:00+09:00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending"] is False
    assert data["pending_address"] is None
    assert data["queued_job_id"] is not None

    with sqlite3.connect(database_path) as connection:
        email_row = connection.execute(
            """
            SELECT resolution_status, has_inbound_message_history
            FROM contact_email_addresses
            WHERE normalized_email_address = 'known.sender@example.com'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id
            FROM mail_auto_state
            """
        ).fetchone()
        job_payload = connection.execute(
            """
            SELECT payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert email_row == ("linked", 1)
    assert auto_row == (None, "unclassified", None)
    assert "gmail_known_1" in job_payload[0]


def test_mock_mail_ingestion_uses_reply_to_for_reply_to_mailing_list(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Committee ML",
            "status": "active",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "committee-list@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_ml_reply_to_1",
            "gmail_thread_id": "thread_ml",
            "subject": "ML reply-to test",
            "from_address": "committee-list@example.com",
            "reply_to_address": "real.sender@example.com",
            "list_id": "committee.example.com",
            "received_at": "2026-05-23T10:20:00+09:00",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending"] is True
    assert data["pending_address"] == "real.sender@example.com"

    with sqlite3.connect(database_path) as connection:
        from_history = connection.execute(
            """
            SELECT has_inbound_message_history
            FROM contact_email_addresses
            WHERE normalized_email_address = 'committee-list@example.com'
            """
        ).fetchone()
        reply_to_row = connection.execute(
            """
            SELECT resolution_status, has_inbound_message_history
            FROM contact_email_addresses
            WHERE normalized_email_address = 'real.sender@example.com'
            """
        ).fetchone()
        pending_row = connection.execute(
            """
            SELECT cea.normalized_email_address
            FROM mail_auto_state mas
            JOIN contact_email_addresses cea
              ON cea.id = mas.pending_from_address_id
            """
        ).fetchone()

    assert from_history == (1,)
    assert reply_to_row == ("unresolved", 1)
    assert pending_row == ("real.sender@example.com",)

    pending_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")

    assert pending_response.status_code == 200
    pending_item = pending_response.json()["data"]["items"][0]
    assert pending_item["email_address"] == "real.sender@example.com"
    assert pending_item["message_count"] == 1
    assert pending_item["latest_message_id"] == data["message_id"]
    assert pending_item["latest_subject"] == "ML reply-to test"
    assert pending_item["inferred_display_name"] == "Real Sender"
    assert pending_item["inferred_kind"] == "person"
    assert pending_item["inferred_sender_resolution"] == "self"
