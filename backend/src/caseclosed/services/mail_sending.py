from __future__ import annotations

import json
import base64
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from mimetypes import guess_type
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy import update

from caseclosed.db import runtime
from caseclosed.db.models import Case
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import MailSendRequestCaseLink
from caseclosed.db.models import StorageObject
from caseclosed.mail_drafts import MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPES
from caseclosed.mail_drafts import delete_mail_drafts_for_reply_target
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.storage import storage_object_absolute_path


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def json_dict_list(value: str | None) -> list[dict[str, object]]:
    if value is None:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]


def google_gmail():
    from caseclosed import google_integration

    return google_integration


def fail_send_request_gmail(
    session,
    send_request: MailSendRequest,
    now: str,
    message: str,
) -> None:
    send_request.status = "failed_gmail"
    send_request.updated_at = now
    send_request.version += 1
    session.commit()
    raise RuntimeError(message)


def sent_references(reply_target: GmailMessage | None) -> str | None:
    if reply_target is None:
        return None
    references = reply_target.references_header or ""
    if reply_target.message_id_header is None:
        return references or None
    return " ".join(part for part in [references, reply_target.message_id_header] if part)


def handle_mail_send_mock(job: Job) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    send_request_id = payload["send_request_id"]
    now = runtime.jst_iso()

    with runtime.SessionLocal() as session:
        send_request = session.get(MailSendRequest, send_request_id)
        if send_request is None:
            raise LookupError(f"Mail send request not found: {send_request_id}")
        if send_request.sent_message_id is not None:
            return {
                "send_request_id": send_request.id,
                "sent_message_id": send_request.sent_message_id,
                "status": send_request.status,
                "idempotent": True,
            }
        if send_request.status == "canceled":
            return {
                "send_request_id": send_request.id,
                "sent_message_id": None,
                "status": send_request.status,
                "idempotent": True,
            }
        expected_version_value = payload.get("send_request_version")
        expected_version = (
            expected_version_value
            if isinstance(expected_version_value, int)
            else send_request.version
        )
        expected_scheduled_at = (
            payload.get("scheduled_at")
            if "scheduled_at" in payload
            else job.available_at
        )
        if send_request.version != expected_version:
            return superseded_send_result(send_request, "request_version_changed")
        if send_request.scheduled_at != expected_scheduled_at:
            return superseded_send_result(send_request, "scheduled_time_changed")
        if send_request.status not in {"scheduled_mock", "queued_mock", "ready_to_send"}:
            raise ValueError(
                f"Mail send request cannot be mock-sent from status: {send_request.status}"
            )
        if (
            send_request.scheduled_at is not None
            and runtime.parse_iso_datetime(send_request.scheduled_at) > runtime.jst_now()
        ):
            return superseded_send_result(send_request, "scheduled_time_not_reached")

        scheduled_at_condition = (
            MailSendRequest.scheduled_at.is_(None)
            if expected_scheduled_at is None
            else MailSendRequest.scheduled_at == expected_scheduled_at
        )
        claim_result = session.execute(
            update(MailSendRequest)
            .where(MailSendRequest.id == send_request.id)
            .where(MailSendRequest.version == expected_version)
            .where(MailSendRequest.status == send_request.status)
            .where(scheduled_at_condition)
            .values(
                status="sending_gmail",
                updated_at=now,
                version=MailSendRequest.version + 1,
            )
        )
        if claim_result.rowcount != 1:
            session.rollback()
            current = session.get(MailSendRequest, send_request.id)
            if current is None:
                raise LookupError(f"Mail send request not found: {send_request_id}")
            return superseded_send_result(current, "send_claim_lost")
        session.commit()
        session.expire_all()
        send_request = session.get(MailSendRequest, send_request_id)
        if send_request is None:
            raise LookupError(f"Mail send request not found: {send_request_id}")

        reply_target = (
            session.get(GmailMessage, send_request.reply_to_message_id)
            if send_request.reply_to_message_id is not None
            else None
        )
        if send_request.reply_to_message_id is not None and reply_target is None:
            raise LookupError(f"Reply target mail not found: {send_request.reply_to_message_id}")

        gmail = google_gmail()
        connected, can_send = gmail.gmail_connection_send_state(session)
        if not connected:
            fail_send_request_gmail(
                session,
                send_request,
                now,
                "Gmail is not connected. Connect Gmail from Management before sending mail.",
            )
        if not can_send:
            fail_send_request_gmail(
                session,
                send_request,
                now,
                "Gmail is connected without the gmail.send scope. "
                "Reconnect Gmail from Management to enable real sending.",
            )

        return send_request_via_gmail(session, send_request, reply_target, now)


def superseded_send_result(
    send_request: MailSendRequest,
    reason: str,
) -> dict[str, object]:
    return {
        "send_request_id": send_request.id,
        "sent_message_id": send_request.sent_message_id,
        "status": "superseded",
        "current_status": send_request.status,
        "reason": reason,
        "idempotent": True,
    }


def transfer_send_request_case_links(
    session,
    send_request: MailSendRequest,
    sent_message: GmailMessage,
    now: str,
) -> None:
    request_links = session.scalars(
        select(MailSendRequestCaseLink).where(
            MailSendRequestCaseLink.send_request_id == send_request.id
        )
    ).all()
    if not request_links:
        return
    messages = session.scalars(
        select(GmailMessage).where(GmailMessage.thread_id == sent_message.thread_id)
    ).all()
    message_ids = [message.id for message in messages]
    for request_link in request_links:
        existing_message_ids = set(
            session.scalars(
                select(CaseMailLink.message_id)
                .where(CaseMailLink.case_id == request_link.case_id)
                .where(CaseMailLink.message_id.in_(message_ids))
            ).all()
        )
        for message in messages:
            if message.id in existing_message_ids:
                continue
            session.add(
                CaseMailLink(
                    id=new_id("case_mail_link"),
                    case_id=request_link.case_id,
                    message_id=message.id,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
        case = session.get(Case, request_link.case_id)
        if case is not None:
            case.updated_at = now
            case.version += 1


def send_request_via_gmail(
    session,
    send_request: MailSendRequest,
    reply_target: GmailMessage | None,
    now: str,
) -> dict[str, object]:
    gmail = google_gmail()
    connection = gmail.read_setting_json(
        session,
        gmail.GMAIL_CONNECTION_KEY,
    ) or {}
    access_token = gmail.google_gmail_access_token(session, connection)
    profile = gmail.gmail_api_get_json("/users/me/profile", access_token)
    from_address = profile.get("emailAddress")
    if not isinstance(from_address, str) or from_address.strip() == "":
        raise RuntimeError("Gmail profile did not include an email address.")

    try:
        raw_message = build_gmail_raw_message(
            session,
            send_request,
            from_address=from_address.strip().lower(),
            reply_target=reply_target,
        )
        sent_response = gmail.gmail_api_send_raw_message(
            access_token,
            raw_message,
            thread_id=reply_target.gmail_thread_id if reply_target is not None else None,
        )
        gmail_message_id = sent_response.get("id")
        if not isinstance(gmail_message_id, str) or gmail_message_id.strip() == "":
            raise RuntimeError("Gmail send response did not include a message id.")
        sent_message = gmail.gmail_api_get_json(
            f"/users/me/messages/{gmail_message_id}",
            access_token,
            {"format": "full"},
        )
        result = ingest_mock_mail(
            session,
            gmail.gmail_message_to_mail_input(sent_message),
        )
    except Exception:
        send_request.status = "failed_gmail"
        send_request.updated_at = runtime.jst_iso()
        send_request.version += 1
        session.commit()
        raise

    send_request.sent_message_id = result.message_id
    sent_message = session.get(GmailMessage, result.message_id)
    if sent_message is None:
        raise RuntimeError("Sent Gmail message was not ingested.")
    transfer_send_request_case_links(
        session, send_request, sent_message, runtime.jst_iso()
    )
    send_request.status = "sent_gmail"
    send_request.updated_at = runtime.jst_iso()
    send_request.version += 1
    session.commit()
    delete_mail_drafts_for_reply_target(send_request.reply_to_message_id)
    return {
        "send_request_id": send_request.id,
        "sent_message_id": result.message_id,
        "status": send_request.status,
        "gmail_message_id": result.gmail_message_id,
        "idempotent": False,
    }


def build_gmail_raw_message(
    session,
    send_request: MailSendRequest,
    *,
    from_address: str,
    reply_target: GmailMessage | None,
) -> bytes:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = ", ".join(json_list(send_request.to_addresses_json))
    cc_addresses = json_list(send_request.cc_addresses_json)
    bcc_addresses = json_list(send_request.bcc_addresses_json)
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    if bcc_addresses:
        message["Bcc"] = ", ".join(bcc_addresses)
    message["Subject"] = send_request.subject or ""
    message["Date"] = formatdate(localtime=True)
    if reply_target is not None:
        if reply_target.message_id_header:
            message["In-Reply-To"] = reply_target.message_id_header
        references = sent_references(reply_target)
        if references is not None:
            message["References"] = references
    message.set_content(send_request.body_text)
    for attachment in json_dict_list(send_request.attachment_data_json):
        filename = attachment_filename(attachment)
        content_type = attachment_content_type(attachment, filename)
        content = attachment_content(session, attachment, filename)
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    return message.as_bytes(policy=SMTP)


def attachment_filename(attachment: dict[str, object]) -> str:
    filename = attachment.get("filename")
    if isinstance(filename, str) and filename.strip() != "":
        return filename.strip()
    raise RuntimeError("Attachment filename is missing.")


def attachment_content_type(attachment: dict[str, object], filename: str) -> str:
    content_type = attachment.get("content_type")
    if isinstance(content_type, str) and "/" in content_type:
        return content_type.strip()
    guessed_type, _ = guess_type(filename)
    return guessed_type or "application/octet-stream"


def attachment_content(
    session,
    attachment: dict[str, object],
    filename: str,
) -> bytes:
    storage_object_id = attachment.get("storage_object_id")
    if isinstance(storage_object_id, str) and storage_object_id.strip() != "":
        storage_object = session.get(StorageObject, storage_object_id.strip())
        if (
            storage_object is None
            or storage_object.status != "active"
            or storage_object.scope not in MAIL_DRAFT_ATTACHMENT_STORAGE_SCOPES
        ):
            raise RuntimeError(f"Attachment storage object is missing: {filename}")
        object_path = storage_object_absolute_path(storage_object, session)
        if not object_path.is_file():
            raise RuntimeError(f"Attachment storage file is missing: {filename}")
        return object_path.read_bytes()

    data_base64 = attachment.get("data_base64")
    if not isinstance(data_base64, str) or data_base64.strip() == "":
        raise RuntimeError(f"Attachment data is missing: {filename}")
    try:
        return base64.b64decode(data_base64, validate=True)
    except ValueError as error:
        raise RuntimeError(f"Attachment data is invalid: {filename}") from error
