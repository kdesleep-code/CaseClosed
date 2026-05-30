from __future__ import annotations

import json
import base64
import mimetypes
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db import runtime
from caseclosed.db.models import StorageObject
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.settings import get_mail_drafts_database_path
from caseclosed.storage import decode_base64_payload
from caseclosed.storage import delete_storage_object
from caseclosed.storage import save_storage_object
from caseclosed.storage import storage_object_absolute_path

router = APIRouter(prefix="/api/v1/mail-drafts", tags=["mail-drafts"])
MAIL_DRAFT_RETENTION_DAYS = 30
MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPE = "tmp/mail-draft-attachments"
MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPES = {"tmp", MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPE}


class MailDraftAttachmentRefPayload(BaseModel):
    name: str
    path: str | None = None
    content_type: str | None = None
    data_base64: str | None = None
    size: int | None = None
    storage_object_id: str | None = None


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


def normalize_content_type(content_type: str | None, filename: str) -> str:
    if content_type is not None and content_type.strip() != "":
        return content_type.strip()
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def is_mail_draft_attachment_storage_object(storage_object: StorageObject) -> bool:
    return (
        storage_object.status == "active"
        and storage_object.scope in MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPES
    )


def stored_attachment_refs(
    session: DatabaseSession,
    refs: list[MailDraftAttachmentRefPayload],
    *,
    now: str,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for ref in refs:
        name = ref.name.strip()
        if name == "":
            continue
        content_type = normalize_content_type(ref.content_type, name)
        item: dict[str, object] = {
            "name": name,
            "path": (ref.path or name).strip(),
            "content_type": content_type,
            "size": ref.size,
        }
        if ref.storage_object_id is not None and ref.storage_object_id.strip() != "":
            storage_object = session.get(StorageObject, ref.storage_object_id.strip())
            if storage_object is not None and is_mail_draft_attachment_storage_object(
                storage_object
            ):
                object_path = storage_object_absolute_path(storage_object, session)
                if not object_path.is_file():
                    continue
                copied_object = save_storage_object(
                    session,
                    scope=MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPE,
                    filename=name,
                    content_type=storage_object.content_type or content_type,
                    data=object_path.read_bytes(),
                    now=now,
                )
                item["storage_object_id"] = copied_object.id
                item["path"] = copied_object.storage_path
                item["content_type"] = copied_object.content_type or content_type
                item["size"] = copied_object.byte_size
                values.append(item)
                continue
        if ref.data_base64 is not None and ref.data_base64.strip() != "":
            data = decode_base64_payload(ref.data_base64)
            if len(data) == 0:
                continue
            storage_object = save_storage_object(
                session,
                scope=MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPE,
                filename=name,
                content_type=content_type,
                data=data,
                now=now,
            )
            item["storage_object_id"] = storage_object.id
            item["path"] = storage_object.storage_path
            item["size"] = len(data)
        values.append(item)
    return values


def attachment_refs_json(refs: list[dict[str, object]]) -> str:
    return json.dumps(
        refs,
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


def row_attachment_refs(row: sqlite3.Row) -> list[dict[str, object]]:
    refs = json.loads(row["attachment_refs_json"])
    return refs if isinstance(refs, list) else []


def delete_tmp_storage_objects_for_refs(
    session: DatabaseSession,
    refs: list[dict[str, object]],
    *,
    now: str,
) -> None:
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        storage_object_id = ref.get("storage_object_id")
        if not isinstance(storage_object_id, str) or storage_object_id.strip() == "":
            continue
        storage_object = session.get(StorageObject, storage_object_id.strip())
        if storage_object is None or not is_mail_draft_attachment_storage_object(
            storage_object
        ):
            continue
        delete_storage_object(storage_object, session=session, now=now)


def delete_tmp_storage_objects_for_rows(rows: list[sqlite3.Row]) -> None:
    if not rows:
        return
    now = jst_iso()
    with runtime.SessionLocal() as session:
        for row in rows:
            delete_tmp_storage_objects_for_refs(
                session,
                row_attachment_refs(row),
                now=now,
            )
        session.commit()


def delete_mail_drafts_for_reply_target(reply_to_message_id: str | None) -> int:
    cleanup_expired_mail_drafts()
    with draft_connection() as connection:
        if reply_to_message_id is None:
            rows = connection.execute(
                "SELECT * FROM mail_drafts WHERE reply_to_message_id IS NULL"
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM mail_drafts WHERE reply_to_message_id = ?",
                (reply_to_message_id,),
            ).fetchall()
        delete_tmp_storage_objects_for_rows(rows)
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
        rows = connection.execute(
            "SELECT * FROM mail_drafts WHERE created_at < ?",
            (cutoff,),
        ).fetchall()
        delete_tmp_storage_objects_for_rows(rows)
        cursor = connection.execute(
            "DELETE FROM mail_drafts WHERE created_at < ?",
            (cutoff,),
        )
        connection.commit()
        return int(cursor.rowcount)


def resolved_attachment_data(
    session: DatabaseSession,
    ref: MailDraftAttachmentRefPayload,
) -> dict[str, object] | None:
    if ref.storage_object_id is not None and ref.storage_object_id.strip() != "":
        storage_object = session.get(StorageObject, ref.storage_object_id.strip())
        if storage_object is None or not is_mail_draft_attachment_storage_object(
            storage_object
        ):
            return None
        path = storage_object_absolute_path(storage_object, session)
        if not path.is_file():
            return None
        data = path.read_bytes()
        content_type = storage_object.content_type or normalize_content_type(None, path.name)
        return {
            "filename": ref.name.strip() or storage_object.original_filename or path.name,
            "path": storage_object.storage_path,
            "content_type": content_type,
            "data_base64": base64.b64encode(data).decode("ascii"),
            "size": len(data),
            "storage_object_id": storage_object.id,
        }

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
        "storage_object_id": None,
    }


@router.post("")
def create_mail_draft(
    payload: MailDraftPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    cleanup_expired_mail_drafts()
    now = jst_iso()
    draft_key = new_draft_key()
    attachments = stored_attachment_refs(session, payload.attachment_refs, now=now)
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
                attachment_refs_json(attachments),
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
    session.commit()

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
def delete_mail_draft(
    draft_key: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    with draft_connection() as connection:
        row = connection.execute(
            "SELECT * FROM mail_drafts WHERE key = ?",
            (draft_key,),
        ).fetchone()
        if row is None:
            raise json_error(404, "NOT_FOUND", "Mail draft not found.")
        delete_tmp_storage_objects_for_refs(
            session,
            row_attachment_refs(row),
            now=jst_iso(),
        )
        cursor = connection.execute(
            "DELETE FROM mail_drafts WHERE key = ?",
            (draft_key,),
        )
        connection.commit()
    session.commit()
    if cursor.rowcount == 0:
        raise json_error(404, "NOT_FOUND", "Mail draft not found.")
    return {"ok": True, "data": {"key": draft_key}}


@router.post("/attachments/resolve")
def resolve_mail_draft_attachments(
    payload: MailDraftAttachmentResolvePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    resolved = []
    missing = []
    for ref in payload.attachment_refs:
        if ref.name.strip() == "":
            continue
        attachment = resolved_attachment_data(session, ref)
        if attachment is None:
            missing.append({"name": ref.name, "path": ref.path or ref.name})
        else:
            resolved.append(attachment)
    return {"ok": True, "data": {"items": resolved, "missing": missing}}
