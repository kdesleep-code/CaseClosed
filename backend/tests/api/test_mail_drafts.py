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
        {
            "name": "report.pdf",
            "path": "C:/work/report.pdf",
            "content_type": "application/pdf",
            "size": None,
        },
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


def test_sending_mail_keeps_drafts_until_send_job_completes(
    client,
    database_path: Path,
) -> None:
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
    reply_draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "reply_to_message_id": reply_to_message_id,
            "to_addresses": ["draft.reply@example.com"],
            "subject": "Reply draft",
            "body_text": "Saved reply.",
            "attachment_refs": [
                {
                    "name": "reply-note.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(b"reply note").decode("ascii"),
                },
            ],
        },
    )
    reply_storage_object_id = reply_draft_response.json()["data"]["attachment_refs"][0][
        "storage_object_id"
    ]
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
    assert [item["key"] for item in reply_drafts_response.json()["data"]["items"]] == [
        reply_draft_response.json()["data"]["key"]
    ]
    assert [item["key"] for item in new_drafts_response.json()["data"]["items"]] == [
        new_mail_draft_response.json()["data"]["key"]
    ]
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (reply_storage_object_id,),
        ).fetchone()
    assert row == ("active",)


def test_mail_drafts_older_than_thirty_days_are_deleted(
    client,
    database_path: Path,
) -> None:
    old_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["old@example.com"],
            "subject": "Old draft",
            "body_text": "Expired.",
        },
    )
    current_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["current@example.com"],
            "subject": "Current draft",
            "body_text": "Still useful.",
        },
    )

    with sqlite3.connect(draft_database_path(database_path)) as connection:
        connection.execute(
            "UPDATE mail_drafts SET created_at = ?, updated_at = ? WHERE key = ?",
            (
                "2000-01-01T00:00:00+09:00",
                "2000-01-01T00:00:00+09:00",
                old_response.json()["data"]["key"],
            ),
        )
        connection.commit()

    list_response = client.get(MAIL_DRAFTS_URL)

    assert list_response.status_code == 200
    assert [item["key"] for item in list_response.json()["data"]["items"]] == [
        current_response.json()["data"]["key"]
    ]


def test_mail_draft_attachment_is_stored_in_tmp_storage_and_deleted(
    client,
    database_path: Path,
) -> None:
    attachment_body = b"stored draft attachment"
    draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["reader@example.com"],
            "subject": "Draft with attachment",
            "body_text": "Body.",
            "attachment_refs": [
                {
                    "name": "stored.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(attachment_body).decode("ascii"),
                    "size": len(attachment_body),
                },
            ],
        },
    )

    assert draft_response.status_code == 200
    draft = draft_response.json()["data"]
    storage_object_id = draft["attachment_refs"][0]["storage_object_id"]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT scope, status, storage_path FROM storage_objects WHERE id = ?",
            (storage_object_id,),
        ).fetchone()

    assert row[0] == "tmp/mail-draft-attachments"
    assert row[1] == "active"
    assert row[2].startswith("tmp/mail-draft-attachments/")
    assert (database_path.parent / "storage" / row[2]).read_bytes() == attachment_body

    resolve_response = client.post(
        f"{MAIL_DRAFTS_URL}/attachments/resolve",
        json={"attachment_refs": draft["attachment_refs"]},
    )

    assert resolve_response.status_code == 200
    resolved = resolve_response.json()["data"]["items"][0]
    assert resolved["storage_object_id"] == storage_object_id
    assert base64.b64decode(resolved["data_base64"]) == attachment_body

    delete_response = client.delete(f"{MAIL_DRAFTS_URL}/{draft['key']}")

    assert delete_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        deleted_row = connection.execute(
            "SELECT status, storage_path FROM storage_objects WHERE id = ?",
            (storage_object_id,),
        ).fetchone()

    assert deleted_row[0] == "deleted"
    assert not (database_path.parent / "storage" / deleted_row[1]).exists()


def test_expired_mail_draft_deletes_tmp_attachments(
    client,
    database_path: Path,
) -> None:
    draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["old@example.com"],
            "subject": "Old attachment draft",
            "body_text": "Expired.",
            "attachment_refs": [
                {
                    "name": "old.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(b"old attachment").decode("ascii"),
                },
            ],
        },
    )
    draft = draft_response.json()["data"]
    storage_object_id = draft["attachment_refs"][0]["storage_object_id"]

    with sqlite3.connect(draft_database_path(database_path)) as connection:
        connection.execute(
            "UPDATE mail_drafts SET created_at = ?, updated_at = ? WHERE key = ?",
            (
                "2000-01-01T00:00:00+09:00",
                "2000-01-01T00:00:00+09:00",
                draft["key"],
            ),
        )
        connection.commit()

    list_response = client.get(MAIL_DRAFTS_URL)

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == []
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (storage_object_id,),
        ).fetchone()

    assert row == ("deleted",)


def test_saving_loaded_draft_copies_tmp_attachment(
    client,
    database_path: Path,
) -> None:
    first_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["copy@example.com"],
            "subject": "Copy source",
            "body_text": "Body.",
            "attachment_refs": [
                {
                    "name": "copy.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(b"copy me").decode("ascii"),
                },
            ],
        },
    )
    first_draft = first_response.json()["data"]
    first_storage_object_id = first_draft["attachment_refs"][0]["storage_object_id"]

    second_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["copy@example.com"],
            "subject": "Copy target",
            "body_text": "Body.",
            "attachment_refs": first_draft["attachment_refs"],
        },
    )

    assert second_response.status_code == 200
    second_storage_object_id = second_response.json()["data"]["attachment_refs"][0][
        "storage_object_id"
    ]
    assert second_storage_object_id != first_storage_object_id

    client.delete(f"{MAIL_DRAFTS_URL}/{first_draft['key']}")

    with sqlite3.connect(database_path) as connection:
        rows = dict(
            connection.execute(
                "SELECT id, status FROM storage_objects WHERE id IN (?, ?)",
                (first_storage_object_id, second_storage_object_id),
            ).fetchall()
        )

    assert rows[first_storage_object_id] == "deleted"
    assert rows[second_storage_object_id] == "active"


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
