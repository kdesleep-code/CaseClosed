from __future__ import annotations

import base64
import binascii
import json
import re
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
from caseclosed.db.models import AppSetting
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactTag
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailLlmBlockFilter
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailThreadSummary
from caseclosed.db.models import MailUserState
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_address_list
from caseclosed.email_addressing import normalize_email_address
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import apply_contact_mail_importance_rule
from caseclosed.services.mail_ingestion import block_filter_tokens
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.services.mail_ingestion import message_is_sent
from caseclosed.services.mail_ingestion import row_matches_llm_block_query
from caseclosed.services.background_worker import kick_job_drain
from caseclosed.services.llm_provider import LLM_FUNCTION_TYPES
from caseclosed.services.llm_provider import (
    FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
)
from caseclosed.services.llm_provider import FUNCTION_TYPE_REPLY_DRAFT_GENERATION
from caseclosed.services.llm_provider import LlmProviderResponse
from caseclosed.services.llm_provider import build_mail_draft_generation_provider
from caseclosed.services.llm_provider import list_llm_model_profiles
from caseclosed.services.llm_provider import llm_function_config_data
from caseclosed.services.llm_provider import llm_model_profile_data
from caseclosed.mail_drafts import delete_mail_drafts_for_reply_target
from caseclosed.services.mail_summary import SUMMARY_TARGET_IMPORTANCE
from caseclosed.services.mail_summary import enqueue_mail_summary_job

router = APIRouter(prefix="/api/v1/mails", tags=["mails"])

LANGUAGE_ENGLISH = "english"
LANGUAGE_JAPANESE = "japanese"


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


class MailSendAttachmentPayload(BaseModel):
    filename: str
    content_type: str | None = None
    data_base64: str
    size: int | None = None


class MailSendRequestPayload(BaseModel):
    to_addresses: list[str]
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    subject: str | None = None
    body_text: str
    attachment_names: list[str] | None = None
    attachments: list[MailSendAttachmentPayload] | None = None
    reply_to_message_id: str | None = None
    scheduled_at: str | None = None


class MailDraftGenerationRequest(BaseModel):
    instruction: str | None = None
    standard_prompt: str | None = None
    to_addresses: list[str] | None = None
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    subject: str | None = None
    auto_body_text: str | None = None
    body_text: str | None = None
    reply_to_message_id: str | None = None
    related_case_summaries: list[dict[str, object]] | None = None


class MailSendSchedulePayload(BaseModel):
    scheduled_at: str


class MailLlmBlockFilterPayload(BaseModel):
    q: str
    reason: str | None = None


class MailLlmBlockFilterUpdatePayload(BaseModel):
    is_enabled: bool


class LlmModelAssignmentPayload(BaseModel):
    function_type: str
    profile_id: str


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

SEND_REQUEST_VISIBLE_STATUSES = {
    "scheduled_mock",
    "queued_mock",
    "sending_mock",
    "sending_gmail",
}
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
        "queued_contact_ai_memo_job_id": result.queued_contact_ai_memo_job_id,
    }


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []

    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


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


def attachment_payloads_json(
    attachments: list[MailSendAttachmentPayload] | None,
) -> str | None:
    if not attachments:
        return None
    values: list[dict[str, object]] = []
    for attachment in attachments:
        filename = attachment.filename.strip()
        data_base64 = attachment.data_base64.strip()
        if filename == "" or data_base64 == "":
            raise json_error(422, "VALIDATION_ERROR", "Attachment data is invalid.")
        values.append(
            {
                "filename": filename,
                "content_type": (
                    attachment.content_type.strip()
                    if attachment.content_type is not None
                    and attachment.content_type.strip() != ""
                    else "application/octet-stream"
                ),
                "data_base64": data_base64,
                "size": attachment.size,
            }
        )
    return json.dumps(values, ensure_ascii=True)


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
    *,
    include_sender_resolution_mode: bool = False,
) -> dict[str, object]:
    data = {
        "id": contact.id,
        "display_name": contact.display_name,
        "avatar_url": contact.avatar_url,
        "kind": contact.kind,
        "status": contact.status,
        "tags": contact_tags(session, contact.id) if session is not None else [],
    }
    if include_sender_resolution_mode:
        data["sender_resolution_mode"] = contact.sender_resolution_mode
    return data


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


def display_sender_contact_for_message(
    session: DatabaseSession,
    message: GmailMessage,
    from_contact: Contact | None,
) -> Contact | None:
    if (
        from_contact is not None
        and from_contact.kind == "mailing_list"
        and from_contact.sender_resolution_mode == "reply_to"
        and message.reply_to_address is not None
        and message.reply_to_address.strip() != ""
    ):
        reply_to_contact = contact_for_address(session, message.reply_to_address)
        return reply_to_contact
    return from_contact


def recipient_contact_memos(
    session: DatabaseSession,
    email_addresses: list[str],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_contact_ids: set[str] = set()
    for email_address in email_addresses:
        contact = contact_for_address(session, email_address)
        if contact is None or contact.id in seen_contact_ids:
            continue
        seen_contact_ids.add(contact.id)
        user_memo = contact.user_memo if contact.user_memo is not None else contact.memo
        items.append(
            {
                "contact_id": contact.id,
                "display_name": contact.display_name,
                "kind": contact.kind,
                "status": contact.status,
                "email_address": email_address,
                "user_memo": user_memo,
            }
        )
    return items


def recipient_contact_context(
    session: DatabaseSession,
    *,
    to_addresses: list[str],
    cc_addresses: list[str],
) -> dict[str, object]:
    return {
        "to": recipient_contact_memos(session, to_addresses),
        "cc": recipient_contact_memos(session, cc_addresses),
    }


def detect_draft_language(text: str | None) -> str | None:
    if text is None:
        return None
    compacted = text.strip()
    if compacted == "":
        return None
    japanese_count = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", compacted))
    latin_word_count = len(re.findall(r"\b[A-Za-z][A-Za-z'-]{2,}\b", compacted))
    latin_letter_count = len(re.findall(r"[A-Za-z]", compacted))
    if japanese_count >= 8 and japanese_count >= latin_word_count:
        return LANGUAGE_JAPANESE
    if latin_word_count >= 12 and latin_letter_count >= japanese_count * 3:
        return LANGUAGE_ENGLISH
    if latin_word_count >= 5 and japanese_count == 0:
        return LANGUAGE_ENGLISH
    return None


def explicit_language_instruction(text: str | None) -> str | None:
    if text is None or text.strip() == "":
        return None
    lowered = text.lower()
    asks_english = (
        "in english" in lowered
        or "reply in english" in lowered
        or "write in english" in lowered
        or "英語" in text
        or "英文" in text
    )
    asks_japanese = (
        "in japanese" in lowered
        or "reply in japanese" in lowered
        or "write in japanese" in lowered
        or "日本語" in text
        or "和文" in text
    )
    if asks_english and not asks_japanese:
        return LANGUAGE_ENGLISH
    if asks_japanese and not asks_english:
        return LANGUAGE_JAPANESE
    return None


def reply_source_text(message: GmailMessage | None) -> str:
    if message is None:
        return ""
    return "\n".join(
        part
        for part in [
            message.subject or "",
            message.snippet or "",
            message.body_text or "",
        ]
        if part.strip() != ""
    )


def expected_reply_language(
    *,
    reply_to_message: GmailMessage | None,
    instruction: str | None,
    standard_prompt: str | None,
) -> str | None:
    explicit_language = explicit_language_instruction(
        "\n".join([instruction or "", standard_prompt or ""]),
    )
    if explicit_language is not None:
        return explicit_language
    return detect_draft_language(reply_source_text(reply_to_message))


def language_label(language: str | None) -> str:
    if language == LANGUAGE_ENGLISH:
        return "English"
    if language == LANGUAGE_JAPANESE:
        return "Japanese"
    return "Unspecified"


def language_policy_text(language: str | None, *, is_reply: bool) -> str:
    if not is_reply:
        return (
            "No reply source language is available. Follow the user's explicit "
            "instruction and recipient context; when unclear, write polite Japanese."
        )
    if language == LANGUAGE_ENGLISH:
        return (
            "This is a reply to an English email. Generate the reply body in English. "
            "This overrides the app's default Japanese preference unless the user "
            "explicitly requests another language."
        )
    if language == LANGUAGE_JAPANESE:
        return (
            "This is a reply to a Japanese email. Generate the reply body in Japanese. "
            "This overrides the app's default Japanese preference only if the user "
            "explicitly requests another language."
        )
    return (
        "This is a reply, but the source language was not clear. Infer the reply "
        "language from the source email and user instruction."
    )


def draft_language_mismatch(expected_language: str | None, body_text: str) -> bool:
    actual_language = detect_draft_language(body_text)
    return (
        expected_language in {LANGUAGE_ENGLISH, LANGUAGE_JAPANESE}
        and actual_language in {LANGUAGE_ENGLISH, LANGUAGE_JAPANESE}
        and actual_language != expected_language
    )


def retry_language_instruction(expected_language: str) -> str:
    return (
        f"The previous draft was not written in {language_label(expected_language)}. "
        f"Regenerate the subject and body in {language_label(expected_language)}. "
        "Keep the content faithful to the same compose context."
    )


def combine_draft_provider_responses(
    first_response: LlmProviderResponse,
    retry_response: LlmProviderResponse,
) -> LlmProviderResponse:
    return LlmProviderResponse(
        output=retry_response.output,
        output_preview=retry_response.output_preview,
        prompt_tokens=add_optional_ints(
            first_response.prompt_tokens,
            retry_response.prompt_tokens,
        ),
        completion_tokens=add_optional_ints(
            first_response.completion_tokens,
            retry_response.completion_tokens,
        ),
        total_tokens=add_optional_ints(
            first_response.total_tokens,
            retry_response.total_tokens,
        ),
        estimated_cost=add_optional_floats(
            first_response.estimated_cost,
            retry_response.estimated_cost,
        ),
    )


def add_optional_ints(first: int | None, second: int | None) -> int | None:
    if first is None and second is None:
        return None
    return (first or 0) + (second or 0)


def add_optional_floats(first: float | None, second: float | None) -> float | None:
    if first is None and second is None:
        return None
    return (first or 0.0) + (second or 0.0)


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
    display_sender_contact = (
        display_sender_contact_for_message(session, message, from_contact)
        if session is not None
        else from_contact
    )
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
            contact_summary(
                from_contact,
                session,
                include_sender_resolution_mode=True,
            )
            if from_contact is not None
            else None
        ),
        "sender_contact": (
            contact_summary(
                display_sender_contact,
                session,
                include_sender_resolution_mode=True,
            )
            if display_sender_contact is not None
            else None
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
        data["llm_blocked"] = bool(auto_state.llm_blocked)
        data["llm_block_reason"] = auto_state.llm_block_reason
        data["llm_blocked_at"] = auto_state.llm_blocked_at
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
        "llm_blocked": bool(auto_state.llm_blocked),
        "llm_block_reason": auto_state.llm_block_reason,
        "llm_blocked_at": auto_state.llm_blocked_at,
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


def mail_thread_summary_data(
    summary: MailThreadSummary,
    *,
    item_summaries: list[MailSummary] | None = None,
) -> dict[str, object]:
    return {
        "id": summary.id,
        "thread_id": summary.thread_id,
        "summary_text": summary.summary_text,
        "action_required": bool(summary.action_required)
        if summary.action_required is not None
        else None,
        "next_action": summary.next_action,
        "key_points": json_list(summary.key_points_json),
        "translation_text": summary.translation_text,
        "language": summary.language,
        "llm_run_id": summary.llm_run_id,
        "updated_at": summary.updated_at,
        "version": summary.version,
        "items": (
            [mail_summary_data(item_summary) for item_summary in item_summaries]
            if item_summaries is not None
            else []
        ),
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


def stored_thread_summary(
    session: DatabaseSession,
    thread_id: str,
) -> MailThreadSummary | None:
    return session.scalar(
        select(MailThreadSummary).where(MailThreadSummary.thread_id == thread_id)
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


def normalize_importance_filter_set(value: str | None) -> set[str]:
    if value is None or value.strip() == "":
        return set()
    return {
        normalize_importance_filter(part)
        for part in value.split(",")
        if part.strip() != ""
    }


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


def llm_blocked_mail_data(
    message: GmailMessage,
    auto_state: MailAutoState,
) -> dict[str, object]:
    return {
        "id": message.id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "llm_block_reason": auto_state.llm_block_reason,
        "llm_blocked_at": auto_state.llm_blocked_at,
    }


def llm_block_filter_data(block_filter: MailLlmBlockFilter) -> dict[str, object]:
    return {
        "id": block_filter.id,
        "query_text": block_filter.query_text,
        "reason": block_filter.reason,
        "is_enabled": bool(block_filter.is_enabled),
        "created_at": block_filter.created_at,
        "updated_at": block_filter.updated_at,
        "version": block_filter.version,
    }


LLM_PROFILE_ASSIGNMENTS_KEY = "llm_profile_assignments"


def read_llm_profile_assignments(session: DatabaseSession) -> dict[str, str]:
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == LLM_PROFILE_ASSIGNMENTS_KEY)
    )
    if setting is None:
        return {}

    data = json.loads(setting.value_json)
    if not isinstance(data, dict):
        return {}

    return {
        str(function_type): str(profile_id)
        for function_type, profile_id in data.items()
        if isinstance(function_type, str)
        and isinstance(profile_id, str)
        and profile_id.strip() != ""
    }


def write_llm_profile_assignments(
    session: DatabaseSession,
    assignments: dict[str, str],
    now: str,
) -> None:
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == LLM_PROFILE_ASSIGNMENTS_KEY)
    )
    value_json = json.dumps(assignments, ensure_ascii=True, sort_keys=True)
    if setting is None:
        session.add(
            AppSetting(
                id=f"setting_{LLM_PROFILE_ASSIGNMENTS_KEY}",
                key=LLM_PROFILE_ASSIGNMENTS_KEY,
                value_json=value_json,
                updated_at=now,
            )
        )
        return

    setting.value_json = value_json
    setting.updated_at = now


def aggregate_thread_rows(
    rows: list[tuple[GmailMessage, MailUserState, MailAutoState]],
) -> list[tuple[GmailMessage, MailUserState, MailAutoState, str, str, str | None]]:
    thread_rows: dict[str, list[tuple[GmailMessage, MailUserState, MailAutoState]]] = {}
    for message, user_state, auto_state in rows:
        thread_rows.setdefault(message.thread_id, []).append(
            (message, user_state, auto_state)
        )

    aggregated_rows: list[
        tuple[GmailMessage, MailUserState, MailAutoState, str, str, str | None]
    ] = []
    for thread_group in thread_rows.values():
        display_group = [
            row for row in thread_group if not message_is_sent(row[0])
        ] or thread_group
        latest_message, latest_user_state, latest_auto_state = max(
            display_group,
            key=lambda row: (row[0].received_at, row[0].id),
        )
        importance_candidates = [
            row[1].user_importance or row[2].effective_importance
            for row in display_group
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
            if any(row[1].read_status == "unread" for row in display_group)
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


def needs_action_thread_ids(
    rows: list[tuple[GmailMessage, MailUserState, MailAutoState]],
) -> set[str]:
    return {
        message.thread_id
        for message, user_state, auto_state in rows
        if not message_is_sent(message)
        and auto_state.pending_reason is None
        and user_state.processed_status != "processed"
        and (user_state.user_importance or auto_state.effective_importance)
        in {"high", "middle"}
    }


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
    thread_summary = stored_thread_summary(session, message.thread_id)
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
        "summary": (
            mail_thread_summary_data(thread_summary, item_summaries=list(summaries))
            if thread_summary is not None
            else combined_thread_summary_data(list(summaries))
        ),
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
    thread_summary = stored_thread_summary(session, message.thread_id)
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
        "llm_blocked": bool(auto_state.llm_blocked),
        "llm_block_reason": auto_state.llm_block_reason,
        "llm_blocked_at": auto_state.llm_blocked_at,
        "sender_contact": (
            contact_summary(
                contact_row,
                session,
                include_sender_resolution_mode=True,
            )
            if contact_row is not None
            else None
        ),
        "case_links": [],
        "summary": None
        if is_sent or effective_importance not in SUMMARY_TARGET_IMPORTANCE
        else (
            thread_summary.summary_text
            if thread_summary is not None
            else summary.summary_text if summary is not None else None
        ),
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
    kick_job_drain(reason="mock_mail_ingested")
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
    attachment_names = [name.strip() for name in payload.attachment_names or [] if name.strip() != ""]
    attachment_data_json = attachment_payloads_json(payload.attachments)
    if attachment_names and attachment_data_json is None:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Attachment file data is required. Refresh the compose screen and attach the file again.",
        )
    if payload.attachments:
        attachment_names = [attachment.filename.strip() for attachment in payload.attachments]
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
        attachment_names_json=json.dumps(attachment_names, ensure_ascii=True),
        attachment_data_json=attachment_data_json,
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
    delete_mail_drafts_for_reply_target(payload.reply_to_message_id)
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.post("/generate-draft")
def generate_mail_draft(
    payload: MailDraftGenerationRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    to_addresses = normalize_address_list(payload.to_addresses)
    cc_addresses = normalize_address_list(payload.cc_addresses)
    bcc_addresses = normalize_address_list(payload.bcc_addresses)
    all_recipient_addresses = to_addresses + cc_addresses + bcc_addresses
    if len(all_recipient_addresses) == 0:
        raise json_error(422, "VALIDATION_ERROR", "At least one recipient is required.")

    reply_to_message = None
    if payload.reply_to_message_id is not None:
        reply_to_message = session.get(GmailMessage, payload.reply_to_message_id)
        if reply_to_message is None:
            raise json_error(404, "NOT_FOUND", "Reply target mail not found.")

    function_type = (
        FUNCTION_TYPE_REPLY_DRAFT_GENERATION
        if reply_to_message is not None
        else FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION
    )
    expected_language = expected_reply_language(
        reply_to_message=reply_to_message,
        instruction=payload.instruction,
        standard_prompt=payload.standard_prompt,
    )
    related_case_summaries = payload.related_case_summaries or []
    provider = build_mail_draft_generation_provider(function_type)
    input_payload = {
        "instruction": payload.instruction or "",
        "standard_prompt": payload.standard_prompt or "",
        "reply_language": language_label(expected_language),
        "language_policy": language_policy_text(
            expected_language,
            is_reply=reply_to_message is not None,
        ),
        "to_addresses": to_addresses,
        "cc_addresses": cc_addresses,
        "bcc_addresses": bcc_addresses,
        "current_subject": payload.subject or "",
        "auto_body_text": payload.auto_body_text if reply_to_message is not None else "",
        "current_body": payload.body_text or "",
        "reply_to_message_id": payload.reply_to_message_id,
        "reply_to_subject": reply_to_message.subject if reply_to_message is not None else "",
        "recipient_contact_context": recipient_contact_context(
            session,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
        ),
        "recipient_contact_memos": recipient_contact_memos(
            session,
            all_recipient_addresses,
        ),
        "related_case_summaries": related_case_summaries,
    }
    now = jst_iso()
    provider_response = provider.complete_json(
        function_type=function_type,
        input_payload=input_payload,
    )
    output = provider_response.output
    retry_count = 0
    if draft_language_mismatch(expected_language, str(output.get("body") or "")):
        retry_count = 1
        retry_input_payload = {
            **input_payload,
            "language_retry_instruction": retry_language_instruction(expected_language or ""),
        }
        retry_response = provider.complete_json(
            function_type=function_type,
            input_payload=retry_input_payload,
        )
        retry_output = retry_response.output
        if not draft_language_mismatch(expected_language, str(retry_output.get("body") or "")):
            input_payload = retry_input_payload
            provider_response = combine_draft_provider_responses(
                provider_response,
                retry_response,
            )
            output = retry_output
    llm_run = LlmRun(
        id=new_id("llm_run"),
        function_type=function_type,
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps(
            {
                "reply_to_message_id": payload.reply_to_message_id,
                "to_addresses": to_addresses,
                "cc_addresses": cc_addresses,
                "bcc_addresses": bcc_addresses,
                "has_instruction": bool((payload.instruction or "").strip()),
                "has_standard_prompt": bool((payload.standard_prompt or "").strip()),
                "reply_language": language_label(expected_language),
                "language_retry_count": retry_count,
                "related_case_summary_count": len(related_case_summaries),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        input_diagnostic_json=json.dumps(
            {
                "instruction_length": len(payload.instruction or ""),
                "standard_prompt_length": len(payload.standard_prompt or ""),
                "auto_body_text_length": len(payload.auto_body_text or ""),
                "current_body_length": len(payload.body_text or ""),
                "detected_reply_language": language_label(expected_language),
                "recipient_contact_memo_count": len(input_payload["recipient_contact_memos"]),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        applied_instruction_rule_ids_json=json.dumps([], ensure_ascii=True),
        output_json=json.dumps(output, ensure_ascii=True, sort_keys=True),
        output_text_preview=provider_response.output_preview,
        status="succeeded",
        error_type=None,
        error_message=None,
        retry_count=retry_count,
        max_retry_count=3,
        prompt_tokens=provider_response.prompt_tokens,
        completion_tokens=provider_response.completion_tokens,
        total_tokens=provider_response.total_tokens,
        estimated_cost=provider_response.estimated_cost,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    session.add(llm_run)
    session.commit()
    return {
        "ok": True,
        "data": {
            "subject": str(output["subject"]),
            "body_text": str(output["body"]),
            "llm_run_id": llm_run.id,
        },
    }


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
    if send_request.status in {
        "sent_mock",
        "sent_gmail",
        "sending_mock",
        "sending_gmail",
        "canceled",
    }:
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
    if send_request.status in {"sent_mock", "sent_gmail", "sending_mock", "sending_gmail"}:
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
    importance_any: str | None = None,
    needs_action: bool = False,
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
    normalized_importance_any = normalize_importance_filter_set(importance_any)
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
            if not message_is_sent(message)
            and row_matches_llm_block_query(message, query_tokens)
        }
        all_rows = [
            row
            for row in all_rows
            if row[0].thread_id in matching_thread_ids
        ]

    matching_needs_action_thread_ids = (
        needs_action_thread_ids(all_rows) if needs_action else set()
    )

    aggregated_rows = aggregate_thread_rows(all_rows)
    if needs_action:
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[0].thread_id in matching_needs_action_thread_ids
        ]
    else:
        if normalized_processed in {"0", "unprocessed"}:
            aggregated_rows = [
                row
                for row in aggregated_rows
                if row[1].processed_status == "unprocessed"
            ]
        elif normalized_processed in {"1", "processed"}:
            aggregated_rows = [
                row for row in aggregated_rows if row[1].processed_status == "processed"
            ]

        if normalized_tab == "pending":
            aggregated_rows = [
                row for row in aggregated_rows if row[2].pending_reason is not None
            ]
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
        if normalized_importance_any:
            aggregated_rows = [
                row for row in aggregated_rows if row[3] in normalized_importance_any
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
        and not normalized_importance_any
        and not needs_action
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


@router.get("/llm-blocked")
def list_llm_blocked_mails(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    rows = session.execute(
        select(GmailMessage, MailAutoState)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .where(MailAutoState.llm_blocked == 1)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
        .limit(100)
    ).all()
    return {
        "ok": True,
        "data": {
            "items": [
                llm_blocked_mail_data(message, auto_state)
                for message, auto_state in rows
            ],
        },
    }


@router.get("/llm-model-config")
def get_llm_model_config(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    # Read the DB setting once so later function data resolves runtime overrides.
    read_llm_profile_assignments(session)
    return {
        "ok": True,
        "data": {
            "profiles": [
                llm_model_profile_data(profile) for profile in list_llm_model_profiles()
            ],
            "functions": [
                llm_function_config_data(function_type)
                for function_type in LLM_FUNCTION_TYPES
            ],
        },
    }


@router.patch("/llm-model-config")
def update_llm_model_assignment(
    payload: LlmModelAssignmentPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if payload.function_type not in LLM_FUNCTION_TYPES:
        raise json_error(422, "VALIDATION_ERROR", "Invalid LLM function type.")

    profile_id = payload.profile_id.strip()
    profile_ids = {profile.id for profile in list_llm_model_profiles()}
    if profile_id != "mock" and profile_id not in profile_ids:
        raise json_error(422, "VALIDATION_ERROR", "Invalid LLM model profile.")

    now = jst_iso()
    assignments = read_llm_profile_assignments(session)
    assignments[payload.function_type] = profile_id
    write_llm_profile_assignments(session, assignments, now)
    session.commit()
    kick_job_drain(reason="pending_mail_refreshed")
    return {
        "ok": True,
        "data": {
            "profiles": [
                llm_model_profile_data(profile) for profile in list_llm_model_profiles()
            ],
            "functions": [
                llm_function_config_data(function_type)
                for function_type in LLM_FUNCTION_TYPES
            ],
        },
    }


@router.get("/llm-block-filters")
def list_llm_block_filters(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    filters = session.scalars(
        select(MailLlmBlockFilter).order_by(
            MailLlmBlockFilter.created_at.desc(),
            MailLlmBlockFilter.id.desc(),
        )
    ).all()
    return {
        "ok": True,
        "data": {"items": [llm_block_filter_data(block_filter) for block_filter in filters]},
    }


@router.post("/llm-block-filter")
def apply_llm_block_filter(
    payload: MailLlmBlockFilterPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    query_text = payload.q.strip()
    tokens = block_filter_tokens(query_text)
    if len(tokens) == 0:
        raise json_error(422, "VALIDATION_ERROR", "Filter query is required.")

    now = jst_iso()
    reason = payload.reason.strip() if payload.reason is not None else ""
    if reason == "":
        reason = f"Matched maintenance LLM block filter: {query_text}"

    block_filter = MailLlmBlockFilter(
        id=new_id("mail_llm_block_filter"),
        query_text=query_text,
        reason=reason,
        is_enabled=1,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(block_filter)

    rows = session.execute(
        select(GmailMessage, MailAutoState)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    matched_rows = [
        (message, auto_state)
        for message, auto_state in rows
        if not message_is_sent(message) and row_matches_llm_block_query(message, tokens)
    ]
    changed = 0
    for message, auto_state in matched_rows:
        if not bool(auto_state.llm_blocked):
            changed += 1
        auto_state.llm_blocked = 1
        auto_state.llm_block_reason = reason
        auto_state.llm_blocked_at = now
        if auto_state.pending_reason is None:
            auto_state.effective_importance = "pinned"
        auto_state.updated_at = now
        auto_state.version += 1

    session.commit()
    return {
        "ok": True,
        "data": {
            "filter": llm_block_filter_data(block_filter),
            "matched": len(matched_rows),
            "changed": changed,
            "items": [
                llm_blocked_mail_data(message, auto_state)
                for message, auto_state in matched_rows[:50]
            ],
        },
    }


@router.patch("/llm-block-filters/{filter_id}")
def update_llm_block_filter(
    filter_id: str,
    payload: MailLlmBlockFilterUpdatePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    block_filter = session.get(MailLlmBlockFilter, filter_id)
    if block_filter is None:
        raise json_error(404, "NOT_FOUND", "LLM block filter was not found.")

    block_filter.is_enabled = 1 if payload.is_enabled else 0
    block_filter.updated_at = jst_iso()
    block_filter.version += 1
    session.commit()
    return {"ok": True, "data": llm_block_filter_data(block_filter)}


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


@router.get("/day-stats")
def get_mail_day_stats(
    date: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if len(date) != 10:
        raise json_error(422, "VALIDATION_ERROR", "Date must be formatted as YYYY-MM-DD.")
    start = f"{date}T00:00:00+09:00"
    end = f"{date}T23:59:59+09:00"
    rows = session.execute(
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .where(GmailMessage.received_at >= start, GmailMessage.received_at <= end)
    ).all()
    rows = [
        row
        for row in rows
        if "DRAFT" not in {label.upper() for label in json_list(row[0].gmail_labels_json)}
    ]
    total_count = len(rows)
    sent_count = 0
    received_count = 0
    for message, user_state, auto_state in rows:
        if message_is_sent(message):
            sent_count += 1
            continue
        effective_importance = user_state.user_importance or auto_state.effective_importance
        if effective_importance not in {"skip", "unclassified"}:
            received_count += 1

    send_only_count = sum(
        1
        for send_request in send_only_requests(session)
        if date <= send_request_visible_at(send_request)[:10] <= date
    )
    total_count += send_only_count
    sent_count += send_only_count
    return {
        "ok": True,
        "data": {
            "date": date,
            "total_count": total_count,
            "received_count": received_count,
            "sent_count": sent_count,
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
    kick_job_drain(reason="mail_importance_updated")
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.post("/{message_id}/summary")
def request_mail_summary(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, _user_state, auto_state = get_mail_bundle(session, message_id)
    if message_is_sent(message):
        raise json_error(409, "CONFLICT", "Sent mail cannot be summarized.")
    if auto_state.pending_reason is not None:
        raise json_error(409, "CONFLICT", "Pending mail cannot be summarized.")
    if bool(auto_state.llm_blocked):
        raise json_error(409, "CONFLICT", "LLM blocked mail cannot be summarized.")
    if auto_state.effective_importance == "pinned":
        raise json_error(409, "CONFLICT", "Pinned mail cannot be summarized.")

    now = jst_iso()
    job_id = enqueue_mail_summary_job(
        session,
        message,
        now,
        force=True,
        reason="manual_request",
    )
    session.commit()
    kick_job_drain(reason="mail_summary_requested")
    return {"ok": True, "data": {"job_id": job_id}}


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
