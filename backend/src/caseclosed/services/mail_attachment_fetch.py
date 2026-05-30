from __future__ import annotations

import base64
import binascii
import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.auth import json_error
from caseclosed.db import runtime
from caseclosed.db.models import GmailMessageAttachment
from caseclosed.db.models import Job
from caseclosed.db.models import StorageObject
from caseclosed.storage import GMAIL_ATTACHMENT_STORAGE_SCOPE
from caseclosed.storage import delete_storage_object
from caseclosed.storage import save_storage_object
from caseclosed.storage import storage_object_absolute_path
from caseclosed.storage import storage_object_data

FUNCTION_TYPE = "mail_attachment_fetch"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def enqueue_mail_attachment_fetch_job(
    session,
    attachment: GmailMessageAttachment,
    now: str,
    *,
    target_scope: str = "managed",
    reason: str | None = None,
) -> str:
    existing_job_id = pending_mail_attachment_fetch_job_id(
        session,
        attachment.id,
        target_scope=target_scope,
    )
    if existing_job_id is not None:
        return existing_job_id

    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type=FUNCTION_TYPE,
            priority=90,
            status="pending",
            payload_json=json.dumps(
                {
                    "attachment_id": attachment.id,
                    "message_id": attachment.message_id,
                    "gmail_message_id": attachment.gmail_message_id,
                    "gmail_attachment_id": attachment.gmail_attachment_id,
                    "target_scope": target_scope,
                    "reason": reason,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            result_json=None,
            error_type=None,
            error_message=None,
            retry_count=0,
            max_retries=3,
            locked_by=None,
            locked_at=None,
            heartbeat_at=None,
            available_at=None,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    return job_id


def pending_mail_attachment_fetch_job_id(
    session,
    attachment_id: str,
    *,
    target_scope: str,
) -> str | None:
    jobs = session.scalars(
        select(Job)
        .where(Job.job_type == FUNCTION_TYPE)
        .where(Job.status.in_(["pending", "running", "stale"]))
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all()
    for job in jobs:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            continue
        if (
            payload.get("attachment_id") == attachment_id
            and payload.get("target_scope") == target_scope
        ):
            return job.id
    return None


def handle_mail_attachment_fetch(job: Job) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    attachment_id = payload["attachment_id"]
    target_scope = payload.get("target_scope") or "managed"
    if target_scope not in {"managed", GMAIL_ATTACHMENT_STORAGE_SCOPE}:
        raise ValueError(f"Unsupported attachment fetch target scope: {target_scope}")

    now = runtime.jst_iso()
    with runtime.SessionLocal() as session:
        attachment = session.get(GmailMessageAttachment, attachment_id)
        if attachment is None:
            raise LookupError(f"Mail attachment not found: {attachment_id}")

        existing_storage_object = (
            session.get(StorageObject, attachment.storage_object_id)
            if attachment.storage_object_id is not None
            else None
        )
        if (
            existing_storage_object is not None
            and existing_storage_object.status == "active"
            and existing_storage_object.scope == target_scope
            and storage_object_absolute_path(existing_storage_object, session).is_file()
        ):
            return {
                "attachment_id": attachment.id,
                "storage_object": storage_object_data(existing_storage_object, session),
                "cached": True,
            }

        raw_data: bytes | None = None
        content_type = attachment.mime_type or "application/octet-stream"
        if existing_storage_object is not None and existing_storage_object.status == "active":
            existing_path = storage_object_absolute_path(existing_storage_object, session)
            if existing_path.is_file():
                raw_data = existing_path.read_bytes()
                content_type = existing_storage_object.content_type or content_type

        if raw_data is None:
            raw_data = fetch_gmail_attachment_bytes(session, attachment)

        storage_object = save_storage_object(
            session,
            scope=target_scope,
            filename=attachment.filename,
            content_type=content_type,
            data=raw_data,
            now=now,
            source_type="mail_attachment",
            source_message_id=attachment.message_id,
        )
        if (
            existing_storage_object is not None
            and existing_storage_object.status == "active"
            and existing_storage_object.id != storage_object.id
            and existing_storage_object.scope != target_scope
        ):
            delete_storage_object(existing_storage_object, session=session, now=now)
        attachment.storage_object_id = storage_object.id
        attachment.byte_size = len(raw_data)
        attachment.updated_at = now
        attachment.version += 1
        session.commit()
        return {
            "attachment_id": attachment.id,
            "storage_object": storage_object_data(storage_object, session),
            "cached": False,
        }


def fetch_gmail_attachment_bytes(
    session,
    attachment: GmailMessageAttachment,
) -> bytes:
    from caseclosed import google_integration

    connection = google_integration.read_setting_json(
        session,
        google_integration.GMAIL_CONNECTION_KEY,
    ) or {}
    access_token = google_integration.google_gmail_access_token(session, connection)
    data = google_integration.gmail_api_get_json(
        f"/users/me/messages/{attachment.gmail_message_id}/attachments/{attachment.gmail_attachment_id}",
        access_token,
    )
    encoded_data = data.get("data")
    if not isinstance(encoded_data, str) or encoded_data.strip() == "":
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            "Gmail attachment data is missing.",
        )
    try:
        return base64.urlsafe_b64decode(
            (encoded_data + "=" * (-len(encoded_data) % 4)).encode("ascii")
        )
    except (binascii.Error, ValueError) as error:
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            "Gmail attachment data is invalid.",
        ) from error
