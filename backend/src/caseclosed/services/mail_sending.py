from __future__ import annotations

import json
from uuid import uuid4

from caseclosed.db import runtime
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailSendRequest
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import ingest_mock_mail

MOCK_FROM_ADDRESS = "caseclosed.me@example.local"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


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
        if send_request.status not in {"scheduled_mock", "queued_mock", "ready_to_send"}:
            raise ValueError(
                f"Mail send request cannot be mock-sent from status: {send_request.status}"
            )

        reply_target = (
            session.get(GmailMessage, send_request.reply_to_message_id)
            if send_request.reply_to_message_id is not None
            else None
        )
        if send_request.reply_to_message_id is not None and reply_target is None:
            raise LookupError(f"Reply target mail not found: {send_request.reply_to_message_id}")

        send_request.status = "sending_mock"
        send_request.updated_at = now
        send_request.version += 1
        session.flush()

        gmail_thread_id = (
            reply_target.gmail_thread_id
            if reply_target is not None
            else f"mock_sent_thread_{send_request.id}"
        )
        result = ingest_mock_mail(
            session,
            MockMailInput(
                gmail_message_id=f"mock_sent_{send_request.id}",
                gmail_thread_id=gmail_thread_id,
                message_id_header=f"<{send_request.id}@caseclosed.local>",
                subject=send_request.subject,
                from_address=MOCK_FROM_ADDRESS,
                to_addresses=json_list(send_request.to_addresses_json),
                cc_addresses=json_list(send_request.cc_addresses_json),
                bcc_addresses=json_list(send_request.bcc_addresses_json),
                received_at=now,
                body_text=send_request.body_text,
                gmail_labels=["SENT"],
                in_reply_to_header=(
                    reply_target.message_id_header if reply_target is not None else None
                ),
                references_header=sent_references(reply_target),
                gmail_link=f"mock://mail/{send_request.id}",
            ),
        )

        send_request.sent_message_id = result.message_id
        send_request.status = "sent_mock"
        send_request.updated_at = now
        send_request.version += 1
        session.commit()

        return {
            "send_request_id": send_request.id,
            "sent_message_id": result.message_id,
            "status": send_request.status,
            "idempotent": False,
        }
