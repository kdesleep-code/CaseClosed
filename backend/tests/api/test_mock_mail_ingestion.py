from __future__ import annotations

from pathlib import Path

import json
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


def test_mock_mail_ingestion_skips_subject_marked_spam_without_contact_pending(
    client,
    database_path: Path,
) -> None:
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_subject_spam_1",
            "gmail_thread_id": "thread_subject_spam",
            "subject": "[SPAM] Suspicious account notice",
            "from_address": "spoofed.support@example.com",
            "received_at": "2026-05-23T10:05:00+09:00",
            "body_text": "Suspicious content.",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending"] is False
    assert data["pending_address"] is None
    assert data["queued_job_id"] is None

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id,
                   llm_blocked
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (data["message_id"],),
        ).fetchone()
        email_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM contact_email_addresses
            WHERE normalized_email_address = 'spoofed.support@example.com'
            """
        ).fetchone()
        job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type IN ('mail_importance_classification', 'mail_summary')
            """
        ).fetchone()

    assert auto_row == (None, "skip", None, 0)
    assert email_count == (0,)
    assert job_count == (0,)


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
        contact_count = connection.execute(
            """
            SELECT inbound_message_count, latest_received_at
            FROM contacts
            WHERE display_name = 'Known Sender'
            """
        ).fetchone()

    assert email_row == ("linked", 1)
    assert auto_row == (None, "unclassified", None)
    assert "gmail_known_1" in job_payload[0]
    assert contact_count == (1, "2026-05-23T10:10:00+09:00")


def test_contact_inbound_stats_include_reply_to_messages(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Reply-To Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "reply.person@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Campus List",
            "status": "active",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "mailing_list_recipient_expression": "{faculty}",
            "email_addresses": [
                {"email_address": "campus-list@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_reply_to_stats_1",
            "gmail_thread_id": "thread_reply_to_stats",
            "subject": "Reply-To sender test",
            "from_address": "campus-list@example.com",
            "reply_to_address": "reply.person@example.com",
            "received_at": "2026-05-28T11:20:00+09:00",
        },
    )

    assert response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT display_name, inbound_message_count, latest_received_at
            FROM contacts
            WHERE display_name IN ('Reply-To Sender', 'Campus List')
            ORDER BY display_name
            """
        ).fetchall()

    assert rows == [
        ("Campus List", 1, "2026-05-28T11:20:00+09:00"),
        ("Reply-To Sender", 1, "2026-05-28T11:20:00+09:00"),
    ]


def test_known_person_mail_queues_weekly_contact_ai_memo_batch(
    client,
    database_path: Path,
) -> None:
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Recent Activity Sender",
            "status": "active",
            "ai_memo": "Earlier memo.",
            "email_addresses": [
                {"email_address": "activity.sender@example.com", "is_primary": True}
            ],
        },
    )
    contact_id = create_response.json()["data"]["id"]

    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_contact_ai_memo_1",
            "gmail_thread_id": "thread_contact_ai_memo",
            "subject": "Workshop coordination update",
            "from_address": "activity.sender@example.com",
            "received_at": "2026-05-26T12:00:00+09:00",
            "body_text": "They are coordinating the May workshop schedule.",
        },
    )

    assert ingest_response.status_code == 200
    first_job_id = ingest_response.json()["data"]["queued_contact_ai_memo_job_id"]
    assert first_job_id is not None

    second_ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_contact_ai_memo_2",
            "gmail_thread_id": "thread_contact_ai_memo_2",
            "subject": "Workshop speaker follow-up",
            "from_address": "activity.sender@example.com",
            "received_at": "2026-05-27T09:00:00+09:00",
            "body_text": "They are following up with workshop speakers.",
        },
    )
    assert second_ingest_response.status_code == 200
    assert second_ingest_response.json()["data"]["queued_contact_ai_memo_job_id"] == first_job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT id, status, payload_json, available_at
            FROM jobs
            WHERE job_type = 'contact_ai_memo_update'
            """
        ).fetchone()
        job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'contact_ai_memo_update'
            """
        ).fetchone()[0]

    assert job_row is not None
    assert job_row[0] == first_job_id
    assert job_row[1] == "pending"
    assert json.loads(job_row[2])["schedule_scope"] == "weekly_batch"
    assert job_row[3] is not None
    assert job_count == 1

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE jobs
            SET available_at = '2026-05-27T00:00:00+09:00'
            WHERE id = ?
            """,
            (first_job_id,),
        )

    for _ in range(5):
        run_response = client.post("/api/v1/jobs/run-next")
        assert run_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        ai_memo = connection.execute(
            "SELECT ai_memo FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()[0]
        llm_row = connection.execute(
            """
            SELECT function_type, input_source_json, input_diagnostic_json
            FROM llm_runs
            WHERE function_type = 'contact_ai_memo_update'
            """
        ).fetchone()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE id = ?",
            (first_job_id,),
        ).fetchone()[0]

    assert job_status == "succeeded"
    assert "Earlier memo." in ai_memo
    assert "Workshop coordination update" in ai_memo
    assert "Workshop speaker follow-up" in ai_memo
    assert llm_row[0] == "contact_ai_memo_update"
    assert json.loads(llm_row[1])["message_count"] == 2
    assert json.loads(llm_row[1])["schedule_scope"] == "weekly_batch"
    assert "body_text" not in llm_row[1]
    assert "body_text_length" in llm_row[2]


def test_active_person_without_ai_memo_gets_initial_memo_immediately(
    client,
    database_path: Path,
) -> None:
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Initial Memo Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "initial.memo@example.com", "is_primary": True}
            ],
        },
    )
    contact_id = create_response.json()["data"]["id"]

    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_initial_active_memo",
            "gmail_thread_id": "thread_initial_active_memo",
            "subject": "Initial collaboration context",
            "from_address": "initial.memo@example.com",
            "received_at": "2026-05-27T10:00:00+09:00",
            "body_text": "They are planning a new collaboration meeting.",
        },
    )

    assert ingest_response.status_code == 200
    job_id = ingest_response.json()["data"]["queued_contact_ai_memo_job_id"]
    assert job_id is not None

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT payload_json, available_at
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

    assert json.loads(job_row[0])["schedule_scope"] == "single_message"
    assert job_row[1] is None

    for _ in range(8):
        run_response = client.post("/api/v1/jobs/run-next")
        assert run_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        ai_memo = connection.execute(
            "SELECT ai_memo FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()[0]
        llm_source = connection.execute(
            """
            SELECT input_source_json
            FROM llm_runs
            WHERE function_type = 'contact_ai_memo_update'
            """
        ).fetchone()[0]

    assert "Initial collaboration context" in ai_memo
    assert json.loads(llm_source)["schedule_scope"] == "single_message"


def test_pending_contact_archived_creation_gets_one_initial_ai_memo(
    client,
    database_path: Path,
) -> None:
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_archived_pending_memo",
            "gmail_thread_id": "thread_archived_pending_memo",
            "subject": "One time archive context",
            "from_address": "archive.pending@example.com",
            "from_name": "Archive Pending",
            "received_at": "2026-05-27T12:00:00+09:00",
            "body_text": "This mail explains who this archived contact was.",
        },
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["data"]["pending"] is True

    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Archive Pending",
            "status": "archived",
            "kind": "person",
            "email_addresses": [
                {"email_address": "archive.pending@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200
    contact_id = create_response.json()["data"]["id"]

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT id, status, payload_json
            FROM jobs
            WHERE job_type = 'contact_ai_memo_update'
            """
        ).fetchone()

    assert job_row is not None
    assert job_row[1] == "pending"
    assert json.loads(job_row[2])["allow_archived_initial"] is True

    for _ in range(3):
        run_response = client.post("/api/v1/jobs/run-next")
        assert run_response.status_code == 200

    with sqlite3.connect(database_path) as connection:
        contact_row = connection.execute(
            "SELECT status, ai_memo FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()

    assert contact_row[0] == "archived"
    assert "One time archive context" in contact_row[1]


def test_mock_sent_mail_does_not_queue_importance_or_pending_contact(
    client,
    database_path: Path,
) -> None:
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_sent_1",
            "gmail_thread_id": "thread_sent",
            "subject": "Sent mail test",
            "from_address": "me@example.com",
            "to_addresses": ["known.sender@example.com"],
            "gmail_labels": ["SENT"],
            "received_at": "2026-05-23T10:15:00+09:00",
            "body_text": "This is an outgoing mail.",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending"] is False
    assert data["pending_address"] is None
    assert data["queued_job_id"] is None

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id
            FROM mail_auto_state
            """
        ).fetchone()
        user_row = connection.execute(
            """
            SELECT processed_status, read_status
            FROM mail_user_state
            """
        ).fetchone()
        job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()
        own_address = connection.execute(
            """
            SELECT COUNT(*)
            FROM contact_email_addresses
            WHERE normalized_email_address = 'me@example.com'
            """
        ).fetchone()

    assert auto_row == (None, "sent", None)
    assert user_row == ("processed", "read")
    assert job_count == (0,)
    assert own_address == (0,)


def test_contact_fixed_pinned_rule_skips_importance_and_summary_jobs(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Always Pinned Sender",
            "status": "active",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "pinned",
            "email_addresses": [
                {"email_address": "always.pinned@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_fixed_pinned",
            "gmail_thread_id": "thread_fixed_pinned",
            "subject": "Routine from important contact",
            "from_address": "always.pinned@example.com",
            "received_at": "2026-05-24T09:00:00+09:00",
            "body_text": "This should not need importance LLM classification.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    with sqlite3.connect(database_path) as connection:
        auto_state = connection.execute(
            """
            SELECT effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        jobs = connection.execute(
            """
            SELECT job_type
            FROM jobs
            ORDER BY job_type
            """
        ).fetchall()

    assert auto_state[0] == "pinned"
    assert ("mail_importance_classification",) not in jobs
    assert ("mail_summary",) not in jobs


def test_spam_person_contact_routes_mail_to_skip_without_jobs(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Spam Person",
            "status": "spam",
            "email_addresses": [
                {"email_address": "spam.person@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_spam_person",
            "gmail_thread_id": "thread_spam_person",
            "subject": "Suspicious person mail",
            "from_address": "spam.person@example.com",
            "received_at": "2026-05-24T09:05:00+09:00",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        auto_state = connection.execute(
            """
            SELECT pending_reason, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (response.json()["data"]["message_id"],),
        ).fetchone()
        jobs = connection.execute("SELECT job_type FROM jobs").fetchall()

    assert auto_state == (None, "skip")
    assert jobs == []


def test_spam_reply_to_contact_routes_mail_to_skip_without_from_pending(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Spam Reply Target",
            "status": "spam",
            "email_addresses": [
                {"email_address": "spam.reply@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_spam_reply_to",
            "gmail_thread_id": "thread_spam_reply_to",
            "subject": "Suspicious reply-to mail",
            "from_address": "unknown.sender@example.com",
            "reply_to_address": "spam.reply@example.com",
            "received_at": "2026-05-24T09:05:30+09:00",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        auto_state = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (response.json()["data"]["message_id"],),
        ).fetchone()
        jobs = connection.execute("SELECT job_type FROM jobs").fetchall()

    assert auto_state == (None, "skip", None)
    assert jobs == []


def test_skipped_mailing_list_routes_mail_to_skip_without_reply_to_resolution(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Skipped ML",
            "status": "skipped",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "skipped-list@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_skipped_ml",
            "gmail_thread_id": "thread_skipped_ml",
            "subject": "Skipped list mail",
            "from_address": "skipped-list@example.com",
            "reply_to_address": "real.sender@example.com",
            "received_at": "2026-05-24T09:06:00+09:00",
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        auto_state = connection.execute(
            """
            SELECT pending_reason, effective_importance, pending_from_address_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (response.json()["data"]["message_id"],),
        ).fetchone()
        reply_to_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM contact_email_addresses
            WHERE normalized_email_address = 'real.sender@example.com'
            """
        ).fetchone()

    assert auto_state == (None, "skip", None)
    assert reply_to_count == (0,)


def test_contact_instruction_rule_is_passed_to_importance_job(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Instruction Sender",
            "status": "active",
            "mail_importance_rule_action": "llm_with_instruction",
            "mail_importance_rule_instruction": "常にHigh寄りに判断する。",
            "email_addresses": [
                {"email_address": "instruction.sender@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_instruction_rule",
            "gmail_thread_id": "thread_instruction_rule",
            "subject": "Routine instruction target",
            "from_address": "instruction.sender@example.com",
            "received_at": "2026-05-24T09:10:00+09:00",
            "body_text": "Routine note.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT job_type, payload_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert job_row[0] == "mail_importance_classification"
    assert message_id in job_row[1]
    assert "High" in job_row[1]


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


def test_thread_future_low_rule_skips_llm_and_manual_message_importance_wins(
    client,
    database_path,
) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Thread Rule Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "thread.rule@example.com", "is_primary": True}
            ],
        },
    )
    assert contact_response.status_code == 200
    first_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_thread_rule_1",
            "gmail_thread_id": "thread_future_low",
            "subject": "Thread rule",
            "from_address": "thread.rule@example.com",
            "received_at": "2026-07-14T09:00:00+09:00",
            "body_text": "First message.",
        },
    )
    first_id = first_response.json()["data"]["message_id"]
    first_job_id = first_response.json()["data"]["queued_job_id"]
    rule_response = client.patch(
        f"/api/v1/mails/{first_id}/thread-importance-rule",
        json={"future_importance_rule": "low"},
    )
    assert rule_response.status_code == 200
    assert rule_response.json()["data"]["future_importance_rule"] == "low"

    second_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_thread_rule_2",
            "gmail_thread_id": "thread_future_low",
            "subject": "Thread rule follow-up",
            "from_address": "thread.rule@example.com",
            "received_at": "2026-07-14T10:00:00+09:00",
            "body_text": "Second message.",
        },
    )
    second_id = second_response.json()["data"]["message_id"]
    assert second_response.json()["data"]["queued_job_id"] is None

    from caseclosed.services.orchestrator import Orchestrator

    assert Orchestrator(worker_id="thread-rule-worker").run_once() == first_job_id
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT message_id, effective_importance, llm_run_id "
            "FROM mail_auto_state WHERE message_id IN (?, ?) ORDER BY message_id",
            (first_id, second_id),
        ).fetchall()
    assert {row[0]: row[1:] for row in rows} == {
        first_id: ("low", None),
        second_id: ("low", None),
    }

    manual_response = client.post(
        f"/api/v1/mails/{second_id}/importance",
        json={"importance": "high"},
    )
    assert manual_response.status_code == 200
    assert manual_response.json()["data"]["message"]["effective_importance"] == "high"

    disable_response = client.patch(
        f"/api/v1/mails/{second_id}/thread-importance-rule",
        json={"future_importance_rule": None},
    )
    assert disable_response.status_code == 200
    third_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_thread_rule_3",
            "gmail_thread_id": "thread_future_low",
            "subject": "Automatic again",
            "from_address": "thread.rule@example.com",
            "received_at": "2026-07-14T11:00:00+09:00",
            "body_text": "Third message.",
        },
    )
    assert third_response.json()["data"]["queued_job_id"] is not None
