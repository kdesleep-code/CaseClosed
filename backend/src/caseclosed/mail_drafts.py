from __future__ import annotations

import json
import base64
import mimetypes
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from caseclosed.auth import json_error
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.settings import get_mail_drafts_database_path

router = APIRouter(prefix="/api/v1/mail-drafts", tags=["mail-drafts"])
MAIL_DRAFT_RETENTION_DAYS = 30


class MailDraftAttachmentRefPayload(BaseModel):
    name: str
    path: str | None = None


class MailDraftPayload(BaseModel):
    reply_to_message_id: str | None = None
    to_addresses: list[str] = []
    cc_addresses: list[str] = []
    bcc_addresses: list[str] = []
    subject: str | None = None
    body_text: str = ""
    auto_body_text: str = ""
    selected_signature_id: str | None = None
    attachment_refs: list[MailDraftAttachmentRefPayload] = []
    scheduled_at: str | None = None


class MailDraftAttachmentResolvePayload(BaseModel):
    attachment_refs: list[MailDraftAttachmentRefPayload] = []


def draft_database_path() -> Path:
    return get_mail_drafts_database_path()


def draft_connection() -> sqlite3.Connection:
    path = draft_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def bootstrap_mail_drafts_database() -> None:
    with draft_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mail_drafts (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                reply_to_message_id TEXT,
                to_addresses_json TEXT NOT NULL,
                cc_addresses_json TEXT NOT NULL,
                bcc_addresses_json TEXT NOT NULL,
                subject TEXT,
                body_text TEXT NOT NULL,
                auto_body_text TEXT NOT NULL DEFAULT '',
                selected_signature_id TEXT,
                attachment_refs_json TEXT NOT NULL DEFAULT '[]',
                scheduled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mail_drafts_reply_to_updated
            ON mail_drafts(reply_to_message_id, updated_at DESC)
            """
        )
        connection.commit()
    cleanup_expired_mail_drafts()


def new_draft_key() -> str:
    return f"mail_draft_{uuid4().hex}"


def json_list(values: list[str]) -> str:
    return json.dumps([value for value in values if value.strip() != ""], ensure_ascii=True)


def draft_name(payload: MailDraftPayload) -> str:
    subject = (payload.subject or "").strip() or "(No subject)"
    body_source = payload.body_text.strip() or payload.auto_body_text.strip()
    first_line = next(
        (line.strip() for line in body_source.splitlines() if line.strip() != ""),
        "(No body)",
    )
    return f"{subject}: {first_line}"[:160]


def attachment_refs_json(refs: list[MailDraftAttachmentRefPayload]) -> str:
    return json.dumps(
        [
            {
                "name": ref.name.strip(),
                "path": (ref.path or ref.name).strip(),
            }
            for ref in refs
            if ref.name.strip() != ""
        ],
        ensure_ascii=True,
        sort_keys=True,
    )


def row_data(row: sqlite3.Row) -> dict[str, object]:
    return {
        "key": row["key"],
        "name": row["name"],
        "reply_to_message_id": row["reply_to_message_id"],
        "to_addresses": json.loads(row["to_addresses_json"]),
        "cc_addresses": json.loads(row["cc_addresses_json"]),
        "bcc_addresses": json.loads(row["bcc_addresses_json"]),
        "subject": row["subject"],
        "body_text": row["body_text"],
        "auto_body_text": row["auto_body_text"],
        "selected_signature_id": row["selected_signature_id"],
        "attachment_refs": json.loads(row["attachment_refs_json"]),
        "scheduled_at": row["scheduled_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def delete_mail_drafts_for_reply_target(reply_to_message_id: str | None) -> int:
    cleanup_expired_mail_drafts()
    with draft_connection() as connection:
        if reply_to_message_id is None:
            cursor = connection.execute(
                "DELETE FROM mail_drafts WHERE reply_to_message_id IS NULL"
            )
        else:
            cursor = connection.execute(
                "DELETE FROM mail_drafts WHERE reply_to_message_id = ?",
                (reply_to_message_id,),
            )
        connection.commit()
        return int(cursor.rowcount)


def cleanup_expired_mail_drafts(
    *,
    retention_days: int = MAIL_DRAFT_RETENTION_DAYS,
) -> int:
    cutoff = (jst_now() - timedelta(days=retention_days)).isoformat()
    with draft_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM mail_drafts WHERE created_at < ?",
            (cutoff,),
        )
        connection.commit()
        return int(cursor.rowcount)


def resolved_attachment_data(ref: MailDraftAttachmentRefPayload) -> dict[str, object] | None:
    path_text = (ref.path or ref.name).strip()
    if path_text == "":
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    data = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "filename": ref.name.strip() or path.name,
        "path": str(path),
        "content_type": content_type,
        "data_base64": base64.b64encode(data).decode("ascii"),
        "size": len(data),
    }


@router.post("")
def create_mail_draft(payload: MailDraftPayload) -> dict[str, object]:
    cleanup_expired_mail_drafts()
    now = jst_iso()
    draft_key = new_draft_key()
    with draft_connection() as connection:
        connection.execute(
            """
            INSERT INTO mail_drafts (
                key, name, reply_to_message_id,
                to_addresses_json, cc_addresses_json, bcc_addresses_json,
                subject, body_text, auto_body_text, selected_signature_id,
                attachment_refs_json, scheduled_at, created_at, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                draft_key,
                draft_name(payload),
                payload.reply_to_message_id,
                json_list(payload.to_addresses),
                json_list(payload.cc_addresses),
                json_list(payload.bcc_addresses),
                payload.subject,
                payload.body_text,
                payload.auto_body_text,
                payload.selected_signature_id,
                attachment_refs_json(payload.attachment_refs),
                payload.scheduled_at,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM mail_drafts WHERE key = ?",
            (draft_key,),
        ).fetchone()
        connection.commit()

    if row is None:
        raise json_error(500, "DRAFT_SAVE_FAILED", "Mail draft could not be saved.")
    return {"ok": True, "data": row_data(row)}


@router.get("")
def list_mail_drafts(reply_to_message_id: str | None = None) -> dict[str, object]:
    cleanup_expired_mail_drafts()
    with draft_connection() as connection:
        if reply_to_message_id is None:
            rows = connection.execute(
                """
                SELECT * FROM mail_drafts
                WHERE reply_to_message_id IS NULL
                ORDER BY updated_at DESC, key DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM mail_drafts
                WHERE reply_to_message_id = ?
                ORDER BY updated_at DESC, key DESC
                """,
                (reply_to_message_id,),
            ).fetchall()
    return {"ok": True, "data": {"items": [row_data(row) for row in rows]}}


@router.delete("/{draft_key}")
def delete_mail_draft(draft_key: str) -> dict[str, object]:
    with draft_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM mail_drafts WHERE key = ?",
            (draft_key,),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise json_error(404, "NOT_FOUND", "Mail draft not found.")
    return {"ok": True, "data": {"key": draft_key}}


@router.post("/attachments/resolve")
def resolve_mail_draft_attachments(
    payload: MailDraftAttachmentResolvePayload,
) -> dict[str, object]:
    resolved = []
    missing = []
    for ref in payload.attachment_refs:
        if ref.name.strip() == "":
            continue
        attachment = resolved_attachment_data(ref)
        if attachment is None:
            missing.append({"name": ref.name, "path": ref.path or ref.name})
        else:
            resolved.append(attachment)
    return {"ok": True, "data": {"items": resolved, "missing": missing}}
