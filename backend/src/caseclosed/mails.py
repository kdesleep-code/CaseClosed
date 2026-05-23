from __future__ import annotations

import base64
import binascii
import json

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailUserState
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import ingest_mock_mail

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


IMPORTANCE_RANKS = {
    "pinned": 0,
    "high": 1,
    "middle": 2,
    "low": 3,
    "unclassified": 4,
    "pending": 5,
    "skip": 6,
}


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


def message_data(message: GmailMessage, *, include_body: bool = False) -> dict[str, object]:
    data = {
        "id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "gmail_thread_id": message.gmail_thread_id,
        "thread_id": message.thread_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "from_name": message.from_name,
        "sender_address": message.sender_address,
        "reply_to_address": message.reply_to_address,
        "to_addresses": json_list(message.to_addresses_json),
        "cc_addresses": json_list(message.cc_addresses_json),
        "bcc_addresses": json_list(message.bcc_addresses_json),
        "message_id_header": message.message_id_header,
        "in_reply_to_header": message.in_reply_to_header,
        "references_header": message.references_header,
        "list_id": message.list_id,
        "snippet": message.snippet,
        "gmail_link": message.gmail_link,
        "external_starred": bool(message.external_starred),
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "version": message.version,
    }
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


def auto_state_data(auto_state: MailAutoState) -> dict[str, object]:
    return {
        "id": auto_state.id,
        "message_id": auto_state.message_id,
        "external_importance": auto_state.external_importance,
        "suggested_importance": auto_state.suggested_importance,
        "llm_run_id": auto_state.llm_run_id,
        "effective_importance": auto_state.effective_importance,
        "pending_reason": auto_state.pending_reason,
        "pending_from_address_id": auto_state.pending_from_address_id,
        "updated_at": auto_state.updated_at,
        "version": auto_state.version,
    }


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
    payload = json.dumps(
        {"received_at": message.received_at, "id": message.id},
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
    return {
        "message": message_data(message, include_body=True),
        "thread_messages": [
            message_data(thread_message, include_body=False)
            for thread_message in thread_messages
        ],
        "user_state": user_state_data(user_state),
        "auto_state": auto_state_data(auto_state),
        "summary": None,
        "case_links": [],
        "attachments": [],
        "drafts": [],
        "available_actions": available_actions(user_state, auto_state),
    }


def list_item_data(
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
) -> dict[str, object]:
    effective_importance = auto_state.effective_importance
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
        "read_status": user_state.read_status,
        "read_at": user_state.read_at,
        "user_importance": user_state.user_importance,
        "effective_importance": effective_importance,
        "importance_rank": IMPORTANCE_RANKS.get(effective_importance, 99),
        "external_importance": auto_state.external_importance,
        "suggested_importance": auto_state.suggested_importance,
        "llm_run_id": auto_state.llm_run_id,
        "pending_reason": auto_state.pending_reason,
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
    if normalized_processed in {"0", "unprocessed"}:
        statement = statement.where(MailUserState.processed_status == "unprocessed")
    elif normalized_processed in {"1", "processed"}:
        statement = statement.where(MailUserState.processed_status == "processed")

    if normalized_tab == "pending":
        statement = statement.where(MailAutoState.pending_reason.is_not(None))
    elif normalized_tab == "skip":
        statement = statement.where(
            MailAutoState.pending_reason.is_(None),
            MailAutoState.effective_importance == "skip",
        )
    elif normalized_tab == "processed":
        statement = statement.where(
            MailAutoState.pending_reason.is_(None),
            MailAutoState.effective_importance != "skip",
            MailUserState.processed_status == "processed",
        )
    elif normalized_tab == "unprocessed":
        statement = statement.where(
            MailAutoState.pending_reason.is_(None),
            MailAutoState.effective_importance != "skip",
            MailUserState.processed_status == "unprocessed",
        )

    if importance != "all":
        statement = statement.where(
            MailAutoState.effective_importance == normalize_importance_filter(importance)
        )

    if normalized_contact_status == "pending":
        statement = statement.where(MailAutoState.pending_reason.is_not(None))
    elif normalized_contact_status == "resolved":
        statement = statement.where(MailAutoState.pending_reason.is_(None))

    if normalized_read != "all":
        statement = statement.where(MailUserState.read_status == normalized_read)

    if date_from is not None and date_from.strip() != "":
        statement = statement.where(GmailMessage.received_at >= date_from.strip())
    if date_to is not None and date_to.strip() != "":
        statement = statement.where(GmailMessage.received_at <= date_to.strip())

    if cursor is not None and cursor.strip() != "":
        cursor_received_at, cursor_id = decode_cursor(cursor.strip())
        statement = statement.where(
            or_(
                GmailMessage.received_at < cursor_received_at,
                (
                    (GmailMessage.received_at == cursor_received_at)
                    & (GmailMessage.id > cursor_id)
                ),
            )
        )

    if q is not None and q.strip() != "":
        for token in q.strip().split():
            pattern = f"%{token.lower()}%"
            statement = statement.where(
                or_(
                    GmailMessage.subject.ilike(pattern),
                    GmailMessage.from_address.ilike(pattern),
                    GmailMessage.from_name.ilike(pattern),
                    GmailMessage.sender_address.ilike(pattern),
                    GmailMessage.reply_to_address.ilike(pattern),
                    GmailMessage.to_addresses_json.ilike(pattern),
                    GmailMessage.cc_addresses_json.ilike(pattern),
                    GmailMessage.bcc_addresses_json.ilike(pattern),
                    GmailMessage.message_id_header.ilike(pattern),
                    GmailMessage.list_id.ilike(pattern),
                    GmailMessage.body_text.ilike(pattern),
                    GmailMessage.snippet.ilike(pattern),
                )
            )

    rows = session.execute(statement.limit(normalized_limit + 1)).all()
    visible_rows = rows[:normalized_limit]
    next_cursor = (
        encode_cursor(visible_rows[-1][0])
        if len(rows) > normalized_limit and len(visible_rows) > 0
        else None
    )
    return {
        "ok": True,
        "data": {
            "items": [
                list_item_data(message, user_state, auto_state)
                for message, user_state, auto_state in visible_rows
            ],
            "next_cursor": next_cursor,
            "limit": normalized_limit,
        },
    }


@router.get("/{message_id}")
def get_mail_detail(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


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
    user_state.read_status = "read"
    user_state.read_at = now
    user_state.updated_at = now
    user_state.version += 1
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
