from __future__ import annotations

import base64
from email import message_from_bytes
import sqlite3
import json

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"
MAILS_URL = "/api/v1/mails"
MAIL_DRAFTS_URL = "/api/v1/mail-drafts"


def ingest_mail(
    client,
    *,
    gmail_message_id: str,
    gmail_thread_id: str,
    from_address: str,
    subject: str,
    received_at: str,
    body_text: str = "",
) -> str:
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "message_id_header": f"<{gmail_message_id}@example.com>",
            "subject": subject,
            "from_address": from_address,
            "received_at": received_at,
            "body_text": body_text,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["message_id"]


def create_known_sender_mail(client, *, subject: str, body_text: str = "") -> str:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Mail Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "mail.sender@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Recipient",
            "avatar_url": "https://example.com/recipient.png",
            "status": "active",
            "email_addresses": [
                {"email_address": "user@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mail_api_1",
            "gmail_thread_id": "thread_mail_api",
            "message_id_header": "<mail-api-1@example.com>",
            "subject": subject,
            "from_address": "mail.sender@example.com",
            "reply_to_address": "reply@example.com",
            "to_addresses": ["user@example.com"],
            "received_at": "2026-05-23T13:00:00+09:00",
            "body_text": body_text,
        },
    )
    return response.json()["data"]["message_id"]


def insert_received_attachment(
    database_path,
    *,
    attachment_id: str,
    message_id: str,
    gmail_message_id: str,
    gmail_attachment_id: str,
    filename: str = "note.pdf",
    mime_type: str = "application/pdf",
    byte_size: int = 123,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO gmail_message_attachments (
                id, message_id, gmail_message_id, gmail_attachment_id,
                part_id, filename, mime_type, byte_size, storage_object_id,
                created_at, updated_at, version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
            """,
            (
                attachment_id,
                message_id,
                gmail_message_id,
                gmail_attachment_id,
                "1",
                filename,
                mime_type,
                byte_size,
                "2026-05-28T12:00:00+09:00",
                "2026-05-28T12:00:00+09:00",
            ),
        )
        connection.commit()


def connect_gmail_send(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()


def patch_gmail_send_response(
    monkeypatch,
    *,
    gmail_message_id: str,
    gmail_thread_id: str,
    subject: str,
    body_text: str,
    to_address: str,
    cc_address: str | None = None,
    in_reply_to: str | None = None,
) -> list[bytes]:
    sent_raw_messages: list[bytes] = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        sent_raw_messages.append(raw_message)
        return {"id": gmail_message_id, "threadId": thread_id or gmail_thread_id}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == f"/users/me/messages/{gmail_message_id}":
            headers = [
                {"name": "From", "value": "me@example.com"},
                {"name": "To", "value": to_address},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{gmail_message_id}@example.com>"},
            ]
            if cc_address is not None:
                headers.append({"name": "Cc", "value": cc_address})
            if in_reply_to is not None:
                headers.append({"name": "In-Reply-To", "value": in_reply_to})
            return {
                "id": gmail_message_id,
                "threadId": gmail_thread_id,
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "snippet": body_text,
                "payload": {
                    "mimeType": "text/plain",
                    "headers": headers,
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            body_text.encode("utf-8")
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )
    return sent_raw_messages


def test_mail_detail_returns_message_state_and_available_actions(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Detail API test",
        body_text="This body is stored for detail view.",
    )

    response = client.get(f"{MAILS_URL}/{message_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"]["id"] == message_id
    assert data["message"]["subject"] == "Detail API test"
    assert data["message"]["body_text"] == "This body is stored for detail view."
    assert data["message"]["message_id_header"] == "<mail-api-1@example.com>"
    assert data["message"]["from_contact"]["display_name"] == "Mail Sender"
    assert data["message"]["sender_contact"]["display_name"] == "Mail Sender"
    assert data["message"]["to_addresses"] == ["user@example.com"]
    assert data["message"]["to_recipients"] == [
        {
            "email_address": "user@example.com",
            "contact": {
                "id": data["message"]["to_recipients"][0]["contact"]["id"],
                "display_name": "Known Recipient",
                "avatar_url": "https://example.com/recipient.png",
                "kind": "person",
                "status": "active",
                "tags": [],
            },
        }
    ]
    assert data["message"]["cc_recipients"] == []
    assert data["user_state"]["processed_status"] == "unprocessed"
    assert data["user_state"]["read_status"] == "unread"
    assert data["auto_state"]["effective_importance"] == "unclassified"
    assert data["thread_messages"][0]["id"] == message_id
    assert data["thread_messages"][0]["body_text"] == "This body is stored for detail view."
    assert data["thread_messages"][0]["effective_importance"] == "unclassified"
    assert data["thread_messages"][0]["processed_status"] == "unprocessed"
    assert "process" in data["available_actions"]
    assert "set_importance" in data["available_actions"]


def test_mail_detail_and_list_report_received_attachments(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment detail",
        body_text="Please see the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_detail",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_detail",
        filename="review-note.pdf",
        byte_size=2048,
    )

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    list_response = client.get(f"{MAILS_URL}?tab=unprocessed&limit=20")

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["message"]["has_attachments"] is True
    assert detail["message"]["attachment_count"] == 1
    assert detail["message"]["attachments"][0]["filename"] == "review-note.pdf"
    assert detail["message"]["attachments"][0]["download_url"].endswith(
        "/api/v1/mails/attachments/mail_attachment_detail/download"
    )
    assert detail["attachments"] == detail["message"]["attachments"]
    assert list_response.status_code == 200
    item = next(
        item for item in list_response.json()["data"]["items"] if item["id"] == message_id
    )
    assert item["has_attachments"] is True
    assert item["attachment_count"] == 1


def test_mail_attachment_download_caches_gmail_data(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment download",
        body_text="Please download the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_download",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_download",
        filename="review-note.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)
    calls: list[str] = []

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        calls.append(path)
        assert path == "/users/me/messages/gmail_mail_api_1/attachments/gmail_attach_download"
        return {
            "data": base64.urlsafe_b64encode(b"hello attachment")
            .decode("ascii")
            .rstrip("="),
            "size": 16,
        }

    from caseclosed import google_integration

    monkeypatch.setattr(google_integration, "gmail_api_get_json", fake_gmail_api_get_json)

    first_response = client.get(
        f"{MAILS_URL}/attachments/mail_attachment_download/download"
    )
    second_response = client.get(
        f"{MAILS_URL}/attachments/mail_attachment_download/download"
    )

    assert first_response.status_code == 200
    assert first_response.content == b"hello attachment"
    assert second_response.status_code == 200
    assert second_response.content == b"hello attachment"
    assert calls == [
        "/users/me/messages/gmail_mail_api_1/attachments/gmail_attach_download"
    ]


def test_move_cached_mail_attachment_to_storage_deletes_tmp_file(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment move",
        body_text="Please store the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_move",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_move",
        filename="move-note.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        lambda path, access_token, params=None: {
            "data": base64.urlsafe_b64encode(b"cached attachment")
            .decode("ascii")
            .rstrip("="),
        },
    )

    cache_response = client.get(f"{MAILS_URL}/attachments/mail_attachment_move/download")
    assert cache_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        tmp_row = connection.execute(
            """
            SELECT storage_objects.id, storage_objects.storage_path
            FROM gmail_message_attachments
            JOIN storage_objects
                ON storage_objects.id = gmail_message_attachments.storage_object_id
            WHERE gmail_message_attachments.id = ?
            """,
            ("mail_attachment_move",),
        ).fetchone()
    tmp_storage_object_id, tmp_storage_path = tmp_row
    assert (database_path.parent / "storage" / tmp_storage_path).is_file()

    move_response = client.post(
        f"{MAILS_URL}/attachments/mail_attachment_move/move-to-storage"
    )

    assert move_response.status_code == 200
    managed_object = move_response.json()["data"]["storage_object"]
    assert managed_object["scope"] == "managed"
    assert managed_object["source_type"] == "mail_attachment"
    assert managed_object["source_message_id"] == message_id
    with sqlite3.connect(database_path) as connection:
        tmp_status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (tmp_storage_object_id,),
        ).fetchone()[0]
        attachment_storage_object_id = connection.execute(
            "SELECT storage_object_id FROM gmail_message_attachments WHERE id = ?",
            ("mail_attachment_move",),
        ).fetchone()[0]

    assert tmp_status == "deleted"
    assert attachment_storage_object_id == managed_object["id"]
    assert not (database_path.parent / "storage" / tmp_storage_path).exists()

    with sqlite3.connect(database_path) as connection:
        managed_storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (managed_object["id"],),
        ).fetchone()[0]
    assert (database_path.parent / "storage" / managed_storage_path).is_file()

    delete_response = client.delete(f"/api/v1/storage/objects/{managed_object['id']}")

    assert delete_response.status_code == 200
    restored_object = delete_response.json()["data"]["restored_storage_object"]
    assert restored_object["scope"] == "tmp/gmail-attachments"
    assert restored_object["source_type"] == "mail_attachment"
    assert restored_object["source_message_id"] == message_id
    with sqlite3.connect(database_path) as connection:
        managed_status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (managed_object["id"],),
        ).fetchone()[0]
        restored_storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (restored_object["id"],),
        ).fetchone()[0]
        restored_attachment_storage_object_id = connection.execute(
            "SELECT storage_object_id FROM gmail_message_attachments WHERE id = ?",
            ("mail_attachment_move",),
        ).fetchone()[0]

    assert managed_status == "deleted"
    assert restored_attachment_storage_object_id == restored_object["id"]
    assert not (database_path.parent / "storage" / managed_storage_path).exists()
    assert (database_path.parent / "storage" / restored_storage_path).is_file()


def test_mail_attachment_fetch_job_stores_attachment(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment background fetch",
        body_text="Please store this file in the background.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_fetch_job",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_fetch_job",
        filename="fetch-job.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)

    from caseclosed import google_integration
    from caseclosed.services.orchestrator import Orchestrator

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        lambda path, access_token, params=None: {
            "data": base64.urlsafe_b64encode(b"background attachment")
            .decode("ascii")
            .rstrip("="),
        },
    )

    response = client.post(
        f"{MAILS_URL}/attachments/mail_attachment_fetch_job/fetch-job"
    )

    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    assert Orchestrator(worker_id="worker-test").run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            "SELECT status, error_type FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        attachment_row = connection.execute(
            """
            SELECT gmail_message_attachments.storage_object_id,
                   storage_objects.scope,
                   storage_objects.original_filename,
                   storage_objects.byte_size,
                   storage_objects.storage_path
            FROM gmail_message_attachments
            JOIN storage_objects
                ON storage_objects.id = gmail_message_attachments.storage_object_id
            WHERE gmail_message_attachments.id = ?
            """,
            ("mail_attachment_fetch_job",),
        ).fetchone()

    assert job_row == ("succeeded", None)
    assert attachment_row[1:4] == (
        "managed",
        "fetch-job.txt",
        len(b"background attachment"),
    )
    assert (database_path.parent / "storage" / attachment_row[4]).is_file()


def test_llm_block_filter_marks_matching_mail_and_worker_skips_llm(
    client,
    database_path,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Password reset notice",
        body_text="Your temporary password is hunter2.",
    )

    response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "temporary password", "reason": "May contain password."},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filter"]["query_text"] == "temporary password"
    assert data["filter"]["is_enabled"] is True
    assert data["matched"] == 1
    assert data["changed"] == 1
    assert data["items"][0]["id"] == message_id
    assert data["items"][0]["llm_block_reason"] == "May contain password."

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["auto_state"]["llm_blocked"] is True
    assert detail["auto_state"]["llm_block_reason"] == "May contain password."
    assert detail["auto_state"]["effective_importance"] == "pinned"
    assert detail["message"]["effective_importance"] == "pinned"
    assert detail["message"]["llm_blocked"] is True

    run_response = client.post("/api/v1/jobs/run-next")
    assert run_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        llm_run_count = connection.execute("SELECT COUNT(*) FROM llm_runs").fetchone()
        job_row = connection.execute(
            """
            SELECT status, result_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert llm_run_count == (0,)
    assert job_row[0] == "succeeded"
    assert json.loads(job_row[1])["reason"] == "llm_blocked"
    assert json.loads(job_row[1])["effective_importance"] == "pinned"


def test_llm_block_filter_applies_to_newly_ingested_mail_before_llm_job(
    client,
    database_path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Blocked Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "blocked.sender@example.com", "is_primary": True}
            ],
        },
    )
    register_response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "secret token", "reason": "Contains credential material."},
    )

    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_future_llm_block",
        gmail_thread_id="thread_future_llm_block",
        from_address="blocked.sender@example.com",
        subject="Routine note",
        received_at="2026-05-23T13:30:00+09:00",
        body_text="Please use this secret token only once.",
    )

    assert register_response.status_code == 200
    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    detail = detail_response.json()["data"]
    assert detail["auto_state"]["llm_blocked"] is True
    assert detail["auto_state"]["llm_block_reason"] == "Contains credential material."
    assert detail["auto_state"]["effective_importance"] == "pinned"
    assert detail["message"]["effective_importance"] == "pinned"

    with sqlite3.connect(database_path) as connection:
        jobs = connection.execute(
            """
            SELECT job_type
            FROM jobs
            WHERE payload_json LIKE ?
            """,
            (f"%{message_id}%",),
        ).fetchall()

    assert jobs == []


def test_llm_block_filters_can_be_listed_and_disabled(client) -> None:
    create_response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "private material", "reason": "Private material."},
    )
    block_filter = create_response.json()["data"]["filter"]

    list_response = client.get(f"{MAILS_URL}/llm-block-filters")
    disable_response = client.patch(
        f"{MAILS_URL}/llm-block-filters/{block_filter['id']}",
        json={"is_enabled": False},
    )

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["id"] == block_filter["id"]
    assert disable_response.status_code == 200
    assert disable_response.json()["data"]["is_enabled"] is False


def test_llm_model_config_lists_profiles_and_updates_assignment(client) -> None:
    config_response = client.get(f"{MAILS_URL}/llm-model-config")

    assert config_response.status_code == 200
    config = config_response.json()["data"]
    profile_ids = {profile["id"] for profile in config["profiles"]}
    assert {"openai_gpt_5_2", "openai_gpt_5_4"} <= profile_ids
    importance_config = next(
        item
        for item in config["functions"]
        if item["function_type"] == "mail_importance_classification"
    )
    assert importance_config["profile_id"] == "mock"

    update_response = client.patch(
        f"{MAILS_URL}/llm-model-config",
        json={
            "function_type": "mail_importance_classification",
            "profile_id": "openai_gpt_5_2",
        },
    )

    assert update_response.status_code == 200
    updated_importance_config = next(
        item
        for item in update_response.json()["data"]["functions"]
        if item["function_type"] == "mail_importance_classification"
    )
    assert updated_importance_config["profile_id"] == "openai_gpt_5_2"


def test_send_mail_records_mock_send_request(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Reply source",
        body_text="Original body.",
    )

    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com", "reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Reply source",
            "body_text": "Thanks.\n\n> Original body.",
            "attachments": [
                {
                    "filename": "agenda.pdf",
                    "content_type": "application/pdf",
                    "data_base64": base64.b64encode(b"agenda").decode("ascii"),
                    "size": 6,
                }
            ],
            "reply_to_message_id": message_id,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"].startswith("mail_send_")
    assert data["status"] == "scheduled_mock"
    assert data["to_addresses"] == ["reply@example.com"]
    assert data["cc_addresses"] == ["team@example.com"]
    assert data["bcc_addresses"] == []
    assert data["subject"] == "Reply source"
    assert data["body_text"] == "Thanks.\n\n> Original body."
    assert data["attachment_names"] == ["agenda.pdf"]
    assert data["reply_to_message_id"] == message_id
    assert data["sent_message_id"] is None
    assert data["scheduled_at"] is not None

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT status, to_addresses_json, attachment_names_json, scheduled_at "
            "FROM mail_send_requests"
        ).fetchall()
        jobs = connection.execute(
            "SELECT job_type, status, payload_json FROM jobs "
            "WHERE job_type = 'mail_send_mock'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "scheduled_mock"
    assert rows[0][1] == '["reply@example.com"]'
    assert rows[0][2] == '["agenda.pdf"]'
    assert rows[0][3] is not None
    assert len(jobs) == 1
    assert jobs[0][1] == "pending"
    assert json.loads(jobs[0][2])["send_request_id"] == data["id"]


def test_send_mail_rejects_attachment_names_without_file_data(client) -> None:
    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Attachment names only",
            "body_text": "Body.",
            "attachment_names": ["name-only.pdf"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_send_mail_requests_can_be_listed_for_debug(client) -> None:
    client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["first@example.com"],
            "subject": "First",
            "body_text": "First body.",
        },
    )
    client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["second@example.com"],
            "subject": "Second",
            "body_text": "Second body.",
            "cc_addresses": ["cc@example.com"],
        },
    )

    response = client.get(f"{MAILS_URL}/send-requests")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["subject"] for item in items] == ["Second", "First"]
    assert items[0]["status"] == "scheduled_mock"
    assert items[0]["to_addresses"] == ["second@example.com"]
    assert items[0]["cc_addresses"] == ["cc@example.com"]


def test_send_job_fails_without_gmail_connection(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Reply source",
        body_text="Original body.",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Reply source",
            "body_text": "Thanks.\n\n> Original body.",
            "reply_to_message_id": message_id,
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")

    run_response = client.post("/api/v1/jobs/run-next")

    assert run_response.status_code == 200
    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    detail = detail_response.json()["data"]
    sent_messages = [
        message
        for message in detail["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert sent_messages == []

    with sqlite3.connect(database_path) as connection:
        send_request_row = connection.execute(
            "SELECT status, sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()
        job_row = connection.execute(
            """
            SELECT status, error_type, error_message
            FROM jobs
            WHERE job_type = 'mail_send_mock'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    assert send_request_row == ("failed_gmail", None)
    assert job_row[0] == "failed"
    assert job_row[1] == "RuntimeError"
    assert "Gmail is not connected" in job_row[2]


def test_send_only_sent_message_appears_in_done_list(
    client,
    database_path,
    monkeypatch,
) -> None:
    connect_gmail_send(database_path)
    patch_gmail_send_response(
        monkeypatch,
        gmail_message_id="gmail_sent_standalone",
        gmail_thread_id="thread_sent_standalone",
        subject="Standalone sent mail",
        body_text="This mail starts a new thread.",
        to_address="new.receiver@example.com",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["new.receiver@example.com"],
            "subject": "Standalone sent mail",
            "body_text": "This mail starts a new thread.",
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert run_response.status_code == 200

    list_response = client.get(f"{MAILS_URL}?tab=processed&limit=20")
    items = list_response.json()["data"]["items"]
    sent_item = next(item for item in items if item["subject"] == "Standalone sent mail")

    assert sent_item["processed_status"] == "processed"
    assert sent_item["read_status"] == "read"
    assert sent_item["effective_importance"] == "sent"

    detail_response = client.get(f"{MAILS_URL}/{sent_item['id']}")
    detail = detail_response.json()["data"]
    assert detail["message"]["body_text"] == "This mail starts a new thread."
    assert detail["message"]["gmail_labels"] == ["SENT"]


def test_send_job_uses_gmail_api_when_gmail_send_scope_is_connected(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Gmail reply source",
        body_text="Original Gmail body.",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Gmail reply source",
            "body_text": "Thanks from Gmail.",
            "reply_to_message_id": message_id,
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    sent_raw_messages = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        assert thread_id == "thread_mail_api"
        sent_raw_messages.append(raw_message)
        return {"id": "gmail_sent_real", "threadId": "thread_mail_api"}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == "/users/me/messages/gmail_sent_real":
            return {
                "id": "gmail_sent_real",
                "threadId": "thread_mail_api",
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "snippet": "Thanks from Gmail.",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "reply@example.com"},
                        {"name": "Cc", "value": "team@example.com"},
                        {"name": "Subject", "value": "Gmail reply source"},
                        {"name": "Message-ID", "value": "<gmail-sent-real@example.com>"},
                        {"name": "In-Reply-To", "value": "<mail-api-1@example.com>"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Thanks from Gmail."
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert run_response.status_code == 200
    assert len(sent_raw_messages) == 1
    raw_message = message_from_bytes(sent_raw_messages[0])
    assert raw_message["From"] == "me@example.com"
    assert raw_message["To"] == "reply@example.com"
    assert raw_message["Cc"] == "team@example.com"
    assert raw_message["In-Reply-To"] == "<mail-api-1@example.com>"
    assert raw_message.get_payload().strip() == "Thanks from Gmail."

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    sent_messages = [
        message
        for message in detail_response.json()["data"]["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert len(sent_messages) == 1
    assert sent_messages[0]["gmail_message_id"] == "gmail_sent_real"
    assert sent_messages[0]["from_address"] == "me@example.com"

    with sqlite3.connect(database_path) as connection:
        send_request_row = connection.execute(
            "SELECT status, sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()

    assert send_request_row[0] == "sent_gmail"
    assert send_request_row[1] == sent_messages[0]["id"]


def test_gmail_send_job_builds_attachment_mime_part(
    client,
    database_path,
    monkeypatch,
) -> None:
    draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["receiver@example.com"],
            "subject": "Attachment draft",
            "body_text": "Draft body.",
            "attachment_refs": [
                {
                    "name": "draft-note.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(b"draft attachment").decode("ascii"),
                },
            ],
        },
    )
    draft_storage_object_id = draft_response.json()["data"]["attachment_refs"][0][
        "storage_object_id"
    ]
    attachment_upload_response = client.post(
        "/api/v1/storage/tmp",
        json={
            "filename": "note.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"attached text").decode("ascii"),
        },
    )
    storage_object_id = attachment_upload_response.json()["data"]["storage_object"]["id"]
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["receiver@example.com"],
            "subject": "Attachment mail",
            "body_text": "Please see attached.",
            "attachments": [
                {
                    "filename": "note.txt",
                    "content_type": "text/plain",
                    "storage_object_id": storage_object_id,
                    "size": 13,
                }
            ],
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    assert send_response.json()["data"]["attachment_names"] == ["note.txt"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    sent_raw_messages = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        assert thread_id is None
        sent_raw_messages.append(raw_message)
        return {"id": "gmail_sent_attachment", "threadId": "thread_sent_attachment"}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == "/users/me/messages/gmail_sent_attachment":
            return {
                "id": "gmail_sent_attachment",
                "threadId": "thread_sent_attachment",
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "receiver@example.com"},
                        {"name": "Subject", "value": "Attachment mail"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Please see attached."
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    assert send_now_response.status_code == 200
    run_response = client.post("/api/v1/jobs/run-next")

    assert run_response.status_code == 200
    assert run_response.json()["data"]["job_id"] is not None
    assert sent_raw_messages, client.get("/api/v1/jobs").json()
    raw_message = message_from_bytes(sent_raw_messages[0])
    attachments = [
        part
        for part in raw_message.walk()
        if part.get_content_disposition() == "attachment"
    ]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "note.txt"
    assert attachments[0].get_payload(decode=True) == b"attached text"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (draft_storage_object_id,),
        ).fetchone()
    assert row == ("deleted",)


def test_scheduled_send_request_can_be_rescheduled_sent_now_and_canceled(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Scheduled source",
        body_text="Original body.",
    )
    schedule_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Scheduled source",
            "body_text": "Later reply.",
            "reply_to_message_id": message_id,
            "scheduled_at": "2099-05-25T09:00:00+09:00",
        },
    )
    send_request = schedule_response.json()["data"]

    assert schedule_response.status_code == 200
    assert send_request["status"] == "scheduled_mock"
    assert send_request["scheduled_at"] == "2099-05-25T09:00:00+09:00"

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    scheduled_requests = detail_response.json()["data"]["scheduled_send_requests"]
    assert [item["id"] for item in scheduled_requests] == [send_request["id"]]

    reschedule_response = client.patch(
        f"{MAILS_URL}/send-requests/{send_request['id']}/schedule",
        json={"scheduled_at": "2099-05-25T10:30:00+09:00"},
    )
    assert reschedule_response.status_code == 200
    assert reschedule_response.json()["data"]["status"] == "scheduled_mock"
    assert reschedule_response.json()["data"]["scheduled_at"] == (
        "2099-05-25T10:30:00+09:00"
    )

    cancel_response = client.post(f"{MAILS_URL}/send-requests/{send_request['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "canceled"

    after_cancel_detail_response = client.get(f"{MAILS_URL}/{message_id}")
    assert after_cancel_detail_response.json()["data"]["scheduled_send_requests"] == []

    second_schedule_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Scheduled source",
            "body_text": "Send now reply.",
            "reply_to_message_id": message_id,
            "scheduled_at": "2099-05-25T11:00:00+09:00",
        },
    )
    second_id = second_schedule_response.json()["data"]["id"]
    connect_gmail_send(database_path)
    patch_gmail_send_response(
        monkeypatch,
        gmail_message_id="gmail_sent_scheduled",
        gmail_thread_id="thread_mail_api",
        subject="Scheduled source",
        body_text="Send now reply.",
        to_address="reply@example.com",
        in_reply_to="<mail-api-1@example.com>",
    )
    send_now_response = client.post(f"{MAILS_URL}/send-requests/{second_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert send_now_response.json()["data"]["status"] == "queued_mock"
    assert send_now_response.json()["data"]["scheduled_at"] is None
    assert run_response.status_code == 200

    detail_after_send_response = client.get(f"{MAILS_URL}/{message_id}")
    sent_messages = [
        message
        for message in detail_after_send_response.json()["data"]["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert len(sent_messages) == 1
    assert sent_messages[0]["body_text"] == "Send now reply."

    with sqlite3.connect(database_path) as connection:
        statuses = dict(
            connection.execute(
                "SELECT id, status FROM mail_send_requests WHERE id IN (?, ?)",
                (send_request["id"], second_id),
            ).fetchall()
        )
    assert statuses == {send_request["id"]: "canceled", second_id: "sent_gmail"}


def test_send_only_scheduled_request_appears_in_done_list_and_detail(client) -> None:
    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["new.receiver@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "New scheduled mail",
            "body_text": "This is a send-only scheduled mail.",
            "scheduled_at": "2099-05-25T15:00:00+09:00",
        },
    )
    send_request = response.json()["data"]

    list_response = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2099-05-25T00:00:00%2B09:00&date_to=2099-05-25T23:59:59%2B09:00"
    )
    dates_response = client.get(f"{MAILS_URL}/dates?tab=processed")
    detail_response = client.get(f"{MAILS_URL}/{send_request['id']}")

    assert response.status_code == 200
    assert send_request["status"] == "scheduled_mock"
    list_items = list_response.json()["data"]["items"]
    assert [item["id"] for item in list_items] == [send_request["id"]]
    assert list_items[0]["processed_status"] == "processed"
    assert list_items[0]["read_status"] == "read"
    assert list_items[0]["effective_importance"] == "sent"
    assert list_items[0]["received_date"] == "2099-05-25"
    assert dates_response.json()["data"]["items"] == [
        {"date": "2099-05-25", "count": 1}
    ]

    detail = detail_response.json()["data"]
    assert detail["message"]["id"] == send_request["id"]
    assert detail["message"]["thread_id"].startswith("provisional_thread_")
    assert detail["thread_messages"] == []
    assert [item["id"] for item in detail["scheduled_send_requests"]] == [
        send_request["id"]
    ]


def test_send_mail_requires_recipient_and_existing_reply_target(client) -> None:
    missing_recipient_response = client.post(
        f"{MAILS_URL}/send",
        json={"to_addresses": [], "body_text": "Body."},
    )
    missing_reply_target_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "body_text": "Body.",
            "reply_to_message_id": "mail_missing",
        },
    )

    assert missing_recipient_response.status_code == 422
    assert missing_recipient_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing_reply_target_response.status_code == 404
    assert missing_reply_target_response.json()["error"]["code"] == "NOT_FOUND"


def test_mail_draft_generation_standard_prompt_is_saved_in_app_settings(
    client,
    database_path,
) -> None:
    initial_response = client.get(f"{MAILS_URL}/draft-generation-standard-prompt")
    assert initial_response.status_code == 200
    assert initial_response.json()["data"]["standard_prompt"] == ""
    assert initial_response.json()["data"]["generation_language"] == "japanese"

    update_response = client.patch(
        f"{MAILS_URL}/draft-generation-standard-prompt",
        json={
            "standard_prompt": "Use concise academic English.\n",
            "generation_language": "english",
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["data"]["standard_prompt"] == (
        "Use concise academic English."
    )
    assert update_response.json()["data"]["generation_language"] == "english"
    read_response = client.get(f"{MAILS_URL}/draft-generation-standard-prompt")
    assert read_response.status_code == 200
    assert read_response.json()["data"]["standard_prompt"] == (
        "Use concise academic English."
    )
    assert read_response.json()["data"]["generation_language"] == "english"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT value_json
            FROM app_settings
            WHERE key = 'mail_draft_generation_standard_prompt'
            """
        ).fetchone()
        language_row = connection.execute(
            """
            SELECT value_json
            FROM app_settings
            WHERE key = 'mail_draft_generation_language'
            """
        ).fetchone()
    assert row == ('"Use concise academic English."',)
    assert language_row == ('"english"',)


def test_generate_reply_draft_uses_language_policy_without_auto_retry(
    client,
    database_path,
    monkeypatch,
) -> None:
    import importlib

    mails_module = importlib.import_module("caseclosed.mails")
    provider_module = importlib.import_module("caseclosed.services.llm_provider")

    class CapturingDraftProvider:
        provider_name = "test"
        model_name = "language-policy-test"

        def __init__(self) -> None:
            self.calls = []

        def complete_json(self, *, function_type, input_payload):
            self.calls.append(dict(input_payload))
            body = "承知しました。確認します。"
            output = {
                "schema_version": "1.0",
                "subject": "Re: Agenda review",
                "body": body,
                "reasoning_summary": "Generated test draft.",
                "warnings": [],
            }
            return provider_module.LlmProviderResponse(
                output=output,
                output_preview=body,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                estimated_cost=0.1,
            )

    provider = CapturingDraftProvider()
    monkeypatch.setattr(
        mails_module,
        "build_mail_draft_generation_provider",
        lambda _function_type: provider,
    )
    reply_to_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_language_policy_source",
        gmail_thread_id="thread_language_policy_source",
        from_address="sender@example.com",
        subject="Agenda review",
        body_text=(
            "Please review the attached agenda and let me know if you can join "
            "tomorrow. We need your confirmation by Friday morning."
        ),
        received_at="2026-05-23T15:00:00+09:00",
    )
    setting_response = client.patch(
        f"{MAILS_URL}/draft-generation-standard-prompt",
        json={"generation_language": "english"},
    )
    assert setting_response.status_code == 200

    response = client.post(
        f"{MAILS_URL}/generate-draft",
        json={
            "to_addresses": ["sender@example.com"],
            "cc_addresses": [],
            "bcc_addresses": [],
            "subject": "Re: Agenda review",
            "body_text": "",
            "auto_body_text": "On May 23, sender@example.com wrote: ...",
            "reply_to_message_id": reply_to_message_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["body_text"] == "承知しました。確認します。"
    assert len(provider.calls) == 1
    assert provider.calls[0]["reply_language"] == "English"
    assert provider.calls[0]["language_generation_prompt"] == "英語で生成してください。"
    assert "reply to an English email" in provider.calls[0]["language_policy"]
    with sqlite3.connect(database_path) as connection:
        llm_run_row = connection.execute(
            """
            SELECT retry_count, prompt_tokens, completion_tokens, total_tokens,
                   input_source_json, input_diagnostic_json
            FROM llm_runs
            WHERE function_type = 'reply_draft_generation'
            """
        ).fetchone()
    assert llm_run_row[:4] == (0, 10, 5, 15)
    assert json.loads(llm_run_row[4])["generation_language"] == "english"
    assert json.loads(llm_run_row[5])["language_generation_prompt"] == (
        "英語で生成してください。"
    )


def test_mail_detail_keeps_mailing_list_as_from_contact_and_uses_reply_to_sender(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Committee List",
            "avatar_url": "https://example.com/list.png",
            "status": "archived",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "committee-list@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "List Writer",
            "avatar_url": "https://example.com/writer.png",
            "status": "active",
            "email_addresses": [
                {"email_address": "writer@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mailing_list_detail",
            "gmail_thread_id": "thread_mailing_list_detail",
            "message_id_header": "<mailing-list-detail@example.com>",
            "subject": "Mailing list detail",
            "from_address": "committee-list@example.com",
            "reply_to_address": "writer@example.com",
            "received_at": "2026-05-23T14:00:00+09:00",
            "body_text": "List mail.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    list_response = client.get(f"{MAILS_URL}?limit=20")
    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert list_response.status_code == 200
    list_item = next(
        item
        for item in list_response.json()["data"]["items"]
        if item["id"] == message_id
    )
    assert list_item["sender_contact"]["display_name"] == "Committee List"
    assert list_item["sender_contact"]["kind"] == "mailing_list"
    assert list_item["sender_contact"]["status"] == "archived"

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["from_contact"]["display_name"] == "Committee List"
    assert message["from_contact"]["kind"] == "mailing_list"
    assert message["from_contact"]["avatar_url"] == "https://example.com/list.png"
    assert message["sender_contact"]["display_name"] == "List Writer"
    assert message["sender_contact"]["kind"] == "person"
    assert message["sender_contact"]["avatar_url"] == "https://example.com/writer.png"


def test_mail_detail_uses_unresolved_reply_to_address_for_mailing_list_sender(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Archive Committee List",
            "status": "archived",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "archive-committee@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mailing_list_unresolved_reply_to",
            "gmail_thread_id": "thread_mailing_list_unresolved_reply_to",
            "message_id_header": "<mailing-list-unresolved-reply-to@example.com>",
            "subject": "Mailing list unresolved reply-to",
            "from_address": "archive-committee@example.com",
            "reply_to_address": "unregistered-writer@example.com",
            "received_at": "2026-05-23T14:10:00+09:00",
            "body_text": "List mail.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["from_contact"]["display_name"] == "Archive Committee List"
    assert message["from_contact"]["kind"] == "mailing_list"
    assert message["from_contact"]["sender_resolution_mode"] == "reply_to"
    assert message["reply_to_address"] == "unregistered-writer@example.com"
    assert message["sender_contact"] is None


def test_mail_list_filters_by_importance_processed_and_query(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Review deadline",
        body_text="Please review this before the deadline.",
    )
    client.post(
        f"{MAILS_URL}/{message_id}/importance",
        json={"importance": "Middle"},
    )
    client.post(f"{MAILS_URL}/{message_id}/process", json={"reason": "handled"})

    matching_response = client.get(
        f"{MAILS_URL}?importance=Middle&processed=1&q=deadline"
    )
    empty_response = client.get(f"{MAILS_URL}?importance=High&processed=1&q=deadline")
    unprocessed_response = client.get(f"{MAILS_URL}?processed=0")

    assert matching_response.status_code == 200
    assert [item["id"] for item in matching_response.json()["data"]["items"]] == [
        message_id
    ]
    assert matching_response.json()["data"]["items"][0]["processed_status"] == (
        "processed"
    )
    assert empty_response.json()["data"]["items"] == []
    assert unprocessed_response.json()["data"]["items"] == []


def test_mail_list_supports_matomail_style_tabs_and_read_filter(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Tab Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "tab.sender@example.com", "is_primary": True}
            ],
        },
    )
    unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_unprocessed",
        gmail_thread_id="thread_tab_unprocessed",
        from_address="tab.sender@example.com",
        subject="Unprocessed mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    processed_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_processed",
        gmail_thread_id="thread_tab_processed",
        from_address="tab.sender@example.com",
        subject="Processed mail",
        received_at="2026-05-23T10:00:00+09:00",
    )
    skip_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_skip",
        gmail_thread_id="thread_tab_skip",
        from_address="tab.sender@example.com",
        subject="Skip mail",
        received_at="2026-05-23T11:00:00+09:00",
    )
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_pending",
        gmail_thread_id="thread_tab_pending",
        from_address="pending.tab@example.com",
        subject="Pending mail",
        received_at="2026-05-23T12:00:00+09:00",
    )
    client.post(f"{MAILS_URL}/{processed_id}/process", json={"reason": "handled"})
    client.post(f"{MAILS_URL}/{skip_id}/importance", json={"importance": "Skip"})
    client.post(f"{MAILS_URL}/{unprocessed_id}/read")

    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")
    processed_response = client.get(f"{MAILS_URL}?tab=processed")
    skip_response = client.get(f"{MAILS_URL}?tab=skip")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    read_response = client.get(f"{MAILS_URL}?read=read")
    unread_response = client.get(f"{MAILS_URL}?read=unread&tab=unprocessed")

    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        unprocessed_id
    ]
    assert [item["id"] for item in processed_response.json()["data"]["items"]] == [
        processed_id
    ]
    assert [item["id"] for item in skip_response.json()["data"]["items"]] == [
        skip_id
    ]
    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]
    read_item = read_response.json()["data"]["items"][0]
    assert read_item["id"] == unprocessed_id
    assert read_item["read_status"] == "read"
    assert read_item["received_date"] == "2026-05-23"
    assert isinstance(read_item["importance_rank"], int)
    assert unread_response.json()["data"]["items"] == []


def test_mail_list_needs_action_matches_unprocessed_high_or_middle_messages(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Needs Action Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "needs.action@example.com", "is_primary": True}
            ],
        },
    )
    processed_high_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_processed_high",
        gmail_thread_id="thread_needs_processed_high_low",
        from_address="needs.action@example.com",
        subject="Processed high older mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    low_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_low_unprocessed",
        gmail_thread_id="thread_needs_processed_high_low",
        from_address="needs.action@example.com",
        subject="Low latest mail",
        received_at="2026-05-23T10:00:00+09:00",
    )
    high_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_high_unprocessed",
        gmail_thread_id="thread_needs_high_unprocessed",
        from_address="needs.action@example.com",
        subject="High action mail",
        received_at="2026-05-23T11:00:00+09:00",
    )
    middle_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_middle_unprocessed",
        gmail_thread_id="thread_needs_middle_unprocessed",
        from_address="needs.action@example.com",
        subject="Middle action mail",
        received_at="2026-05-23T12:00:00+09:00",
    )
    pinned_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_pinned_unprocessed",
        gmail_thread_id="thread_needs_pinned_unprocessed",
        from_address="needs.action@example.com",
        subject="Pinned mail",
        received_at="2026-05-23T13:00:00+09:00",
    )
    client.post(
        f"{MAILS_URL}/{processed_high_id}/importance",
        json={"importance": "High"},
    )
    client.post(f"{MAILS_URL}/{processed_high_id}/process", json={"reason": "handled"})
    client.post(f"{MAILS_URL}/{low_unprocessed_id}/importance", json={"importance": "Low"})
    client.post(f"{MAILS_URL}/{high_unprocessed_id}/importance", json={"importance": "High"})
    client.post(
        f"{MAILS_URL}/{middle_unprocessed_id}/importance",
        json={"importance": "Middle"},
    )
    client.post(
        f"{MAILS_URL}/{pinned_unprocessed_id}/importance",
        json={"importance": "Pinned"},
    )

    response = client.get(f"{MAILS_URL}?needs_action=true")

    assert response.status_code == 200
    gmail_thread_ids = {
        item["gmail_thread_id"] for item in response.json()["data"]["items"]
    }
    assert gmail_thread_ids == {
        "thread_needs_high_unprocessed",
        "thread_needs_middle_unprocessed",
    }


def test_spam_contact_mail_appears_in_skip_tab_with_contact_status(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Spam Sender",
            "status": "spam",
            "email_addresses": [
                {"email_address": "spam.list@example.com", "is_primary": True}
            ],
        },
    )
    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_spam_tab",
        gmail_thread_id="thread_spam_tab",
        from_address="spam.list@example.com",
        subject="Spam tab mail",
        received_at="2026-05-23T13:00:00+09:00",
    )

    skip_response = client.get(f"{MAILS_URL}?tab=skip")

    assert skip_response.status_code == 200
    items = skip_response.json()["data"]["items"]
    assert [item["id"] for item in items] == [message_id]
    assert items[0]["effective_importance"] == "skip"
    assert items[0]["sender_contact"]["status"] == "spam"


def test_mail_list_aggregates_inbound_messages_by_thread(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Thread Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "thread.sender@example.com", "is_primary": True}
            ],
        },
    )
    older_id = ingest_mail(
        client,
        gmail_message_id="gmail_thread_older",
        gmail_thread_id="thread_aggregate",
        from_address="thread.sender@example.com",
        subject="Older inbound",
        received_at="2026-05-23T09:00:00+09:00",
    )
    latest_id = ingest_mail(
        client,
        gmail_message_id="gmail_thread_latest",
        gmail_thread_id="thread_aggregate",
        from_address="thread.sender@example.com",
        subject="Latest inbound",
        received_at="2026-05-23T11:00:00+09:00",
    )
    sent_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_thread_sent",
            "gmail_thread_id": "thread_aggregate",
            "message_id_header": "<gmail-thread-sent@example.com>",
            "subject": "Sent reply",
            "from_address": "me@example.com",
            "gmail_labels": ["SENT"],
            "received_at": "2026-05-23T12:00:00+09:00",
            "body_text": "Outgoing reply.",
        },
    )
    assert sent_response.status_code == 200
    client.post(f"{MAILS_URL}/{older_id}/importance", json={"importance": "High"})
    client.post(f"{MAILS_URL}/{latest_id}/importance", json={"importance": "Low"})
    client.post(f"{MAILS_URL}/{latest_id}/read")
    client.post(f"{MAILS_URL}/{older_id}/unread")

    response = client.get(f"{MAILS_URL}?tab=unprocessed")
    unread_response = client.get(f"{MAILS_URL}?tab=unprocessed&read=unread")
    read_response = client.get(f"{MAILS_URL}?tab=unprocessed&read=read")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["id"] for item in items] == [latest_id]
    assert items[0]["subject"] == "Latest inbound"
    assert items[0]["effective_importance"] == "high"
    assert items[0]["importance_rank"] == 1
    assert items[0]["user_importance"] == "low"
    assert items[0]["read_status"] == "unread"
    assert [item["id"] for item in unread_response.json()["data"]["items"]] == [
        latest_id
    ]
    assert read_response.json()["data"]["items"] == []

    thread_read_response = client.post(f"{MAILS_URL}/{latest_id}/read")

    assert thread_read_response.status_code == 200
    assert {
        message["id"]: message["read_status"]
        for message in thread_read_response.json()["data"]["thread_messages"]
        if message["id"] in {older_id, latest_id}
    } == {older_id: "read", latest_id: "read"}


def test_mail_dates_returns_days_with_mail_for_tab(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Calendar Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "calendar.sender@example.com", "is_primary": True}
            ],
        },
    )
    first_id = ingest_mail(
        client,
        gmail_message_id="gmail_calendar_first",
        gmail_thread_id="thread_calendar_first",
        from_address="calendar.sender@example.com",
        subject="First calendar mail",
        received_at="2026-05-21T09:00:00+09:00",
    )
    second_id = ingest_mail(
        client,
        gmail_message_id="gmail_calendar_second",
        gmail_thread_id="thread_calendar_second",
        from_address="calendar.sender@example.com",
        subject="Second calendar mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    client.post(f"{MAILS_URL}/{second_id}/process", json={"reason": "handled"})

    all_response = client.get(f"{MAILS_URL}/dates")
    unprocessed_response = client.get(f"{MAILS_URL}/dates?tab=unprocessed")
    processed_response = client.get(f"{MAILS_URL}/dates?tab=processed")

    assert all_response.status_code == 200
    assert all_response.json()["data"]["items"] == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-23", "count": 1},
    ]
    assert unprocessed_response.json()["data"]["items"] == [
        {"date": "2026-05-21", "count": 1}
    ]
    assert processed_response.json()["data"]["items"] == [
        {"date": "2026-05-23", "count": 1}
    ]
    assert first_id != second_id


def test_thread_mail_is_grouped_by_thread_and_day(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Daily Thread Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "daily.thread@example.com", "is_primary": True}
            ],
        },
    )
    first_id = ingest_mail(
        client,
        gmail_message_id="gmail_daily_thread_first",
        gmail_thread_id="thread_daily_group",
        from_address="daily.thread@example.com",
        subject="Daily thread first",
        received_at="2026-05-21T09:00:00+09:00",
    )
    second_id = ingest_mail(
        client,
        gmail_message_id="gmail_daily_thread_second",
        gmail_thread_id="thread_daily_group",
        from_address="daily.thread@example.com",
        subject="Daily thread second",
        received_at="2026-05-23T09:00:00+09:00",
    )
    sent_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_daily_thread_sent",
            "gmail_thread_id": "thread_daily_group",
            "message_id_header": "<gmail-daily-thread-sent@example.com>",
            "subject": "Daily thread reply",
            "from_address": "me@example.com",
            "gmail_labels": ["SENT"],
            "received_at": "2026-05-24T09:00:00+09:00",
            "body_text": "Sent reply.",
        },
    )
    sent_id = sent_response.json()["data"]["message_id"]
    client.post(f"{MAILS_URL}/{first_id}/process", json={"reason": "handled"})

    all_dates = client.get(f"{MAILS_URL}/dates").json()["data"]["items"]
    processed_dates = client.get(f"{MAILS_URL}/dates?tab=processed").json()["data"]["items"]
    unprocessed_dates = client.get(
        f"{MAILS_URL}/dates?tab=unprocessed"
    ).json()["data"]["items"]

    assert all_dates == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-23", "count": 1},
        {"date": "2026-05-24", "count": 1},
    ]
    assert processed_dates == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-24", "count": 1},
    ]
    assert unprocessed_dates == [{"date": "2026-05-23", "count": 1}]

    day1 = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2026-05-21T00:00:00+09:00"
        "&date_to=2026-05-21T23:59:59+09:00"
    ).json()["data"]["items"]
    day2 = client.get(
        f"{MAILS_URL}?tab=unprocessed&date_from=2026-05-23T00:00:00+09:00"
        "&date_to=2026-05-23T23:59:59+09:00"
    ).json()["data"]["items"]
    day3 = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2026-05-24T00:00:00+09:00"
        "&date_to=2026-05-24T23:59:59+09:00"
    ).json()["data"]["items"]

    assert [item["id"] for item in day1] == [first_id]
    assert [item["id"] for item in day2] == [second_id]
    assert [item["id"] for item in day3] == [sent_id]
    assert day3[0]["processed_status"] == "processed"
    assert day3[0]["effective_importance"] == "sent"


def test_mail_list_filters_pending_dates_and_and_query(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Senders",
            "status": "active",
            "email_addresses": [
                {"email_address": "alpha.sender@example.com", "is_primary": True},
                {"email_address": "beta.sender@example.com", "is_primary": False},
            ],
        },
    )
    alpha_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_alpha",
        gmail_thread_id="thread_filter_alpha",
        from_address="alpha.sender@example.com",
        subject="Alpha budget",
        received_at="2026-05-23T10:00:00+09:00",
        body_text="Please review the budget memo.",
    )
    beta_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_beta",
        gmail_thread_id="thread_filter_beta",
        from_address="beta.sender@example.com",
        subject="Beta deadline",
        received_at="2026-05-23T11:00:00+09:00",
        body_text="Ordinary update.",
    )
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_pending",
        gmail_thread_id="thread_filter_pending",
        from_address="pending.filter@example.com",
        subject="Pending sender",
        received_at="2026-05-23T12:00:00+09:00",
        body_text="Needs contact resolution.",
    )
    client.post(f"{MAILS_URL}/{beta_id}/importance", json={"importance": "High"})

    pending_response = client.get(f"{MAILS_URL}?contact_status=pending")
    resolved_response = client.get(f"{MAILS_URL}?contact_status=resolved")
    date_response = client.get(
        f"{MAILS_URL}?date_from=2026-05-23T10:30:00%2B09:00&date_to=2026-05-23T11:30:00%2B09:00"
    )
    and_match_response = client.get(f"{MAILS_URL}?q=alpha%20budget")
    and_empty_response = client.get(f"{MAILS_URL}?q=alpha%20deadline")
    pending_importance_response = client.get(f"{MAILS_URL}?importance=pending")
    high_response = client.get(f"{MAILS_URL}?importance=high")

    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]
    assert [item["id"] for item in resolved_response.json()["data"]["items"]] == [
        beta_id,
        alpha_id,
    ]
    assert [item["id"] for item in date_response.json()["data"]["items"]] == [
        beta_id
    ]
    assert [item["id"] for item in and_match_response.json()["data"]["items"]] == [
        alpha_id
    ]
    assert and_empty_response.json()["data"]["items"] == []
    assert [item["id"] for item in pending_importance_response.json()["data"]["items"]] == [
        pending_id
    ]
    assert [item["id"] for item in high_response.json()["data"]["items"]] == [
        beta_id
    ]


def test_refresh_pending_mail_state_releases_linked_sender(client) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_pending",
        gmail_thread_id="thread_refresh_pending",
        from_address="refresh.pending@example.com",
        subject="Refresh pending sender",
        received_at="2026-05-23T12:10:00+09:00",
        body_text="Needs refresh.",
    )
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Refresh Pending",
            "status": "active",
            "email_addresses": [
                {"email_address": "refresh.pending@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200

    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")
    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "not_pending"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] is None
    assert data["mail"]["effective_importance"] == "unclassified"
    assert pending_response.json()["data"]["items"] == []
    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        pending_id
    ]


def test_refresh_pending_mail_state_applies_fixed_contact_importance(
    client,
    database_path,
) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_fixed_rule",
        gmail_thread_id="thread_refresh_fixed_rule",
        from_address="refresh.fixed@example.com",
        subject="Refresh fixed sender",
        received_at="2026-05-23T12:15:00+09:00",
        body_text="This should use fixed importance after contact creation.",
    )
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Refresh Fixed",
            "status": "active",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "high",
            "email_addresses": [
                {"email_address": "refresh.fixed@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200

    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "not_pending"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] is None
    assert data["mail"]["effective_importance"] == "high"
    assert pending_response.json()["data"]["items"] == []
    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        pending_id
    ]

    with sqlite3.connect(database_path) as connection:
        job_types = connection.execute(
            """
            SELECT job_type
            FROM jobs
            ORDER BY job_type
            """
        ).fetchall()

    assert ("mail_importance_classification",) not in job_types
    assert ("mail_summary",) in job_types


def test_refresh_pending_mail_state_keeps_unresolved_sender_pending(client) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_unresolved",
        gmail_thread_id="thread_refresh_unresolved",
        from_address="refresh.unresolved@example.com",
        subject="Refresh unresolved sender",
        received_at="2026-05-23T12:20:00+09:00",
    )

    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "pending_address_unresolved"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] == "unresolved_from_contact"
    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]


def test_mail_list_uses_limit_and_cursor_pagination(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Paged Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "paged.sender@example.com", "is_primary": True}
            ],
        },
    )
    newest_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_newest",
        gmail_thread_id="thread_page_newest",
        from_address="paged.sender@example.com",
        subject="Newest",
        received_at="2026-05-23T13:00:00+09:00",
    )
    middle_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_middle",
        gmail_thread_id="thread_page_middle",
        from_address="paged.sender@example.com",
        subject="Middle",
        received_at="2026-05-23T12:00:00+09:00",
    )
    oldest_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_oldest",
        gmail_thread_id="thread_page_oldest",
        from_address="paged.sender@example.com",
        subject="Oldest",
        received_at="2026-05-23T11:00:00+09:00",
    )

    first_response = client.get(f"{MAILS_URL}?limit=2")
    first_data = first_response.json()["data"]
    second_response = client.get(
        f"{MAILS_URL}?limit=2&cursor={first_data['next_cursor']}"
    )
    invalid_response = client.get(f"{MAILS_URL}?cursor=not-a-valid-cursor")

    assert first_response.status_code == 200
    assert first_data["limit"] == 2
    assert [item["id"] for item in first_data["items"]] == [newest_id, middle_id]
    assert first_data["next_cursor"] is not None
    assert [item["id"] for item in second_response.json()["data"]["items"]] == [
        oldest_id
    ]
    assert second_response.json()["data"]["next_cursor"] is None
    assert invalid_response.status_code == 422


def test_mail_process_unprocess_and_importance_update(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Routine update",
    )

    importance_response = client.post(
        f"{MAILS_URL}/{message_id}/importance",
        json={"importance": "High"},
    )
    process_response = client.post(
        f"{MAILS_URL}/{message_id}/process",
        json={"reason": "done"},
    )
    unprocess_response = client.post(f"{MAILS_URL}/{message_id}/unprocess")

    assert importance_response.status_code == 200
    assert importance_response.json()["data"]["auto_state"]["effective_importance"] == (
        "high"
    )
    assert importance_response.json()["data"]["user_state"]["user_importance"] == (
        "high"
    )
    assert process_response.json()["data"]["user_state"]["processed_status"] == (
        "processed"
    )
    assert unprocess_response.json()["data"]["user_state"]["processed_status"] == (
        "unprocessed"
    )


def test_request_mail_summary_queues_for_unclassified_mail(
    client,
    database_path,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Manual summary request",
        body_text="Please summarize this even before automatic importance is available.",
    )

    response = client.post(f"{MAILS_URL}/{message_id}/summary")

    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT job_type, status, payload_json
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

    assert job_row[0:2] == ("mail_summary", "pending")
    payload = json.loads(job_row[2])
    assert payload["message_id"] == message_id
    assert payload["force"] is True
    assert payload["reason"] == "manual_request"


def test_mail_detail_reports_active_summary_job(
    client,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Summary job visible",
        body_text="The detail view should show that summary is still running.",
    )

    summary_response = client.post(f"{MAILS_URL}/{message_id}/summary")
    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert summary_response.status_code == 200
    assert detail_response.status_code == 200
    summary_jobs = detail_response.json()["data"]["summary_jobs"]
    assert summary_jobs[message_id]["job_id"] == summary_response.json()["data"]["job_id"]
    assert summary_jobs[message_id]["status"] == "pending"


def test_request_mail_summary_rejects_pinned_mail(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Pinned mail to read directly",
        body_text="This should not be summarized.",
    )
    client.post(f"{MAILS_URL}/{message_id}/importance", json={"importance": "Pinned"})

    response = client.post(f"{MAILS_URL}/{message_id}/summary")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Pinned mail cannot be summarized."


def test_mail_read_unread_update(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Read state update",
    )

    read_response = client.post(f"{MAILS_URL}/{message_id}/read")
    unread_response = client.post(f"{MAILS_URL}/{message_id}/unread")

    assert read_response.status_code == 200
    assert read_response.json()["data"]["user_state"]["read_status"] == "read"
    assert read_response.json()["data"]["user_state"]["read_at"] is not None
    assert unread_response.json()["data"]["user_state"]["read_status"] == "unread"
    assert unread_response.json()["data"]["user_state"]["read_at"] is None
