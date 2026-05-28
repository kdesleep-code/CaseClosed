from __future__ import annotations

import sqlite3
import base64
from pathlib import Path

CONTACTS_URL = "/api/v1/contacts"
MAIL_DRAFTS_URL = "/api/v1/mail-drafts"
MAILS_URL = "/api/v1/mails"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"


def draft_database_path(database_path: Path) -> Path:
    return database_path.with_name(f"{database_path.stem}.drafts{database_path.suffix}")


def test_mail_drafts_are_saved_in_separate_database(client, database_path: Path) -> None:
    response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["reader@example.com"],
            "cc_addresses": ["cc@example.com"],
            "subject": "Draft subject",
            "body_text": "First body line\nSecond body line",
            "auto_body_text": "Auto body",
            "selected_signature_id": "signature_test",
            "attachment_refs": [
                {"name": "report.pdf", "path": "C:/work/report.pdf"},
            ],
        },
    )

    assert response.status_code == 200
    draft = response.json()["data"]
    assert draft["key"].startswith("mail_draft_")
    assert draft["name"] == "Draft subject: First body line"
    assert draft["reply_to_message_id"] is None
    assert draft["attachment_refs"] == [
        {"name": "report.pdf", "path": "C:/work/report.pdf"},
    ]

    drafts_path = draft_database_path(database_path)
    assert drafts_path.exists()
    with sqlite3.connect(drafts_path) as connection:
        table_row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'mail_drafts'"
        ).fetchone()
    assert table_row == ("mail_drafts",)

    list_response = client.get(MAIL_DRAFTS_URL)
    assert [item["key"] for item in list_response.json()["data"]["items"]] == [
        draft["key"]
    ]


def test_sending_mail_deletes_drafts_for_same_reply_target_only(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Draft Reply Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "draft.reply@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_draft_reply",
            "gmail_thread_id": "thread_draft_reply",
            "message_id_header": "<draft-reply@example.com>",
            "subject": "Reply target",
            "from_address": "draft.reply@example.com",
            "received_at": "2026-05-27T10:00:00+09:00",
            "body_text": "Reply target body.",
        },
    )
    reply_to_message_id = ingest_response.json()["data"]["message_id"]
    client.post(
        MAIL_DRAFTS_URL,
        json={
            "reply_to_message_id": reply_to_message_id,
            "to_addresses": ["draft.reply@example.com"],
            "subject": "Reply draft",
            "body_text": "Saved reply.",
        },
    )
    new_mail_draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["new@example.com"],
            "subject": "New draft",
            "body_text": "Saved new mail.",
        },
    )

    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["draft.reply@example.com"],
            "subject": "Reply send",
            "body_text": "Sending this clears reply drafts.",
            "reply_to_message_id": reply_to_message_id,
        },
    )

    assert send_response.status_code == 200
    reply_drafts_response = client.get(
        f"{MAIL_DRAFTS_URL}?reply_to_message_id={reply_to_message_id}"
    )
    new_drafts_response = client.get(MAIL_DRAFTS_URL)
    assert reply_drafts_response.json()["data"]["items"] == []
    assert [item["key"] for item in new_drafts_response.json()["data"]["items"]] == [
        new_mail_draft_response.json()["data"]["key"]
    ]


def test_resolve_mail_draft_attachments_reads_existing_files(
    client,
    tmp_path: Path,
) -> None:
    existing_file = tmp_path / "draft-attachment.txt"
    existing_file.write_text("attachment body", encoding="utf-8")

    response = client.post(
        f"{MAIL_DRAFTS_URL}/attachments/resolve",
        json={
            "attachment_refs": [
                {"name": "draft-attachment.txt", "path": str(existing_file)},
                {"name": "missing.txt", "path": str(tmp_path / "missing.txt")},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 1
    assert data["items"][0]["filename"] == "draft-attachment.txt"
    assert base64.b64decode(data["items"][0]["data_base64"]) == b"attachment body"
    assert data["missing"] == [
        {"name": "missing.txt", "path": str(tmp_path / "missing.txt")}
    ]

