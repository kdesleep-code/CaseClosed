from __future__ import annotations

import base64
import binascii
import json
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactTag
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailUserState
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import jst_iso
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import apply_contact_mail_importance_rule
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.services.mail_ingestion import message_is_sent
from caseclosed.services.mail_summary import SUMMARY_TARGET_IMPORTANCE
from caseclosed.services.mail_summary import enqueue_mail_summary_job

router = APIRouter(prefix="/api/v1/mails", tags=["mails"])


class MockMailIngestRequest(BaseModel):
    gmail_message_id: str
    gmail_thread_id: str
    from_address: str
    received_at: str | None = None
    subject: str | None = None
    from_name: str | None = None
    sender_address: str | None = None
    reply_to_address: str | None = None
    to_addresses: list[str] | None = None
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    message_id_header: str | None = None
    in_reply_to_header: str | None = None
    references_header: str | None = None
    list_id: str | None = None
    internal_date: str | None = None
    snippet: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    gmail_link: str | None = None
    gmail_labels: list[str] | None = None
    external_starred: bool = False


class MailImportanceRequest(BaseModel):
    importance: str


class MailProcessRequest(BaseModel):
    reason: str | None = None


class MailSendRequestPayload(BaseModel):
    to_addresses: list[str]
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    subject: str | None = None
    body_text: str
    attachment_names: list[str] | None = None
    reply_to_message_id: str | None = None
    scheduled_at: str | None = None


class MailSendSchedulePayload(BaseModel):
    scheduled_at: str


IMPORTANCE_RANKS = {
    "pinned": 0,
    "high": 1,
    "middle": 2,
    "low": 3,
    "unclassified": 4,
    "pending": 5,
    "skip": 6,
    "sent": 7,
}

SEND_REQUEST_VISIBLE_STATUSES = {"scheduled_mock", "queued_mock", "sending_mock"}
MOCK_FROM_ADDRESS = "caseclosed.me@example.local"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def mock_mail_result_data(result: MailIngestionResult) -> dict[str, object]:
    return {
        "message_id": result.message_id,
        "gmail_message_id": result.gmail_message_id,
        "pending": result.pending,
        "pending_address": result.pending_address,
        "pending_reason": result.pending_reason,
        "queued_job_id": result.queued_job_id,
    }


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []

    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def normalize_email_address(email_address: str) -> str:
    return email_address.strip().lower()


def normalize_address_list(addresses: list[str] | None) -> list[str]:
    if addresses is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        cleaned = address.strip()
        if cleaned == "":
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def mail_send_request_data(send_request: MailSendRequest) -> dict[str, object]:
    return {
        "id": send_request.id,
        "status": send_request.status,
        "to_addresses": json_list(send_request.to_addresses_json),
        "cc_addresses": json_list(send_request.cc_addresses_json),
        "bcc_addresses": json_list(send_request.bcc_addresses_json),
        "subject": send_request.subject,
        "body_text": send_request.body_text,
        "attachment_names": json_list(send_request.attachment_names_json),
        "reply_to_message_id": send_request.reply_to_message_id,
        "sent_message_id": send_request.sent_message_id,
        "scheduled_at": send_request.scheduled_at,
        "created_at": send_request.created_at,
        "updated_at": send_request.updated_at,
        "version": send_request.version,
    }


def send_request_thread_id(send_request: MailSendRequest) -> str:
    return f"provisional_thread_{send_request.id}"


def send_request_visible_at(send_request: MailSendRequest) -> str:
    return send_request.scheduled_at or send_request.created_at


def send_request_matches_query(send_request: MailSendRequest, tokens: list[str]) -> bool:
    searchable_values = [
        send_request.subject,
        send_request.body_text,
        send_request.to_addresses_json,
        send_request.cc_addresses_json,
        send_request.bcc_addresses_json,
        send_request.attachment_names_json,
    ]
    searchable_text = "\n".join(value for value in searchable_values if value).lower()
    return all(token in searchable_text for token in tokens)


def send_request_list_item_data(send_request: MailSendRequest) -> dict[str, object]:
    visible_at = send_request_visible_at(send_request)
    return {
        "id": send_request.id,
        "gmail_message_id": f"provisional:{send_request.id}",
        "gmail_thread_id": send_request_thread_id(send_request),
        "thread_id": send_request_thread_id(send_request),
        "received_at": visible_at,
        "received_date": visible_at[:10],
        "subject": send_request.subject,
        "from_address": MOCK_FROM_ADDRESS,
        "from_name": "CaseClosed",
        "reply_to_address": None,
        "list_id": None,
        "processed_status": "processed",
        "read_status": "read",
        "read_at": send_request.created_at,
        "user_importance": None,
        "effective_importance": "sent",
        "importance_rank": IMPORTANCE_RANKS["sent"],
        "external_importance": None,
        "suggested_importance": None,
        "llm_run_id": None,
        "pending_reason": None,
        "sender_contact": None,
        "case_links": [],
        "summary": None,
    }


def send_request_message_data(send_request: MailSendRequest) -> dict[str, object]:
    visible_at = send_request_visible_at(send_request)
    thread_id = send_request_thread_id(send_request)
    to_addresses = json_list(send_request.to_addresses_json)
    cc_addresses = json_list(send_request.cc_addresses_json)
    bcc_addresses = json_list(send_request.bcc_addresses_json)
    return {
        "id": send_request.id,
        "gmail_message_id": f"provisional:{send_request.id}",
        "gmail_thread_id": thread_id,
        "thread_id": thread_id,
        "received_at": visible_at,
        "received_date": visible_at[:10],
        "subject": send_request.subject,
        "from_address": MOCK_FROM_ADDRESS,
        "from_name": "CaseClosed",
        "from_contact": None,
        "sender_contact": None,
        "sender_address": None,
        "reply_to_address": None,
        "to_addresses": to_addresses,
        "cc_addresses": cc_addresses,
        "bcc_addresses": bcc_addresses,
        "to_recipients": [{"email_address": address, "contact": None} for address in to_addresses],
        "cc_recipients": [{"email_address": address, "contact": None} for address in cc_addresses],
        "bcc_recipients": [{"email_address": address, "contact": None} for address in bcc_addresses],
        "message_id_header": None,
        "in_reply_to_header": None,
        "references_header": None,
        "list_id": None,
        "snippet": send_request.body_text[:160],
        "gmail_link": None,
        "external_starred": False,
        "gmail_labels": ["SENT"],
        "body_text": send_request.body_text,
        "body_html": None,
        "processed_status": "processed",
        "read_status": "read",
        "read_at": send_request.created_at,
        "user_importance": None,
        "effective_importance": "sent",
        "importance_rank": IMPORTANCE_RANKS["sent"],
        "external_importance": None,
        "suggested_importance": None,
        "llm_run_id": None,
        "pending_reason": None,
        "created_at": send_request.created_at,
        "updated_at": send_request.updated_at,
        "version": send_request.version,
    }


def send_request_detail_data(send_request: MailSendRequest) -> dict[str, object]:
    message = send_request_message_data(send_request)
    user_state = {
        "user_importance": None,
        "processed_status": "processed",
        "processed_at": send_request.created_at,
        "read_status": "read",
        "read_at": send_request.created_at,
        "version": send_request.version,
    }
    auto_state = {
        "external_importance": None,
        "suggested_importance": None,
        "llm_run_id": None,
        "effective_importance": "sent",
        "pending_reason": None,
    }
    return {
        "message": message,
        "thread_messages": [],
        "scheduled_send_requests": [mail_send_request_data(send_request)],
        "user_state": user_state,
        "auto_state": auto_state,
        "summary": None,
        "case_links": [],
        "attachments": [],
        "drafts": [],
        "available_actions": [],
    }


def enqueue_mail_send_mock_job(
    session: DatabaseSession,
    send_request: MailSendRequest,
    now: str,
    *,
    available_at: str | None = None,
) -> str:
    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type="mail_send_mock",
            priority=80,
            status="pending",
            payload_json=json.dumps(
                {"send_request_id": send_request.id},
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
            available_at=available_at,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    return job_id


def contact_tags(session: DatabaseSession, contact_id: str) -> list[str]:
    return list(
        session.scalars(
            select(ContactTag.tag)
            .where(ContactTag.contact_id == contact_id)
            .order_by(ContactTag.tag)
        ).all()
    )


def contact_summary(
    contact: Contact,
    session: DatabaseSession | None = None,
) -> dict[str, object]:
    return {
        "id": contact.id,
        "display_name": contact.display_name,
        "avatar_url": contact.avatar_url,
        "kind": contact.kind,
        "tags": contact_tags(session, contact.id) if session is not None else [],
    }


def contact_for_address(
    session: DatabaseSession,
    email_address: str,
) -> Contact | None:
    return session.execute(
        select(Contact)
        .join(ContactEmailAddress, ContactEmailAddress.contact_id == Contact.id)
        .where(
            ContactEmailAddress.normalized_email_address
            == normalize_email_address(email_address),
            ContactEmailAddress.deleted_at.is_(None),
            Contact.deleted_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()


def recipient_data(
    session: DatabaseSession,
    email_address: str,
) -> dict[str, object]:
    contact = contact_for_address(session, email_address)
    return {
        "email_address": email_address,
        "contact": contact_summary(contact, session) if contact is not None else None,
    }


def recipient_list_data(
    session: DatabaseSession,
    email_addresses: list[str],
) -> list[dict[str, object]]:
    return [recipient_data(session, email_address) for email_address in email_addresses]


def message_data(
    message: GmailMessage,
    *,
    include_body: bool = False,
    session: DatabaseSession | None = None,
    user_state: MailUserState | None = None,
    auto_state: MailAutoState | None = None,
) -> dict[str, object]:
    to_addresses = json_list(message.to_addresses_json)
    cc_addresses = json_list(message.cc_addresses_json)
    bcc_addresses = json_list(message.bcc_addresses_json)
    from_contact = contact_for_address(session, message.from_address) if session else None
    data = {
        "id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "gmail_thread_id": message.gmail_thread_id,
        "thread_id": message.thread_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "from_name": message.from_name,
        "from_contact": (
            contact_summary(from_contact, session) if from_contact is not None else None
        ),
        "sender_contact": (
            contact_summary(from_contact, session) if from_contact is not None else None
        ),
        "sender_address": message.sender_address,
        "reply_to_address": message.reply_to_address,
        "to_addresses": to_addresses,
        "cc_addresses": cc_addresses,
        "bcc_addresses": bcc_addresses,
        "message_id_header": message.message_id_header,
        "in_reply_to_header": message.in_reply_to_header,
        "references_header": message.references_header,
        "list_id": message.list_id,
        "snippet": message.snippet,
        "gmail_link": message.gmail_link,
        "external_starred": bool(message.external_starred),
        "gmail_labels": json_list(message.gmail_labels_json),
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "version": message.version,
    }
    if user_state is not None:
        data["processed_status"] = user_state.processed_status
        data["read_status"] = user_state.read_status
        data["read_at"] = user_state.read_at
        data["user_importance"] = user_state.user_importance
    if auto_state is not None:
        effective_importance = (
            user_state.user_importance
            if user_state is not None and user_state.user_importance is not None
            else auto_state.effective_importance
        )
        data["effective_importance"] = effective_importance
        data["importance_rank"] = IMPORTANCE_RANKS.get(
            effective_importance,
            99,
        )
        data["external_importance"] = auto_state.external_importance
        data["suggested_importance"] = auto_state.suggested_importance
        data["llm_run_id"] = auto_state.llm_run_id
        data["pending_reason"] = auto_state.pending_reason
    if session is not None:
        data["to_recipients"] = recipient_list_data(session, to_addresses)
        data["cc_recipients"] = recipient_list_data(session, cc_addresses)
        data["bcc_recipients"] = recipient_list_data(session, bcc_addresses)
    if include_body:
        data["body_text"] = message.body_text
        data["body_html"] = message.body_html
    return data


def user_state_data(user_state: MailUserState) -> dict[str, object]:
    return {
        "id": user_state.id,
        "message_id": user_state.message_id,
        "user_importance": user_state.user_importance,
        "processed_status": user_state.processed_status,
        "processed_at": user_state.processed_at,
        "read_status": user_state.read_status,
        "read_at": user_state.read_at,
        "updated_at": user_state.updated_at,
        "version": user_state.version,
    }


def auto_state_data(
    auto_state: MailAutoState,
    user_state: MailUserState | None = None,
) -> dict[str, object]:
    effective_importance = (
        user_state.user_importance
        if user_state is not None and user_state.user_importance is not None
        else auto_state.effective_importance
    )
    return {
        "id": auto_state.id,
        "message_id": auto_state.message_id,
        "external_importance": auto_state.external_importance,
        "suggested_importance": auto_state.suggested_importance,
        "llm_run_id": auto_state.llm_run_id,
        "effective_importance": effective_importance,
        "pending_reason": auto_state.pending_reason,
        "pending_from_address_id": auto_state.pending_from_address_id,
        "updated_at": auto_state.updated_at,
        "version": auto_state.version,
    }


def mail_summary_data(summary: MailSummary) -> dict[str, object]:
    return {
        "id": summary.id,
        "message_id": summary.message_id,
        "summary_text": summary.summary_text,
        "action_required": bool(summary.action_required)
        if summary.action_required is not None
        else None,
        "deadline_text": summary.deadline_text,
        "next_action": summary.next_action,
        "key_points": json_list(summary.key_points_json),
        "translation_text": summary.translation_text,
        "language": summary.language,
        "llm_run_id": summary.llm_run_id,
        "updated_at": summary.updated_at,
        "version": summary.version,
    }


def combined_thread_summary_data(summaries: list[MailSummary]) -> dict[str, object] | None:
    if len(summaries) == 0:
        return None
    return {
        "summary_text": "\n".join(summary.summary_text for summary in summaries),
        "items": [mail_summary_data(summary) for summary in summaries],
    }


def latest_thread_summary(
    session: DatabaseSession,
    thread_id: str,
) -> MailSummary | None:
    return session.scalar(
        select(MailSummary)
        .join(GmailMessage, GmailMessage.id == MailSummary.message_id)
        .where(GmailMessage.thread_id == thread_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
        .limit(1)
    )


def get_mail_bundle(
    session: DatabaseSession,
    message_id: str,
) -> tuple[GmailMessage, MailUserState, MailAutoState]:
    message = session.get(GmailMessage, message_id)
    if message is None:
        raise json_error(404, "NOT_FOUND", "Mail not found.")
    user_state = session.scalar(
        select(MailUserState).where(MailUserState.message_id == message.id)
    )
    auto_state = session.scalar(
        select(MailAutoState).where(MailAutoState.message_id == message.id)
    )
    if user_state is None or auto_state is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Mail state is missing.")
    return message, user_state, auto_state


def normalize_importance(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "pinned":
        return "pinned"
    if normalized == "high":
        return "high"
    if normalized == "middle":
        return "middle"
    if normalized == "low":
        return "low"
    if normalized == "skip":
        return "skip"
    raise json_error(422, "VALIDATION_ERROR", "Invalid mail importance.")


def normalize_importance_filter(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"pending", "unclassified"}:
        return normalized
    return normalize_importance(normalized)


def normalize_processed_filter(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"all", "0", "1", "unprocessed", "processed"}:
        return normalized
    raise json_error(422, "VALIDATION_ERROR", "Invalid processed filter.")


def normalize_contact_status_filter(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"all", "pending", "resolved"}:
        return normalized
    raise json_error(422, "VALIDATION_ERROR", "Invalid contact status filter.")


def normalize_read_filter(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"all", "read", "unread"}:
        return normalized
    raise json_error(422, "VALIDATION_ERROR", "Invalid read filter.")


def normalize_tab_filter(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"all", "pending", "unprocessed", "processed", "skip"}:
        return normalized
    raise json_error(422, "VALIDATION_ERROR", "Invalid mail tab filter.")


def normalize_limit(limit: int) -> int:
    if limit < 1:
        raise json_error(422, "VALIDATION_ERROR", "Limit must be positive.")
    return min(limit, 100)


def encode_cursor(message: GmailMessage) -> str:
    return encode_cursor_values(message.received_at, message.id)


def encode_cursor_values(received_at: str, item_id: str) -> str:
    payload = json.dumps(
        {"received_at": received_at, "id": item_id},
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded_cursor = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded_cursor.encode("ascii")).decode("utf-8")
        )
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        raise json_error(422, "VALIDATION_ERROR", "Invalid cursor.") from None

    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("received_at"), str)
        or not isinstance(payload.get("id"), str)
    ):
        raise json_error(422, "VALIDATION_ERROR", "Invalid cursor.")
    return payload["received_at"], payload["id"]


def row_matches_query(message: GmailMessage, tokens: list[str]) -> bool:
    searchable_values = [
        message.subject,
        message.from_address,
        message.from_name,
        message.sender_address,
        message.reply_to_address,
        message.to_addresses_json,
        message.cc_addresses_json,
        message.bcc_addresses_json,
        message.message_id_header,
        message.list_id,
        message.body_text,
        message.snippet,
    ]
    searchable_text = "\n".join(value for value in searchable_values if value)
    searchable_text = searchable_text.lower()
    return all(token in searchable_text for token in tokens)


def aggregate_thread_rows(
    rows: list[tuple[GmailMessage, MailUserState, MailAutoState]],
) -> list[tuple[GmailMessage, MailUserState, MailAutoState, str, str, str | None]]:
    thread_rows: dict[str, list[tuple[GmailMessage, MailUserState, MailAutoState]]] = {}
    for message, user_state, auto_state in rows:
        if message_is_sent(message):
            continue
        thread_rows.setdefault(message.thread_id, []).append(
            (message, user_state, auto_state)
        )

    aggregated_rows: list[
        tuple[GmailMessage, MailUserState, MailAutoState, str, str, str | None]
    ] = []
    for thread_group in thread_rows.values():
        latest_message, latest_user_state, latest_auto_state = max(
            thread_group,
            key=lambda row: (row[0].received_at, row[0].id),
        )
        importance_candidates = [
            row[1].user_importance or row[2].effective_importance
            for row in thread_group
            if (row[1].user_importance or row[2].effective_importance) != "skip"
        ]
        if not importance_candidates:
            effective_importance = "skip"
        else:
            effective_importance = min(
                importance_candidates,
                key=lambda importance: IMPORTANCE_RANKS.get(importance, 99),
            )
        thread_read_status = (
            "unread"
            if any(row[1].read_status == "unread" for row in thread_group)
            else "read"
        )
        thread_read_at = (
            None
            if thread_read_status == "unread"
            else max(
                (row[1].read_at for row in thread_group if row[1].read_at is not None),
                default=None,
            )
        )
        aggregated_rows.append(
            (
                latest_message,
                latest_user_state,
                latest_auto_state,
                effective_importance,
                thread_read_status,
                thread_read_at,
            )
        )
    return sorted(
        aggregated_rows,
        key=lambda row: (row[0].received_at, row[0].id),
        reverse=True,
    )


def send_only_requests(session: DatabaseSession) -> list[MailSendRequest]:
    return session.scalars(
        select(MailSendRequest)
        .where(
            MailSendRequest.reply_to_message_id.is_(None),
            MailSendRequest.sent_message_id.is_(None),
            MailSendRequest.scheduled_at.is_not(None),
            MailSendRequest.status.in_(list(SEND_REQUEST_VISIBLE_STATUSES)),
        )
        .order_by(MailSendRequest.created_at.desc(), MailSendRequest.id.desc())
    ).all()


def available_actions(
    user_state: MailUserState,
    auto_state: MailAutoState,
) -> list[str]:
    if auto_state.pending_reason is not None:
        return ["resolve_contact"]
    actions = ["set_importance"]
    if user_state.processed_status == "processed":
        actions.append("unprocess")
    else:
        actions.append("process")
    return actions


def refresh_pending_mail_state(
    session: DatabaseSession,
    message: GmailMessage,
    auto_state: MailAutoState,
) -> tuple[bool, str, str | None]:
    if auto_state.pending_reason is None:
        return False, "not_pending", None
    if auto_state.pending_from_address_id is None:
        return False, "pending_address_missing", None

    email_address = session.get(ContactEmailAddress, auto_state.pending_from_address_id)
    if email_address is None or email_address.deleted_at is not None:
        return False, "pending_address_not_found", None
    if email_address.resolution_status != "linked" or email_address.contact_id is None:
        return False, "pending_address_unresolved", None

    contact = session.get(Contact, email_address.contact_id)
    if contact is None or contact.deleted_at is not None:
        return False, "pending_contact_not_found", None

    now = jst_iso()
    result = apply_contact_mail_importance_rule(
        session,
        message=message,
        auto_state=auto_state,
        contact=contact,
        now=now,
    )
    reason = "released" if result.reason == "released_to_importance_job" else result.reason
    return True, reason, result.queued_job_id


def detail_data(
    session: DatabaseSession,
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
) -> dict[str, object]:
    thread_messages = session.scalars(
        select(GmailMessage)
        .where(GmailMessage.thread_id == message.thread_id)
        .order_by(GmailMessage.received_at, GmailMessage.id)
    ).all()
    user_states = {
        state.message_id: state
        for state in session.scalars(
            select(MailUserState).where(
                MailUserState.message_id.in_([thread_message.id for thread_message in thread_messages])
            )
        ).all()
    }
    auto_states = {
        state.message_id: state
        for state in session.scalars(
            select(MailAutoState).where(
                MailAutoState.message_id.in_([thread_message.id for thread_message in thread_messages])
            )
        ).all()
    }
    summaries = session.scalars(
        select(MailSummary)
        .where(
            MailSummary.message_id.in_(
                [thread_message.id for thread_message in thread_messages]
            )
        )
        .join(GmailMessage, GmailMessage.id == MailSummary.message_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    scheduled_send_requests = session.scalars(
        select(MailSendRequest)
        .where(
            MailSendRequest.reply_to_message_id.in_(
                [thread_message.id for thread_message in thread_messages]
            ),
            MailSendRequest.sent_message_id.is_(None),
            MailSendRequest.scheduled_at.is_not(None),
            MailSendRequest.status.in_(
                ["scheduled_mock", "queued_mock", "sending_mock"]
            ),
        )
        .order_by(MailSendRequest.scheduled_at, MailSendRequest.created_at, MailSendRequest.id)
    ).all()
    return {
        "message": message_data(
            message,
            include_body=True,
            session=session,
            user_state=user_state,
            auto_state=auto_state,
        ),
        "thread_messages": [
            message_data(
                thread_message,
                include_body=True,
                session=session,
                user_state=user_states.get(thread_message.id),
                auto_state=auto_states.get(thread_message.id),
            )
            for thread_message in thread_messages
        ],
        "scheduled_send_requests": [
            mail_send_request_data(send_request)
            for send_request in scheduled_send_requests
        ],
        "user_state": user_state_data(user_state),
        "auto_state": auto_state_data(auto_state, user_state),
        "summary": combined_thread_summary_data(list(summaries)),
        "case_links": [],
        "attachments": [],
        "drafts": [],
        "available_actions": available_actions(user_state, auto_state),
    }


def list_item_data(
    session: DatabaseSession,
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
    *,
    effective_importance_override: str | None = None,
    read_status_override: str | None = None,
    read_at_override: str | None = None,
) -> dict[str, object]:
    effective_importance = (
        effective_importance_override
        or user_state.user_importance
        or auto_state.effective_importance
    )
    contact_row = contact_for_address(session, message.from_address)
    is_sent = message_is_sent(message)
    summary = latest_thread_summary(session, message.thread_id)
    return {
        "id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "gmail_thread_id": message.gmail_thread_id,
        "thread_id": message.thread_id,
        "received_at": message.received_at,
        "received_date": message.received_at[:10],
        "subject": message.subject,
        "from_address": message.from_address,
        "from_name": message.from_name,
        "reply_to_address": message.reply_to_address,
        "list_id": message.list_id,
        "processed_status": user_state.processed_status,
        "read_status": read_status_override or user_state.read_status,
        "read_at": read_at_override if read_status_override is not None else user_state.read_at,
        "user_importance": user_state.user_importance,
        "effective_importance": effective_importance,
        "importance_rank": IMPORTANCE_RANKS.get(effective_importance, 99),
        "external_importance": auto_state.external_importance,
        "suggested_importance": auto_state.suggested_importance,
        "llm_run_id": auto_state.llm_run_id,
        "pending_reason": auto_state.pending_reason,
        "sender_contact": (
            contact_summary(contact_row, session)
            if contact_row is not None
            else None
        ),
        "case_links": [],
        "summary": None
        if is_sent or effective_importance not in SUMMARY_TARGET_IMPORTANCE
        else (summary.summary_text if summary is not None else None),
    }


@router.post("/mock-ingest")
def mock_ingest_mail(
    payload: MockMailIngestRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if payload.gmail_message_id.strip() == "":
        raise json_error(422, "VALIDATION_ERROR", "Gmail message ID is required.")
    if payload.gmail_thread_id.strip() == "":
        raise json_error(422, "VALIDATION_ERROR", "Gmail thread ID is required.")
    if payload.from_address.strip() == "":
        raise json_error(422, "VALIDATION_ERROR", "From address is required.")

    result = ingest_mock_mail(
        session,
        MockMailInput(
            gmail_message_id=payload.gmail_message_id.strip(),
            gmail_thread_id=payload.gmail_thread_id.strip(),
            from_address=payload.from_address,
            received_at=payload.received_at or jst_iso(),
            subject=payload.subject,
            from_name=payload.from_name,
            sender_address=payload.sender_address,
            reply_to_address=payload.reply_to_address,
            to_addresses=payload.to_addresses,
            cc_addresses=payload.cc_addresses,
            bcc_addresses=payload.bcc_addresses,
            message_id_header=payload.message_id_header,
            in_reply_to_header=payload.in_reply_to_header,
            references_header=payload.references_header,
            list_id=payload.list_id,
            internal_date=payload.internal_date,
            snippet=payload.snippet,
            body_text=payload.body_text,
            body_html=payload.body_html,
            gmail_link=payload.gmail_link,
            gmail_labels=payload.gmail_labels,
            external_starred=payload.external_starred,
        ),
    )
    return {"ok": True, "data": mock_mail_result_data(result)}


@router.post("/send")
def send_mail(
    payload: MailSendRequestPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    to_addresses = normalize_address_list(payload.to_addresses)
    if len(to_addresses) == 0:
        raise json_error(422, "VALIDATION_ERROR", "At least one recipient is required.")

    body_text = payload.body_text
    if body_text.strip() == "":
        raise json_error(422, "VALIDATION_ERROR", "Body text is required.")

    if payload.reply_to_message_id is not None:
        reply_to_message = session.get(GmailMessage, payload.reply_to_message_id)
        if reply_to_message is None:
            raise json_error(404, "NOT_FOUND", "Reply target mail not found.")

    now = jst_iso()
    scheduled_at = (
        payload.scheduled_at.strip()
        if payload.scheduled_at is not None and payload.scheduled_at.strip() != ""
        else jst_iso(jst_now() + timedelta(minutes=1))
    )
    send_request = MailSendRequest(
        id=new_id("mail_send"),
        status="scheduled_mock",
        to_addresses_json=json.dumps(to_addresses, ensure_ascii=True),
        cc_addresses_json=json.dumps(
            normalize_address_list(payload.cc_addresses),
            ensure_ascii=True,
        ),
        bcc_addresses_json=json.dumps(
            normalize_address_list(payload.bcc_addresses),
            ensure_ascii=True,
        ),
        subject=payload.subject,
        body_text=body_text,
        attachment_names_json=json.dumps(
            [name.strip() for name in payload.attachment_names or [] if name.strip() != ""],
            ensure_ascii=True,
        ),
        reply_to_message_id=payload.reply_to_message_id,
        sent_message_id=None,
        scheduled_at=scheduled_at,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(send_request)
    enqueue_mail_send_mock_job(
        session,
        send_request,
        now,
        available_at=scheduled_at,
    )
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.get("/send-requests")
def list_mail_send_requests(
    limit: int = 50,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized_limit = max(1, min(limit, 200))
    send_requests = session.scalars(
        select(MailSendRequest)
        .order_by(MailSendRequest.created_at.desc(), MailSendRequest.id.desc())
        .limit(normalized_limit)
    ).all()
    return {
        "ok": True,
        "data": {
            "items": [
                mail_send_request_data(send_request)
                for send_request in send_requests
            ],
        },
    }


def get_send_request_or_404(
    session: DatabaseSession,
    send_request_id: str,
) -> MailSendRequest:
    send_request = session.get(MailSendRequest, send_request_id)
    if send_request is None:
        raise json_error(404, "NOT_FOUND", "Mail send request not found.")
    return send_request


def ensure_send_request_mutable(send_request: MailSendRequest) -> None:
    if send_request.status in {"sent_mock", "sending_mock", "canceled"}:
        raise json_error(409, "CONFLICT", "Mail send request cannot be changed.")


@router.post("/send-requests/{send_request_id}/send-now")
def send_mail_request_now(
    send_request_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    send_request = get_send_request_or_404(session, send_request_id)
    ensure_send_request_mutable(send_request)
    now = jst_iso()
    send_request.status = "queued_mock"
    send_request.scheduled_at = None
    send_request.updated_at = now
    send_request.version += 1
    enqueue_mail_send_mock_job(session, send_request, now)
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.patch("/send-requests/{send_request_id}/schedule")
def reschedule_mail_request(
    send_request_id: str,
    payload: MailSendSchedulePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    send_request = get_send_request_or_404(session, send_request_id)
    ensure_send_request_mutable(send_request)
    scheduled_at = payload.scheduled_at.strip()
    if scheduled_at == "":
        raise json_error(422, "VALIDATION_ERROR", "Scheduled time is required.")

    now = jst_iso()
    send_request.status = "scheduled_mock"
    send_request.scheduled_at = scheduled_at
    send_request.updated_at = now
    send_request.version += 1
    enqueue_mail_send_mock_job(session, send_request, now, available_at=scheduled_at)
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.post("/send-requests/{send_request_id}/cancel")
def cancel_mail_send_request(
    send_request_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    send_request = get_send_request_or_404(session, send_request_id)
    if send_request.status in {"sent_mock", "sending_mock"}:
        raise json_error(409, "CONFLICT", "Mail send request cannot be canceled.")
    now = jst_iso()
    send_request.status = "canceled"
    send_request.updated_at = now
    send_request.version += 1
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.get("")
def list_mails(
    tab: str = "all",
    processed: str = "all",
    importance: str = "all",
    contact_status: str = "all",
    read: str = "all",
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized_tab = normalize_tab_filter(tab)
    normalized_processed = normalize_processed_filter(processed)
    normalized_contact_status = normalize_contact_status_filter(contact_status)
    normalized_read = normalize_read_filter(read)
    normalized_limit = normalize_limit(limit)
    statement = (
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id)
    )
    all_rows = session.execute(statement).all()
    query_tokens = [token.lower() for token in q.strip().split()] if q else []
    if query_tokens:
        matching_thread_ids = {
            message.thread_id
            for message, _, _ in all_rows
            if not message_is_sent(message) and row_matches_query(message, query_tokens)
        }
        all_rows = [
            row
            for row in all_rows
            if row[0].thread_id in matching_thread_ids
        ]

    aggregated_rows = aggregate_thread_rows(all_rows)
    if normalized_processed in {"0", "unprocessed"}:
        aggregated_rows = [
            row for row in aggregated_rows if row[1].processed_status == "unprocessed"
        ]
    elif normalized_processed in {"1", "processed"}:
        aggregated_rows = [
            row for row in aggregated_rows if row[1].processed_status == "processed"
        ]

    if normalized_tab == "pending":
        aggregated_rows = [row for row in aggregated_rows if row[2].pending_reason is not None]
    elif normalized_tab == "skip":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None and row[3] == "skip"
        ]
    elif normalized_tab == "processed":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None
            and row[3] != "skip"
            and row[1].processed_status == "processed"
        ]
    elif normalized_tab == "unprocessed":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None
            and row[3] != "skip"
            and row[1].processed_status == "unprocessed"
        ]

    if importance != "all":
        normalized_importance = normalize_importance_filter(importance)
        aggregated_rows = [
            row for row in aggregated_rows if row[3] == normalized_importance
        ]

    if normalized_contact_status == "pending":
        aggregated_rows = [row for row in aggregated_rows if row[2].pending_reason is not None]
    elif normalized_contact_status == "resolved":
        aggregated_rows = [row for row in aggregated_rows if row[2].pending_reason is None]

    if normalized_read != "all":
        aggregated_rows = [
            row for row in aggregated_rows if row[4] == normalized_read
        ]

    send_requests = []
    if (
        normalized_tab in {"all", "processed"}
        and normalized_processed in {"all", "1", "processed"}
        and importance == "all"
        and normalized_contact_status != "pending"
        and normalized_read in {"all", "read"}
    ):
        send_requests = send_only_requests(session)
        if query_tokens:
            send_requests = [
                send_request
                for send_request in send_requests
                if send_request_matches_query(send_request, query_tokens)
            ]

    if date_from is not None and date_from.strip() != "":
        aggregated_rows = [
            row for row in aggregated_rows if row[0].received_at >= date_from.strip()
        ]
        send_requests = [
            send_request
            for send_request in send_requests
            if send_request_visible_at(send_request) >= date_from.strip()
        ]
    if date_to is not None and date_to.strip() != "":
        aggregated_rows = [
            row for row in aggregated_rows if row[0].received_at <= date_to.strip()
        ]
        send_requests = [
            send_request
            for send_request in send_requests
            if send_request_visible_at(send_request) <= date_to.strip()
        ]

    if cursor is not None and cursor.strip() != "":
        cursor_received_at, cursor_id = decode_cursor(cursor.strip())
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[0].received_at < cursor_received_at
            or (row[0].received_at == cursor_received_at and row[0].id > cursor_id)
        ]
        send_requests = [
            send_request
            for send_request in send_requests
            if send_request_visible_at(send_request) < cursor_received_at
            or (
                send_request_visible_at(send_request) == cursor_received_at
                and send_request.id > cursor_id
            )
        ]

    real_items = [
        (
            message.received_at,
            message.id,
            list_item_data(
                session,
                message,
                user_state,
                auto_state,
                effective_importance_override=effective_importance,
                read_status_override=thread_read_status,
                read_at_override=thread_read_at,
            ),
        )
        for (
            message,
            user_state,
            auto_state,
            effective_importance,
            thread_read_status,
            thread_read_at,
        ) in aggregated_rows
    ]
    send_items = [
        (
            send_request_visible_at(send_request),
            send_request.id,
            send_request_list_item_data(send_request),
        )
        for send_request in send_requests
    ]
    combined_items = sorted(
        [*real_items, *send_items],
        key=lambda row: (row[0], row[1]),
        reverse=True,
    )
    visible_items = combined_items[:normalized_limit]
    has_next = len(combined_items) > normalized_limit
    next_cursor = (
        encode_cursor_values(visible_items[-1][0], visible_items[-1][1])
        if has_next and len(visible_items) > 0
        else None
    )
    return {
        "ok": True,
        "data": {
            "items": [item for _, _, item in visible_items],
            "next_cursor": next_cursor,
            "limit": normalized_limit,
        },
    }


@router.get("/dates")
def list_mail_dates(
    tab: str = "all",
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized_tab = normalize_tab_filter(tab)
    statement = (
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
    )
    aggregated_rows = aggregate_thread_rows(session.execute(statement).all())
    if normalized_tab == "pending":
        aggregated_rows = [row for row in aggregated_rows if row[2].pending_reason is not None]
    elif normalized_tab == "skip":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None and row[3] == "skip"
        ]
    elif normalized_tab == "processed":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None
            and row[3] != "skip"
            and row[1].processed_status == "processed"
        ]
    elif normalized_tab == "unprocessed":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None
            and row[3] != "skip"
            and row[1].processed_status == "unprocessed"
        ]

    date_counts: dict[str, int] = {}
    for message, _, _, _, _, _ in aggregated_rows:
        date_counts[message.received_at[:10]] = date_counts.get(message.received_at[:10], 0) + 1
    if normalized_tab in {"all", "processed"}:
        for send_request in send_only_requests(session):
            received_date = send_request_visible_at(send_request)[:10]
            date_counts[received_date] = date_counts.get(received_date, 0) + 1

    return {
        "ok": True,
        "data": {
            "items": [
                {"date": received_date, "count": date_counts[received_date]}
                for received_date in sorted(date_counts)
            ],
        },
    }


@router.get("/{message_id}")
def get_mail_detail(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message = session.get(GmailMessage, message_id)
    if message is None:
        send_request = session.get(MailSendRequest, message_id)
        if (
            send_request is None
            or send_request.reply_to_message_id is not None
            or send_request.sent_message_id is not None
            or send_request.status not in SEND_REQUEST_VISIBLE_STATUSES
        ):
            raise json_error(404, "NOT_FOUND", "Mail not found.")
        return {"ok": True, "data": send_request_detail_data(send_request)}
    user_state = session.scalar(
        select(MailUserState).where(MailUserState.message_id == message.id)
    )
    auto_state = session.scalar(
        select(MailAutoState).where(MailAutoState.message_id == message.id)
    )
    if user_state is None or auto_state is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Mail state is missing.")
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/refresh-pending")
def refresh_mail_pending_state(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    changed, reason, queued_job_id = refresh_pending_mail_state(
        session,
        message,
        auto_state,
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "changed": changed,
            "reason": reason,
            "queued_job_id": queued_job_id,
            "mail": list_item_data(session, message, user_state, auto_state),
        },
    }


@router.post("/{message_id}/importance")
def update_mail_importance(
    message_id: str,
    payload: MailImportanceRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    if auto_state.pending_reason is not None:
        raise json_error(409, "CONFLICT", "Pending mail importance cannot be changed.")

    importance = normalize_importance(payload.importance)
    now = jst_iso()
    user_state.user_importance = importance
    user_state.updated_at = now
    user_state.version += 1
    auto_state.effective_importance = importance
    auto_state.updated_at = now
    auto_state.version += 1
    if importance in SUMMARY_TARGET_IMPORTANCE and not message_is_sent(message):
        enqueue_mail_summary_job(session, message, now)
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/process")
def process_mail(
    message_id: str,
    payload: MailProcessRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    del payload
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    now = jst_iso()
    user_state.processed_status = "processed"
    user_state.processed_at = now
    user_state.updated_at = now
    user_state.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/read")
def mark_mail_read(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    now = jst_iso()
    thread_user_states = session.scalars(
        select(MailUserState)
        .join(GmailMessage, GmailMessage.id == MailUserState.message_id)
        .where(GmailMessage.thread_id == message.thread_id)
    ).all()
    for thread_user_state in thread_user_states:
        if thread_user_state.read_status == "read":
            continue
        thread_user_state.read_status = "read"
        thread_user_state.read_at = now
        thread_user_state.updated_at = now
        thread_user_state.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/unread")
def mark_mail_unread(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    now = jst_iso()
    user_state.read_status = "unread"
    user_state.read_at = None
    user_state.updated_at = now
    user_state.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/unprocess")
def unprocess_mail(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    now = jst_iso()
    user_state.processed_status = "unprocessed"
    user_state.processed_at = None
    user_state.updated_at = now
    user_state.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}
