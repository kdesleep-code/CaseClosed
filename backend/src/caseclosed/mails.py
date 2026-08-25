from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import load_only

from caseclosed.auth import ACCESS_MODE_LOW_MAIL_REVIEW
from caseclosed.auth import json_error
from caseclosed.auth import require_session_access_mode
from caseclosed.contact_selectors import resolve_recipient_selectors
from caseclosed.db.models import AppSetting
from caseclosed.db.models import Case
from caseclosed.db.models import CalendarEvent
from caseclosed.db.models import CalendarEventLink
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactTag
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import GmailMessageAttachment
from caseclosed.db.models import GmailThread
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import LlmInstructionRule
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailLlmBlockFilter
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import MailSendRequestCaseLink
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailThreadSummary
from caseclosed.db.models import MailUserState
from caseclosed.db.models import StorageObject
from caseclosed.db.models import Task
from caseclosed.db.models import TaskLink
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import parse_iso_datetime
from caseclosed.email_addressing import normalize_address_list
from caseclosed.email_addressing import normalize_email_address
from caseclosed.services.case_mail_stakeholders import ensure_case_stakeholders_for_mail_senders
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import apply_contact_mail_importance_rule
from caseclosed.services.mail_ingestion import block_filter_tokens
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.services.mail_ingestion import enqueue_importance_job
from caseclosed.services.mail_ingestion import message_is_sent
from caseclosed.services.mail_ingestion import row_matches_llm_block_query
from caseclosed.services.background_worker import kick_job_drain
from caseclosed.services.mail_attachment_fetch import (
    enqueue_mail_attachment_fetch_job,
)
from caseclosed.services.mail_attachment_visibility import (
    is_probable_generated_inline_image,
)
from caseclosed.services.llm_provider import LLM_FUNCTION_TYPES
from caseclosed.services.llm_provider import LLM_SETTINGS_RULE_ID_PREFIX
from caseclosed.services.llm_provider import (
    FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
)
from caseclosed.services.llm_provider import FUNCTION_TYPE_REPLY_DRAFT_GENERATION
from caseclosed.services.llm_provider import OpenAIProviderError
from caseclosed.services.llm_provider import build_mail_draft_generation_provider
from caseclosed.services.llm_provider import list_llm_model_profiles
from caseclosed.services.llm_provider import llm_function_config_data
from caseclosed.services.llm_provider import llm_applied_instruction_rule_ids
from caseclosed.services.llm_provider import with_llm_personalization
from caseclosed.services.llm_provider import llm_model_profile_data
from caseclosed.services.mail_summary import SUMMARY_TARGET_IMPORTANCE
from caseclosed.services.mail_summary import enqueue_mail_summary_job
from caseclosed.services.mail_state_transitions import clear_done_after_leaving_skip
from caseclosed.storage import delete_storage_object
from caseclosed.storage import save_storage_object
from caseclosed.storage import storage_object_data
from caseclosed.storage import storage_object_absolute_path

router = APIRouter(prefix="/api/v1/mails", tags=["mails"])

LANGUAGE_ENGLISH = "english"
LANGUAGE_JAPANESE = "japanese"
GMAIL_ATTACHMENT_STORAGE_SCOPE = "tmp/gmail-attachments"
MAIL_ATTACHMENT_STORAGE_SCOPES = {GMAIL_ATTACHMENT_STORAGE_SCOPE, "managed"}
MAIL_DRAFT_GENERATION_STANDARD_PROMPT_KEY = "mail_draft_generation_standard_prompt"
MAIL_DRAFT_GENERATION_LANGUAGE_KEY = "mail_draft_generation_language"


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


class MailThreadCaseAssignRequest(BaseModel):
    case_id: str


class MailImportanceRequest(BaseModel):
    importance: str


class MailThreadImportanceRuleRequest(BaseModel):
    future_importance_rule: str | None = None


class MailProcessRequest(BaseModel):
    reason: str | None = None


class MailSendAttachmentPayload(BaseModel):
    filename: str
    content_type: str | None = None
    data_base64: str | None = None
    storage_object_id: str | None = None
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
    case_ids: list[str] | None = None


class MailDraftGenerationRequest(BaseModel):
    instruction: str | None = None
    standard_prompt: str | None = None
    generation_language: str | None = None
    to_addresses: list[str] | None = None
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    subject: str | None = None
    auto_body_text: str | None = None
    body_text: str | None = None
    reply_to_message_id: str | None = None
    related_case_summaries: list[dict[str, object]] | None = None


class MailDraftGenerationStandardPromptPatch(BaseModel):
    standard_prompt: str | None = None
    generation_language: str | None = None


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


class LlmFunctionInstructionPayload(BaseModel):
    function_type: str
    instruction_text: str
    is_enabled: bool = True


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


def read_mail_draft_generation_standard_prompt(session: DatabaseSession) -> str:
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == MAIL_DRAFT_GENERATION_STANDARD_PROMPT_KEY)
    )
    if setting is None:
        return ""
    value = json.loads(setting.value_json)
    return value if isinstance(value, str) else ""


def write_mail_draft_generation_standard_prompt(
    session: DatabaseSession,
    standard_prompt: str,
    now: str,
) -> None:
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == MAIL_DRAFT_GENERATION_STANDARD_PROMPT_KEY)
    )
    value_json = json.dumps(standard_prompt, ensure_ascii=True)
    if setting is None:
        session.add(
            AppSetting(
                id=new_id("setting"),
                key=MAIL_DRAFT_GENERATION_STANDARD_PROMPT_KEY,
                value_json=value_json,
                updated_at=now,
            )
        )
        return
    setting.value_json = value_json
    setting.updated_at = now


def llm_settings_rule_id(function_type: str) -> str:
    return f"{LLM_SETTINGS_RULE_ID_PREFIX}{function_type}"


def read_llm_settings_rule(
    session: DatabaseSession,
    function_type: str,
) -> LlmInstructionRule | None:
    return session.get(LlmInstructionRule, llm_settings_rule_id(function_type))


def llm_function_instruction_data(
    session: DatabaseSession,
    function_type: str,
) -> dict[str, object]:
    rule = read_llm_settings_rule(session, function_type)
    instruction_text = ""
    is_enabled = False
    source = "settings"
    updated_at = None
    if rule is not None and rule.deleted_at is None:
        instruction_text = rule.instruction_text
        is_enabled = bool(rule.is_enabled and rule.instruction_text.strip())
        updated_at = rule.updated_at
    elif function_type in {
        FUNCTION_TYPE_REPLY_DRAFT_GENERATION,
        FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
    }:
        legacy_prompt = read_mail_draft_generation_standard_prompt(session)
        if legacy_prompt.strip():
            instruction_text = legacy_prompt
            is_enabled = True
            source = "legacy_mail_standard_prompt"
    config = llm_function_config_data(function_type)
    return {
        "function_type": function_type,
        "label": config["label"],
        "instruction_text": instruction_text,
        "is_enabled": is_enabled,
        "source": source,
        "updated_at": updated_at,
        "is_available": function_type not in {
            "mail_case_selection",
            "preparation_task_suggestion",
        },
    }


def upsert_llm_settings_rule(
    session: DatabaseSession,
    payload: LlmFunctionInstructionPayload,
    now: str,
) -> LlmInstructionRule:
    function_type = payload.function_type.strip()
    if function_type not in LLM_FUNCTION_TYPES:
        raise json_error(422, "VALIDATION_ERROR", "Unknown LLM function type.")
    instruction_text = payload.instruction_text.strip()
    enabled = bool(payload.is_enabled and instruction_text)
    rule = read_llm_settings_rule(session, function_type)
    if rule is None:
        rule = LlmInstructionRule(
            id=llm_settings_rule_id(function_type),
            name=f"Settings: {llm_function_config_data(function_type)['label']}",
            condition_json=json.dumps({"always": True}, ensure_ascii=True),
            instruction_text=instruction_text,
            function_types_json=json.dumps([function_type], ensure_ascii=True),
            priority_order=100,
            is_enabled=1 if enabled else 0,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            version=1,
        )
        session.add(rule)
        return rule
    rule.name = f"Settings: {llm_function_config_data(function_type)['label']}"
    rule.condition_json = json.dumps({"always": True}, ensure_ascii=True)
    rule.instruction_text = instruction_text
    rule.function_types_json = json.dumps([function_type], ensure_ascii=True)
    rule.priority_order = 100
    rule.is_enabled = 1 if enabled else 0
    rule.updated_at = now
    rule.deleted_at = None
    rule.version += 1
    return rule


def normalize_generation_language(value: str | None) -> str:
    return value if value in {LANGUAGE_JAPANESE, LANGUAGE_ENGLISH} else LANGUAGE_JAPANESE


def read_mail_draft_generation_language(session: DatabaseSession) -> str:
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == MAIL_DRAFT_GENERATION_LANGUAGE_KEY)
    )
    if setting is None:
        return LANGUAGE_JAPANESE
    value = json.loads(setting.value_json)
    return normalize_generation_language(value if isinstance(value, str) else None)


def write_mail_draft_generation_language(
    session: DatabaseSession,
    generation_language: str,
    now: str,
) -> None:
    normalized = normalize_generation_language(generation_language)
    setting = session.scalar(
        select(AppSetting).where(AppSetting.key == MAIL_DRAFT_GENERATION_LANGUAGE_KEY)
    )
    value_json = json.dumps(normalized, ensure_ascii=True)
    if setting is None:
        session.add(
            AppSetting(
                id=new_id("setting"),
                key=MAIL_DRAFT_GENERATION_LANGUAGE_KEY,
                value_json=value_json,
                updated_at=now,
            )
        )
        return
    setting.value_json = value_json
    setting.updated_at = now


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
        "attachments": sent_attachment_items(send_request),
        "reply_to_message_id": send_request.reply_to_message_id,
        "sent_message_id": send_request.sent_message_id,
        "scheduled_at": send_request.scheduled_at,
        "created_at": send_request.created_at,
        "updated_at": send_request.updated_at,
        "version": send_request.version,
    }


def send_request_case_link_items(
    session: DatabaseSession,
    send_request_id: str,
) -> list[dict[str, object]]:
    cases = session.scalars(
        select(Case)
        .join(MailSendRequestCaseLink, MailSendRequestCaseLink.case_id == Case.id)
        .where(MailSendRequestCaseLink.send_request_id == send_request_id)
        .order_by(Case.is_system_case.desc(), Case.updated_at.desc(), Case.name.asc())
    ).all()
    return [
        {"id": case.id, "case_id": case.id, "title": case.name}
        for case in cases
    ]


def attachment_payloads_json(
    attachments: list[MailSendAttachmentPayload] | None,
) -> str | None:
    if not attachments:
        return None
    values: list[dict[str, object]] = []
    for attachment in attachments:
        filename = attachment.filename.strip()
        data_base64 = (
            attachment.data_base64.strip()
            if attachment.data_base64 is not None
            else ""
        )
        storage_object_id = (
            attachment.storage_object_id.strip()
            if attachment.storage_object_id is not None
            else ""
        )
        if filename == "" or (data_base64 == "" and storage_object_id == ""):
            raise json_error(422, "VALIDATION_ERROR", "Attachment data is invalid.")
        item = {
            "filename": filename,
            "content_type": (
                attachment.content_type.strip()
                if attachment.content_type is not None
                and attachment.content_type.strip() != ""
                else "application/octet-stream"
            ),
            "size": attachment.size,
        }
        if storage_object_id != "":
            item["storage_object_id"] = storage_object_id
        else:
            item["data_base64"] = data_base64
        values.append(item)
    return json.dumps(values, ensure_ascii=True)


def json_dict_list(value: str | None) -> list[dict[str, object]]:
    if value is None:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]


def sent_attachment_filename(attachment: dict[str, object], index: int) -> str:
    filename = attachment.get("filename")
    if isinstance(filename, str) and filename.strip() != "":
        return filename.strip()
    return f"attachment-{index + 1}"


def sent_attachment_content_type(
    attachment: dict[str, object],
) -> str:
    content_type = attachment.get("content_type")
    if isinstance(content_type, str) and "/" in content_type:
        return content_type.strip()
    return "application/octet-stream"


def sent_attachment_size(
    attachment: dict[str, object],
) -> int:
    size = attachment.get("size")
    if isinstance(size, int) and size >= 0:
        return size
    return 0


def sent_attachment_download_url(send_request_id: str, index: int) -> str:
    return (
        f"/api/v1/mails/send-requests/{send_request_id}"
        f"/attachments/{index}/download"
    )


def sent_attachment_items(send_request: MailSendRequest) -> list[dict[str, object]]:
    return [
        {
            "id": f"{send_request.id}:{index}",
            "message_id": send_request.sent_message_id or send_request.id,
            "filename": sent_attachment_filename(attachment, index),
            "mime_type": sent_attachment_content_type(attachment),
            "byte_size": sent_attachment_size(attachment),
            "download_url": sent_attachment_download_url(send_request.id, index),
            "cached": True,
            "storage_object_id": (
                attachment.get("storage_object_id")
                if isinstance(attachment.get("storage_object_id"), str)
                else None
            ),
            "source_type": "sent_attachment",
        }
        for index, attachment in enumerate(json_dict_list(send_request.attachment_data_json))
    ]


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


def contact_participant_addresses(
    session: DatabaseSession,
    contact_id: str,
) -> set[str]:
    contact = session.get(Contact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise json_error(404, "NOT_FOUND", "Contact not found.")
    addresses = session.scalars(
        select(ContactEmailAddress.normalized_email_address)
        .where(ContactEmailAddress.contact_id == contact.id)
        .where(ContactEmailAddress.status != "deleted")
    ).all()
    return {normalize_email_address(address) for address in addresses if address.strip() != ""}


def message_has_participant(
    message: GmailMessage,
    participant_addresses: set[str],
) -> bool:
    message_addresses = [
        message.from_address,
        message.sender_address,
        message.reply_to_address,
        *json_list(message.to_addresses_json),
        *json_list(message.cc_addresses_json),
        *json_list(message.bcc_addresses_json),
    ]
    return any(
        address is not None
        and normalize_email_address(str(address)) in participant_addresses
        for address in message_addresses
    )


def send_request_has_participant(
    send_request: MailSendRequest,
    participant_addresses: set[str],
) -> bool:
    recipient_addresses = [
        *json_list(send_request.to_addresses_json),
        *json_list(send_request.cc_addresses_json),
        *json_list(send_request.bcc_addresses_json),
    ]
    return any(
        normalize_email_address(str(address)) in participant_addresses
        for address in recipient_addresses
    )


def send_request_list_item_data(
    session: DatabaseSession,
    send_request: MailSendRequest,
) -> dict[str, object]:
    visible_at = send_request_visible_at(send_request)
    attachments = sent_attachment_items(send_request)
    case_links = send_request_case_link_items(session, send_request.id)
    return {
        "id": send_request.id,
        "gmail_message_id": f"provisional:{send_request.id}",
        "gmail_thread_id": send_request_thread_id(send_request),
        "thread_id": send_request_thread_id(send_request),
        "received_at": visible_at,
        "received_date": visible_at[:10],
        "subject": send_request.subject,
        "from_address": MOCK_FROM_ADDRESS,
        "from_name": "C@seClosed",
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
        "case_links": case_links,
        "summary": None,
        "attachment_count": len(attachments),
        "has_attachments": len(attachments) > 0,
    }


def send_request_message_data(send_request: MailSendRequest) -> dict[str, object]:
    visible_at = send_request_visible_at(send_request)
    thread_id = send_request_thread_id(send_request)
    to_addresses = json_list(send_request.to_addresses_json)
    cc_addresses = json_list(send_request.cc_addresses_json)
    bcc_addresses = json_list(send_request.bcc_addresses_json)
    attachments = sent_attachment_items(send_request)
    return {
        "id": send_request.id,
        "gmail_message_id": f"provisional:{send_request.id}",
        "gmail_thread_id": thread_id,
        "thread_id": thread_id,
        "received_at": visible_at,
        "received_date": visible_at[:10],
        "subject": send_request.subject,
        "from_address": MOCK_FROM_ADDRESS,
        "from_name": "C@seClosed",
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
        "attachments": attachments,
        "attachment_count": len(attachments),
        "has_attachments": len(attachments) > 0,
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


def send_request_detail_data(
    session: DatabaseSession,
    send_request: MailSendRequest,
) -> dict[str, object]:
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
        "case_links": send_request_case_link_items(session, send_request.id),
        "attachments": message["attachments"],
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
                {
                    "send_request_id": send_request.id,
                    "send_request_version": send_request.version,
                    "scheduled_at": send_request.scheduled_at,
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
            available_at=available_at,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    return job_id


def supersede_pending_mail_send_jobs(
    session: DatabaseSession,
    send_request_id: str,
    now: str,
) -> list[str]:
    superseded_ids: list[str] = []
    jobs = session.scalars(
        select(Job)
        .where(Job.job_type == "mail_send_mock")
        .where(Job.status == "pending")
        .order_by(Job.created_at, Job.id)
    ).all()
    for job in jobs:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("send_request_id") != send_request_id:
            continue
        job.status = "succeeded"
        job.result_json = json.dumps(
            {
                "send_request_id": send_request_id,
                "status": "superseded",
                "idempotent": True,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        job.error_type = None
        job.error_message = None
        job.finished_at = now
        job.updated_at = now
        superseded_ids.append(job.id)
    return superseded_ids


def validated_future_send_time(value: str) -> str:
    scheduled_at = value.strip()
    if scheduled_at == "":
        raise json_error(422, "VALIDATION_ERROR", "Scheduled time is required.")
    try:
        parsed = parse_iso_datetime(scheduled_at)
    except (TypeError, ValueError):
        raise json_error(422, "VALIDATION_ERROR", "Scheduled time is invalid.") from None
    if parsed <= jst_now():
        raise json_error(422, "VALIDATION_ERROR", "Scheduled time must be in the future.")
    return scheduled_at


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
    return display_sender_contact_for_addresses(
        session,
        from_address=message.from_address,
        reply_to_address=message.reply_to_address,
        from_contact=from_contact,
    )


def display_sender_contact_for_addresses(
    session: DatabaseSession,
    *,
    from_address: str,
    reply_to_address: str | None,
    from_contact: Contact | None = None,
) -> Contact | None:
    resolved_from_contact = (
        from_contact if from_contact is not None else contact_for_address(session, from_address)
    )
    if (
        resolved_from_contact is not None
        and resolved_from_contact.kind == "mailing_list"
        and resolved_from_contact.sender_resolution_mode == "reply_to"
        and reply_to_address is not None
        and reply_to_address.strip() != ""
    ):
        reply_to_contact = contact_for_address(session, reply_to_address)
        return reply_to_contact
    return resolved_from_contact


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
    generation_language: str | None = None,
) -> str | None:
    normalized_generation_language = normalize_generation_language(generation_language)
    if normalized_generation_language in {LANGUAGE_JAPANESE, LANGUAGE_ENGLISH}:
        return normalized_generation_language
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


def generation_language_prompt(language: str | None) -> str:
    if normalize_generation_language(language) == LANGUAGE_ENGLISH:
        return "英語で生成してください。"
    return "日本語で生成してください。"


def language_policy_text(language: str | None, *, is_reply: bool) -> str:
    if not is_reply and language == LANGUAGE_ENGLISH:
        return "Generate the email body in English."
    if not is_reply and language == LANGUAGE_JAPANESE:
        return "Generate the email body in Japanese."
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


def attachment_download_url(attachment_id: str) -> str:
    return f"/api/v1/mails/attachments/{attachment_id}/download"


def mail_attachment_data(
    attachment: GmailMessageAttachment,
) -> dict[str, object]:
    return {
        "id": attachment.id,
        "message_id": attachment.message_id,
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "byte_size": attachment.byte_size,
        "download_url": attachment_download_url(attachment.id),
        "cached": attachment.storage_object_id is not None,
        "storage_object_id": attachment.storage_object_id,
    }


def is_legacy_inline_image(attachment: GmailMessageAttachment) -> bool:
    return is_probable_generated_inline_image(
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        byte_size=attachment.byte_size,
    )


def attachment_rows_by_message_id(
    session: DatabaseSession,
    message_ids: list[str],
) -> dict[str, list[GmailMessageAttachment]]:
    if not message_ids:
        return {}
    rows = session.scalars(
        select(GmailMessageAttachment)
        .where(GmailMessageAttachment.message_id.in_(message_ids))
        .order_by(
            GmailMessageAttachment.filename,
            GmailMessageAttachment.id,
        )
    ).all()
    grouped: dict[str, list[GmailMessageAttachment]] = {}
    for row in rows:
        if is_legacy_inline_image(row):
            continue
        grouped.setdefault(row.message_id, []).append(row)
    return grouped


def attachment_count_for_message(
    session: DatabaseSession,
    message_id: str,
) -> int:
    rows = session.scalars(
        select(GmailMessageAttachment).where(
            GmailMessageAttachment.message_id == message_id
        )
    ).all()
    return sum(1 for row in rows if not is_legacy_inline_image(row))


def unique_thread_attachments(
    attachments_by_message_id: dict[str, list[GmailMessageAttachment]],
) -> list[dict[str, object]]:
    seen: set[tuple[str, int]] = set()
    items: list[dict[str, object]] = []
    for attachments in attachments_by_message_id.values():
        for attachment in attachments:
            key = (attachment.filename, attachment.byte_size)
            if key in seen:
                continue
            seen.add(key)
            items.append(mail_attachment_data(attachment))
    return items


def sent_request_attachments_by_message_id(
    session: DatabaseSession,
    message_ids: list[str],
) -> dict[str, list[dict[str, object]]]:
    if not message_ids:
        return {}
    send_requests = session.scalars(
        select(MailSendRequest)
        .where(MailSendRequest.sent_message_id.in_(message_ids))
        .order_by(MailSendRequest.created_at, MailSendRequest.id)
    ).all()
    grouped: dict[str, list[dict[str, object]]] = {}
    for send_request in send_requests:
        if send_request.sent_message_id is None:
            continue
        attachments = sent_attachment_items(send_request)
        if attachments:
            grouped.setdefault(send_request.sent_message_id, []).extend(attachments)
    return grouped


def unique_attachment_items(
    attachment_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    seen: set[tuple[str, int]] = set()
    items: list[dict[str, object]] = []
    for attachment in attachment_items:
        filename = attachment.get("filename")
        byte_size = attachment.get("byte_size")
        key = (
            filename if isinstance(filename, str) else "",
            byte_size if isinstance(byte_size, int) else 0,
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(attachment)
    return items


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
        attachments = attachment_rows_by_message_id(session, [message.id]).get(
            message.id,
            [],
        )
        sent_attachments = sent_request_attachments_by_message_id(
            session,
            [message.id],
        ).get(message.id, [])
        attachment_items = [
            mail_attachment_data(attachment) for attachment in attachments
        ] + sent_attachments
        data["attachments"] = unique_attachment_items(attachment_items)
        data["attachment_count"] = len(data["attachments"])
        data["has_attachments"] = len(data["attachments"]) > 0
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


def active_summary_job_status_by_message_id(
    session: DatabaseSession,
    message_ids: list[str],
) -> dict[str, dict[str, object]]:
    message_id_set = set(message_ids)
    if len(message_id_set) == 0:
        return {}
    jobs = session.scalars(
        select(Job)
        .where(
            Job.job_type == "mail_summary",
            Job.status.in_(["pending", "running"]),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all()
    statuses: dict[str, dict[str, object]] = {}
    for job in jobs:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            continue
        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or message_id not in message_id_set:
            continue
        statuses.setdefault(
            message_id,
            {
                "job_id": job.id,
                "status": job.status,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            },
        )
    return statuses


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


def thread_messages(session: DatabaseSession, thread_id: str) -> list[GmailMessage]:
    return session.scalars(
        select(GmailMessage)
        .where(GmailMessage.thread_id == thread_id)
        .order_by(GmailMessage.received_at, GmailMessage.id)
    ).all()


def apply_case_link_importance_floor(
    session: DatabaseSession,
    thread_id: str,
    now: str,
) -> list[str]:
    rows = session.execute(
        select(GmailMessage, MailAutoState)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .where(GmailMessage.thread_id == thread_id)
    ).all()
    changed_message_ids: list[str] = []
    for thread_message, auto_state in rows:
        if (
            auto_state.llm_run_id is None
            or auto_state.effective_importance in {"pinned", "high", "middle"}
        ):
            continue
        auto_state.effective_importance = "middle"
        auto_state.updated_at = now
        auto_state.version += 1
        enqueue_mail_summary_job(session, thread_message, now)
        changed_message_ids.append(thread_message.id)
    return changed_message_ids


def mail_thread_case_link_items(
    session: DatabaseSession,
    thread_id: str,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(Case)
        .join(CaseMailLink, CaseMailLink.case_id == Case.id)
        .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
        .where(GmailMessage.thread_id == thread_id)
        .group_by(Case.id)
        .order_by(Case.is_system_case.desc(), Case.updated_at.desc(), Case.name.asc())
    ).scalars().all()
    return [
        {
            "id": case.id,
            "case_id": case.id,
            "title": case.name,
        }
        for case in rows
    ]


def mail_thread_task_link_items(
    session: DatabaseSession,
    thread_message_ids: list[str],
) -> list[dict[str, object]]:
    if len(thread_message_ids) == 0:
        return []
    tasks = session.scalars(
        select(Task)
        .outerjoin(TaskLink, TaskLink.task_id == Task.id)
        .where(
            or_(
                and_(Task.source_type == "mail", Task.source_id.in_(thread_message_ids)),
                and_(
                    TaskLink.linked_type.in_(["mail", "gmail_message"]),
                    TaskLink.linked_id.in_(thread_message_ids),
                ),
            )
        )
        .where(Task.deleted_at.is_(None))
        .group_by(Task.id)
        .order_by(Task.status.asc(), Task.updated_at.desc(), Task.title.asc(), Task.id.asc())
    ).all()
    return [
        {
            "id": task.id,
            "task_id": task.id,
            "case_id": task.case_id,
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
        }
        for task in tasks
    ]


def mail_thread_calendar_event_link_items(
    session: DatabaseSession,
    thread_message_ids: list[str],
) -> list[dict[str, object]]:
    if len(thread_message_ids) == 0:
        return []
    events = session.scalars(
        select(CalendarEvent)
        .join(CalendarEventLink, CalendarEventLink.calendar_event_id == CalendarEvent.id)
        .where(CalendarEventLink.linked_type.in_(["mail", "gmail_message"]))
        .where(CalendarEventLink.linked_id.in_(thread_message_ids))
        .where(CalendarEvent.sync_status != "missing")
        .where(or_(CalendarEvent.google_status.is_(None), CalendarEvent.google_status != "cancelled"))
        .group_by(CalendarEvent.id)
        .order_by(CalendarEvent.start_at.desc(), CalendarEvent.summary.asc(), CalendarEvent.id.asc())
    ).all()
    return [
        {
            "id": event.id,
            "calendar_event_id": event.id,
            "title": event.summary,
            "start_at": event.start_at,
            "end_at": event.end_at,
            "all_day": bool(event.all_day),
            "status": event.google_status,
        }
        for event in events
    ]


def ensure_case_for_mail_assignment(session: DatabaseSession, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")
    return case


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


def normalize_mail_sort(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"importance", "newest"}:
        return normalized
    raise json_error(422, "VALIDATION_ERROR", "Invalid mail sort.")


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
) -> list[tuple[GmailMessage, MailUserState, MailAutoState, str, str, str, str | None]]:
    thread_rows: dict[
        tuple[str, str],
        list[tuple[GmailMessage, MailUserState, MailAutoState]],
    ] = {}
    for message, user_state, auto_state in rows:
        thread_rows.setdefault((message.thread_id, message.received_at[:10]), []).append(
            (message, user_state, auto_state)
        )

    aggregated_rows: list[
        tuple[GmailMessage, MailUserState, MailAutoState, str, str, str, str | None]
    ] = []
    for date_group in thread_rows.values():
        display_group = [
            row for row in date_group if not message_is_sent(row[0])
        ] or date_group
        latest_message, latest_user_state, latest_auto_state = max(
            display_group,
            key=lambda row: (row[0].received_at, row[0].id),
        )
        processed_status = (
            "processed"
            if all(message_is_sent(row[0]) for row in display_group)
            else "unprocessed"
            if any(row[1].processed_status == "unprocessed" for row in display_group)
            else "processed"
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
                (row[1].read_at for row in date_group if row[1].read_at is not None),
                default=None,
            )
        )
        aggregated_rows.append(
            (
                latest_message,
                latest_user_state,
                latest_auto_state,
                effective_importance,
                processed_status,
                thread_read_status,
                thread_read_at,
            )
        )
    return sorted(
        aggregated_rows,
        key=lambda row: (row[0].received_at, row[0].id),
        reverse=True,
    )


def row_needs_action(
    row: tuple[GmailMessage, MailUserState, MailAutoState],
) -> bool:
    message, user_state, auto_state = row
    return (
        not message_is_sent(message)
        and auto_state.pending_reason is None
        and user_state.processed_status != "processed"
        and (user_state.user_importance or auto_state.effective_importance)
        in {"high", "middle"}
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
    thread_message_ids = [thread_message.id for thread_message in thread_messages]
    user_states = {
        state.message_id: state
        for state in session.scalars(
            select(MailUserState).where(
                MailUserState.message_id.in_(thread_message_ids)
            )
        ).all()
    }
    auto_states = {
        state.message_id: state
        for state in session.scalars(
            select(MailAutoState).where(
                MailAutoState.message_id.in_(thread_message_ids)
            )
        ).all()
    }
    attachments_by_message_id = attachment_rows_by_message_id(
        session,
        thread_message_ids,
    )
    sent_attachments_by_message_id = sent_request_attachments_by_message_id(
        session,
        thread_message_ids,
    )
    summaries = session.scalars(
        select(MailSummary)
        .where(
            MailSummary.message_id.in_(thread_message_ids)
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
    thread = session.get(GmailThread, message.thread_id)
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
        "future_importance_rule": (
            thread.future_importance_rule if thread is not None else None
        ),
        "user_state": user_state_data(user_state),
        "auto_state": auto_state_data(auto_state, user_state),
        "summary": (
            mail_thread_summary_data(thread_summary, item_summaries=list(summaries))
            if thread_summary is not None
            else combined_thread_summary_data(list(summaries))
        ),
        "summary_jobs": active_summary_job_status_by_message_id(
            session,
            thread_message_ids,
        ),
        "case_links": mail_thread_case_link_items(session, message.thread_id),
        "task_links": mail_thread_task_link_items(session, thread_message_ids),
        "calendar_event_links": mail_thread_calendar_event_link_items(session, thread_message_ids),
        "attachments": unique_attachment_items(
            unique_thread_attachments(attachments_by_message_id)
            + [
                attachment
                for attachments in sent_attachments_by_message_id.values()
                for attachment in attachments
            ]
        ),
        "drafts": [],
        "available_actions": available_actions(user_state, auto_state),
    }


@dataclass
class MailListItemContext:
    sender_contacts_by_address: dict[str, dict[str, object]]
    summaries_by_thread_id: dict[str, MailSummary]
    thread_summaries_by_thread_id: dict[str, MailThreadSummary]
    attachment_counts_by_message_id: dict[str, int]
    sent_attachment_counts_by_message_id: dict[str, int]
    case_links_by_thread_id: dict[str, list[dict[str, object]]]


def build_mail_list_item_context(
    session: DatabaseSession,
    rows: list[
        tuple[GmailMessage, MailUserState, MailAutoState, str, str, str, str | None]
    ],
) -> MailListItemContext:
    messages = [row[0] for row in rows]
    message_ids = [message.id for message in messages]
    thread_ids = list({message.thread_id for message in messages})
    normalized_addresses = {
        normalize_email_address(message.from_address) for message in messages
    }

    sender_contacts_by_address: dict[str, dict[str, object]] = {}
    contact_rows = []
    if normalized_addresses:
        contact_rows = session.execute(
            select(ContactEmailAddress.normalized_email_address, Contact)
            .join(Contact, Contact.id == ContactEmailAddress.contact_id)
            .where(
                ContactEmailAddress.normalized_email_address.in_(normalized_addresses),
                ContactEmailAddress.deleted_at.is_(None),
                Contact.deleted_at.is_(None),
            )
        ).all()
    contact_ids = list({contact.id for _, contact in contact_rows})
    tags_by_contact_id: dict[str, list[str]] = {contact_id: [] for contact_id in contact_ids}
    if contact_ids:
        for contact_id, tag in session.execute(
            select(ContactTag.contact_id, ContactTag.tag)
            .where(ContactTag.contact_id.in_(contact_ids))
            .order_by(ContactTag.contact_id, ContactTag.tag)
        ):
            tags_by_contact_id[contact_id].append(tag)
    for normalized_address, contact in contact_rows:
        contact_data = contact_summary(contact, include_sender_resolution_mode=True)
        contact_data["tags"] = tags_by_contact_id.get(contact.id, [])
        sender_contacts_by_address[normalized_address] = contact_data

    summaries_by_thread_id: dict[str, MailSummary] = {}
    thread_summaries_by_thread_id: dict[str, MailThreadSummary] = {}
    if thread_ids:
        summary_rows = session.execute(
            select(GmailMessage.thread_id, MailSummary)
            .join(MailSummary, MailSummary.message_id == GmailMessage.id)
            .where(GmailMessage.thread_id.in_(thread_ids))
            .order_by(
                GmailMessage.thread_id,
                GmailMessage.received_at.desc(),
                GmailMessage.id.desc(),
            )
        ).all()
        for thread_id, summary in summary_rows:
            summaries_by_thread_id.setdefault(thread_id, summary)
        thread_summaries_by_thread_id = {
            summary.thread_id: summary
            for summary in session.scalars(
                select(MailThreadSummary).where(MailThreadSummary.thread_id.in_(thread_ids))
            ).all()
        }

    attachment_counts_by_message_id = {message_id: 0 for message_id in message_ids}
    if message_ids:
        for attachment in session.scalars(
            select(GmailMessageAttachment).where(
                GmailMessageAttachment.message_id.in_(message_ids)
            )
        ).all():
            if not is_legacy_inline_image(attachment):
                attachment_counts_by_message_id[attachment.message_id] += 1
    sent_attachments = sent_request_attachments_by_message_id(session, message_ids)
    sent_attachment_counts_by_message_id = {
        message_id: len(attachments)
        for message_id, attachments in sent_attachments.items()
    }

    case_links_by_thread_id: dict[str, list[dict[str, object]]] = {
        thread_id: [] for thread_id in thread_ids
    }
    seen_case_links: set[tuple[str, str]] = set()
    if thread_ids:
        case_rows = session.execute(
            select(GmailMessage.thread_id, Case)
            .join(CaseMailLink, CaseMailLink.message_id == GmailMessage.id)
            .join(Case, Case.id == CaseMailLink.case_id)
            .where(GmailMessage.thread_id.in_(thread_ids))
            .order_by(
                GmailMessage.thread_id,
                Case.is_system_case.desc(),
                Case.updated_at.desc(),
                Case.name.asc(),
            )
        ).all()
        for thread_id, case in case_rows:
            key = (thread_id, case.id)
            if key in seen_case_links:
                continue
            seen_case_links.add(key)
            case_links_by_thread_id[thread_id].append(
                {"id": case.id, "case_id": case.id, "title": case.name}
            )

    return MailListItemContext(
        sender_contacts_by_address=sender_contacts_by_address,
        summaries_by_thread_id=summaries_by_thread_id,
        thread_summaries_by_thread_id=thread_summaries_by_thread_id,
        attachment_counts_by_message_id=attachment_counts_by_message_id,
        sent_attachment_counts_by_message_id=sent_attachment_counts_by_message_id,
        case_links_by_thread_id=case_links_by_thread_id,
    )


def list_item_data(
    session: DatabaseSession,
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
    *,
    effective_importance_override: str | None = None,
    processed_status_override: str | None = None,
    read_status_override: str | None = None,
    read_at_override: str | None = None,
    context: MailListItemContext | None = None,
) -> dict[str, object]:
    effective_importance = (
        effective_importance_override
        or user_state.user_importance
        or auto_state.effective_importance
    )
    is_sent = message_is_sent(message)
    if context is None:
        contact_row = contact_for_address(session, message.from_address)
        sender_contact = (
            contact_summary(
                contact_row,
                session,
                include_sender_resolution_mode=True,
            )
            if contact_row is not None
            else None
        )
        summary = latest_thread_summary(session, message.thread_id)
        thread_summary = stored_thread_summary(session, message.thread_id)
        attachment_count = attachment_count_for_message(session, message.id) + len(
            sent_request_attachments_by_message_id(session, [message.id]).get(message.id, [])
        )
        case_links = mail_thread_case_link_items(session, message.thread_id)
    else:
        sender_contact = context.sender_contacts_by_address.get(
            normalize_email_address(message.from_address)
        )
        summary = context.summaries_by_thread_id.get(message.thread_id)
        thread_summary = context.thread_summaries_by_thread_id.get(message.thread_id)
        attachment_count = context.attachment_counts_by_message_id.get(message.id, 0) + (
            context.sent_attachment_counts_by_message_id.get(message.id, 0)
        )
        case_links = context.case_links_by_thread_id.get(message.thread_id, [])
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
        "processed_status": processed_status_override or user_state.processed_status,
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
        "sender_contact": sender_contact,
        "attachment_count": attachment_count,
        "has_attachments": attachment_count > 0,
        "case_links": case_links,
        "summary": None
        if is_sent or effective_importance not in SUMMARY_TARGET_IMPORTANCE
        else (
            thread_summary.summary_text
            if thread_summary is not None
            else summary.summary_text if summary is not None else None
        ),
    }


@router.get("/attachments/{attachment_id}/download")
def download_mail_attachment(
    attachment_id: str,
    session: DatabaseSession = Depends(get_session),
) -> FileResponse:
    attachment = session.get(GmailMessageAttachment, attachment_id)
    if attachment is None:
        raise json_error(404, "NOT_FOUND", "Mail attachment not found.")

    cached_response = cached_mail_attachment_response(session, attachment)
    if cached_response is not None:
        return cached_response

    raw_data = fetch_gmail_attachment_bytes(session, attachment)
    now = jst_iso()
    storage_object = save_storage_object(
        session,
        scope=GMAIL_ATTACHMENT_STORAGE_SCOPE,
        filename=attachment.filename,
        content_type=attachment.mime_type or "application/octet-stream",
        data=raw_data,
        now=now,
        source_type="mail_attachment",
        source_message_id=attachment.message_id,
    )
    attachment.storage_object_id = storage_object.id
    attachment.byte_size = len(raw_data)
    attachment.updated_at = now
    attachment.version += 1
    session.commit()
    return storage_object_file_response(
        storage_object,
        session,
        download_filename=attachment.filename,
    )


@router.post("/attachments/{attachment_id}/move-to-storage")
def move_mail_attachment_to_storage(
    attachment_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    attachment = session.get(GmailMessageAttachment, attachment_id)
    if attachment is None:
        raise json_error(404, "NOT_FOUND", "Mail attachment not found.")

    existing_storage_object = (
        session.get(StorageObject, attachment.storage_object_id)
        if attachment.storage_object_id is not None
        else None
    )
    now = jst_iso()
    if (
        existing_storage_object is not None
        and existing_storage_object.status == "active"
        and existing_storage_object.scope == "managed"
    ):
        existing_storage_object.source_type = "mail_attachment"
        existing_storage_object.source_message_id = attachment.message_id
        existing_storage_object.updated_at = now
        existing_storage_object.version += 1
        session.commit()
        return {
            "ok": True,
            "data": {
                "attachment": mail_attachment_data(attachment),
                "storage_object": storage_object_data(existing_storage_object),
            },
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
        scope="managed",
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
        and existing_storage_object.scope != "managed"
    ):
        delete_storage_object(existing_storage_object, session=session, now=now)
    attachment.storage_object_id = storage_object.id
    attachment.byte_size = len(raw_data)
    attachment.updated_at = now
    attachment.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "attachment": mail_attachment_data(attachment),
            "storage_object": storage_object_data(storage_object),
        },
    }


@router.post("/attachments/{attachment_id}/fetch-job")
def enqueue_mail_attachment_fetch(
    attachment_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    attachment = session.get(GmailMessageAttachment, attachment_id)
    if attachment is None:
        raise json_error(404, "NOT_FOUND", "Mail attachment not found.")
    now = jst_iso()
    job_id = enqueue_mail_attachment_fetch_job(
        session,
        attachment,
        now,
        target_scope="managed",
        reason="manual_request",
    )
    session.commit()
    kick_job_drain(reason="mail_attachment_fetch_requested")
    return {
        "ok": True,
        "data": {
            "job_id": job_id,
            "attachment": mail_attachment_data(attachment),
        },
    }


def fetch_gmail_attachment_bytes(
    session: DatabaseSession,
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
        raw_data = base64.urlsafe_b64decode(
            (encoded_data + "=" * (-len(encoded_data) % 4)).encode("ascii")
        )
    except (binascii.Error, ValueError) as error:
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            "Gmail attachment data is invalid.",
        ) from error
    return raw_data


def cached_mail_attachment_response(
    session: DatabaseSession,
    attachment: GmailMessageAttachment,
) -> FileResponse | None:
    storage_object = (
        session.get(StorageObject, attachment.storage_object_id)
        if attachment.storage_object_id is not None
        else None
    )
    if (
        storage_object is None
        or storage_object.status != "active"
        or storage_object.scope not in MAIL_ATTACHMENT_STORAGE_SCOPES
    ):
        storage_object = managed_storage_object_for_attachment(session, attachment)
        if storage_object is None:
            return None
    object_path = storage_object_absolute_path(storage_object, session)
    if not object_path.is_file():
        managed_storage_object = managed_storage_object_for_attachment(
            session,
            attachment,
        )
        if managed_storage_object is None or managed_storage_object.id == storage_object.id:
            return None
        object_path = storage_object_absolute_path(managed_storage_object, session)
        if not object_path.is_file():
            return None
        storage_object = managed_storage_object
    if attachment.storage_object_id != storage_object.id:
        attachment.storage_object_id = storage_object.id
        attachment.updated_at = jst_iso()
        attachment.version += 1
        session.commit()
    return storage_object_file_response(
        storage_object,
        session,
        download_filename=attachment.filename,
    )


def managed_storage_object_for_attachment(
    session: DatabaseSession,
    attachment: GmailMessageAttachment,
) -> StorageObject | None:
    statement = (
        select(StorageObject)
        .where(StorageObject.status == "active")
        .where(StorageObject.scope == "managed")
        .where(StorageObject.source_type == "mail_attachment")
        .where(StorageObject.source_message_id == attachment.message_id)
        .where(StorageObject.original_filename == attachment.filename)
        .order_by(StorageObject.created_at.desc(), StorageObject.id.desc())
    )
    if attachment.byte_size > 0:
        statement = statement.where(StorageObject.byte_size == attachment.byte_size)
    candidates = session.scalars(statement.limit(5)).all()
    for candidate in candidates:
        if storage_object_absolute_path(candidate, session).is_file():
            return candidate
    return None


def storage_object_file_response(
    storage_object: StorageObject,
    session: DatabaseSession,
    *,
    download_filename: str,
) -> FileResponse:
    response = FileResponse(
        storage_object_absolute_path(storage_object, session),
        media_type=storage_object.content_type or "application/octet-stream",
        filename=download_filename,
    )
    session.close()
    return response


def sent_attachment_content(
    session: DatabaseSession,
    attachment: dict[str, object],
    filename: str,
) -> bytes:
    storage_object_id = attachment.get("storage_object_id")
    if isinstance(storage_object_id, str) and storage_object_id.strip() != "":
        storage_object = session.get(StorageObject, storage_object_id.strip())
        if storage_object is None or storage_object.status != "active":
            raise json_error(404, "NOT_FOUND", "Sent attachment file not found.")
        object_path = storage_object_absolute_path(storage_object, session)
        if not object_path.is_file():
            raise json_error(404, "NOT_FOUND", "Sent attachment file not found.")
        return object_path.read_bytes()

    data_base64 = attachment.get("data_base64")
    if not isinstance(data_base64, str) or data_base64.strip() == "":
        raise json_error(404, "NOT_FOUND", "Sent attachment data not found.")
    try:
        return base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Sent attachment data is invalid.") from error


@router.get("/send-requests/{send_request_id}/attachments/{attachment_index}/download")
def download_sent_mail_attachment(
    send_request_id: str,
    attachment_index: int,
    session: DatabaseSession = Depends(get_session),
) -> Response:
    send_request = session.get(MailSendRequest, send_request_id)
    if send_request is None:
        raise json_error(404, "NOT_FOUND", "Sent mail attachment not found.")

    attachments = json_dict_list(send_request.attachment_data_json)
    if attachment_index < 0 or attachment_index >= len(attachments):
        raise json_error(404, "NOT_FOUND", "Sent mail attachment not found.")

    attachment = attachments[attachment_index]
    filename = sent_attachment_filename(attachment, attachment_index)
    content = sent_attachment_content(session, attachment, filename)
    content_type = sent_attachment_content_type(attachment)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": (
                "attachment; "
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
        },
    )


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
    to_addresses = normalize_address_list(
        resolve_recipient_selectors(session, payload.to_addresses)
    )
    if len(to_addresses) == 0:
        raise json_error(422, "VALIDATION_ERROR", "At least one recipient is required.")

    subject = (payload.subject or "").strip()
    if subject == "":
        raise json_error(422, "VALIDATION_ERROR", "Subject is required.")

    body_text = payload.body_text
    if body_text.strip() == "":
        raise json_error(422, "VALIDATION_ERROR", "Body text is required.")

    if payload.reply_to_message_id is not None:
        reply_to_message = session.get(GmailMessage, payload.reply_to_message_id)
        if reply_to_message is None:
            raise json_error(404, "NOT_FOUND", "Reply target mail not found.")

    selected_cases: list[Case] = []
    seen_case_ids: set[str] = set()
    for case_id in payload.case_ids or []:
        normalized_case_id = case_id.strip()
        if normalized_case_id == "" or normalized_case_id in seen_case_ids:
            continue
        selected_cases.append(ensure_case_for_mail_assignment(session, normalized_case_id))
        seen_case_ids.add(normalized_case_id)

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
        validated_future_send_time(payload.scheduled_at)
        if payload.scheduled_at is not None and payload.scheduled_at.strip() != ""
        else jst_iso(jst_now() + timedelta(minutes=1))
    )
    send_request = MailSendRequest(
        id=new_id("mail_send"),
        status="scheduled_mock",
        to_addresses_json=json.dumps(to_addresses, ensure_ascii=True),
        cc_addresses_json=json.dumps(
            normalize_address_list(
                resolve_recipient_selectors(session, payload.cc_addresses)
            ),
            ensure_ascii=True,
        ),
        bcc_addresses_json=json.dumps(
            normalize_address_list(
                resolve_recipient_selectors(session, payload.bcc_addresses)
            ),
            ensure_ascii=True,
        ),
        subject=subject,
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
    session.flush()
    for case in selected_cases:
        session.add(
            MailSendRequestCaseLink(
                id=new_id("mail_send_case_link"),
                send_request_id=send_request.id,
                case_id=case.id,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        case.updated_at = now
        case.version += 1
    enqueue_mail_send_mock_job(
        session,
        send_request,
        now,
        available_at=scheduled_at,
    )
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.get("/llm-personalization")
def get_llm_personalization(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {
        "ok": True,
        "data": {
            "functions": [
                llm_function_instruction_data(session, function_type)
                for function_type in LLM_FUNCTION_TYPES
            ]
        },
    }


@router.patch("/llm-personalization")
def update_llm_personalization(
    payload: LlmFunctionInstructionPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    function_type = payload.function_type.strip()
    upsert_llm_settings_rule(session, payload, jst_iso())
    session.commit()
    return {
        "ok": True,
        "data": llm_function_instruction_data(session, function_type),
    }


@router.get("/draft-generation-standard-prompt")
def get_mail_draft_generation_standard_prompt(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {
        "ok": True,
        "data": {
            "standard_prompt": read_mail_draft_generation_standard_prompt(session),
            "generation_language": read_mail_draft_generation_language(session),
        },
    }


@router.patch("/draft-generation-standard-prompt")
def update_mail_draft_generation_standard_prompt(
    payload: MailDraftGenerationStandardPromptPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    standard_prompt = (
        payload.standard_prompt.strip()
        if payload.standard_prompt is not None
        else read_mail_draft_generation_standard_prompt(session)
    )
    generation_language = normalize_generation_language(
        payload.generation_language
        if payload.generation_language is not None
        else read_mail_draft_generation_language(session)
    )
    write_mail_draft_generation_standard_prompt(session, standard_prompt, now)
    write_mail_draft_generation_language(session, generation_language, now)
    session.commit()
    return {
        "ok": True,
        "data": {
            "standard_prompt": standard_prompt,
            "generation_language": generation_language,
        },
    }


@router.post("/generate-draft")
def generate_mail_draft(
    payload: MailDraftGenerationRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    to_addresses = normalize_address_list(
        resolve_recipient_selectors(session, payload.to_addresses)
    )
    cc_addresses = normalize_address_list(
        resolve_recipient_selectors(session, payload.cc_addresses)
    )
    bcc_addresses = normalize_address_list(
        resolve_recipient_selectors(session, payload.bcc_addresses)
    )
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
    selected_generation_language = normalize_generation_language(
        payload.generation_language
        if payload.generation_language is not None
        else read_mail_draft_generation_language(session)
    )
    expected_language = expected_reply_language(
        reply_to_message=reply_to_message,
        instruction=payload.instruction,
        standard_prompt=payload.standard_prompt,
        generation_language=selected_generation_language,
    )
    related_case_summaries = payload.related_case_summaries or []
    try:
        provider = build_mail_draft_generation_provider(function_type)
    except OpenAIProviderError as error:
        raise json_error(
            502,
            "LLM_PROVIDER_ERROR",
            f"Mail draft generation failed: {error}",
        ) from error
    active_settings_rule = read_llm_settings_rule(session, function_type)
    has_active_settings_rule = bool(
        active_settings_rule is not None
        and active_settings_rule.deleted_at is None
        and active_settings_rule.is_enabled
        and active_settings_rule.instruction_text.strip()
    )
    input_payload = {
        "instruction": payload.instruction or "",
        "standard_prompt": "" if has_active_settings_rule else (payload.standard_prompt or ""),
        "language_generation_prompt": generation_language_prompt(expected_language),
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
    provider_input_payload = with_llm_personalization(
        session, function_type, input_payload
    )
    now = jst_iso()
    try:
        provider_response = provider.complete_json(
            function_type=function_type,
            input_payload=provider_input_payload,
        )
    except OpenAIProviderError as error:
        raise json_error(
            502,
            "LLM_PROVIDER_ERROR",
            f"Mail draft generation failed: {error}",
        ) from error
    output = provider_response.output
    retry_count = 0
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
                "has_standard_prompt": bool(str(input_payload["standard_prompt"]).strip()),
                "generation_language": selected_generation_language,
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
                "standard_prompt_length": len(str(input_payload["standard_prompt"])),
                "language_generation_prompt": generation_language_prompt(
                    expected_language
                ),
                "auto_body_text_length": len(payload.auto_body_text or ""),
                "current_body_length": len(payload.body_text or ""),
                "detected_reply_language": language_label(expected_language),
                "recipient_contact_memo_count": len(input_payload["recipient_contact_memos"]),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        applied_instruction_rule_ids_json=json.dumps(
            llm_applied_instruction_rule_ids(provider_input_payload),
            ensure_ascii=True,
        ),
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


@router.get("/send-requests/{send_request_id}")
def get_mail_send_request(
    send_request_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    send_request = get_send_request_or_404(session, send_request_id)
    data = mail_send_request_data(send_request)
    data["case_ids"] = [
        str(item["case_id"])
        for item in send_request_case_link_items(session, send_request.id)
    ]
    return {"ok": True, "data": data}


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


def update_mutable_send_request(
    session: DatabaseSession,
    send_request_id: str,
    *,
    status: str,
    scheduled_at: str | None,
    now: str,
    preserve_scheduled_at: bool = False,
) -> MailSendRequest:
    immutable_statuses = {
        "sent_mock",
        "sent_gmail",
        "sending_mock",
        "sending_gmail",
        "canceled",
    }
    values: dict[str, object] = {
        "status": status,
        "updated_at": now,
        "version": MailSendRequest.version + 1,
    }
    if not preserve_scheduled_at:
        values["scheduled_at"] = scheduled_at
    result = session.execute(
        update(MailSendRequest)
        .where(MailSendRequest.id == send_request_id)
        .where(MailSendRequest.status.notin_(immutable_statuses))
        .values(**values)
    )
    if result.rowcount != 1:
        session.rollback()
        send_request = get_send_request_or_404(session, send_request_id)
        ensure_send_request_mutable(send_request)
        raise json_error(409, "CONFLICT", "Mail send request changed concurrently.")
    send_request = session.get(MailSendRequest, send_request_id)
    if send_request is None:
        raise json_error(404, "NOT_FOUND", "Mail send request not found.")
    return send_request


@router.post("/send-requests/{send_request_id}/send-now")
def send_mail_request_now(
    send_request_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    send_request = update_mutable_send_request(
        session,
        send_request_id,
        status="queued_mock",
        scheduled_at=None,
        now=now,
    )
    supersede_pending_mail_send_jobs(session, send_request.id, now)
    enqueue_mail_send_mock_job(session, send_request, now)
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.patch("/send-requests/{send_request_id}/schedule")
def reschedule_mail_request(
    send_request_id: str,
    payload: MailSendSchedulePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    scheduled_at = validated_future_send_time(payload.scheduled_at)
    now = jst_iso()
    send_request = update_mutable_send_request(
        session,
        send_request_id,
        status="scheduled_mock",
        scheduled_at=scheduled_at,
        now=now,
    )
    supersede_pending_mail_send_jobs(session, send_request.id, now)
    enqueue_mail_send_mock_job(session, send_request, now, available_at=scheduled_at)
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


@router.post("/send-requests/{send_request_id}/cancel")
def cancel_mail_send_request(
    send_request_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    send_request = update_mutable_send_request(
        session,
        send_request_id,
        status="canceled",
        scheduled_at=None,
        now=now,
        preserve_scheduled_at=True,
    )
    supersede_pending_mail_send_jobs(session, send_request.id, now)
    session.commit()
    return {"ok": True, "data": mail_send_request_data(send_request)}


def low_mail_review_item_data(
    session: DatabaseSession,
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
    *,
    include_body: bool = False,
) -> dict[str, object]:
    item = list_item_data(session, message, user_state, auto_state)
    item["snippet"] = message.snippet
    if include_body:
        item["body_text"] = message.body_text
    return item


def mail_is_available_for_low_review(
    message: GmailMessage,
    user_state: MailUserState,
    auto_state: MailAutoState,
) -> bool:
    return (
        not message_is_sent(message)
        and message.received_at[:10] == jst_now().date().isoformat()
        and auto_state.pending_reason is None
        and (user_state.user_importance or auto_state.effective_importance)
        in {"low", "skip"}
    )


@router.get("/review/today")
def list_today_low_mail_review(
    request: Request,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    require_session_access_mode(session, request, ACCESS_MODE_LOW_MAIL_REVIEW)
    today = jst_now().date().isoformat()
    rows = session.execute(
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .where(GmailMessage.received_at >= f"{today}T00:00:00+09:00")
        .where(GmailMessage.received_at <= f"{today}T23:59:59.999999+09:00")
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    items = [
        low_mail_review_item_data(session, message, user_state, auto_state)
        for message, user_state, auto_state in rows
        if mail_is_available_for_low_review(message, user_state, auto_state)
    ]
    items.sort(
        key=lambda item: 0 if item["effective_importance"] == "low" else 1
    )
    return {"ok": True, "data": {"date": today, "items": items}}


@router.get("/review/{message_id}")
def get_low_mail_review_detail(
    message_id: str,
    request: Request,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    require_session_access_mode(session, request, ACCESS_MODE_LOW_MAIL_REVIEW)
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    if not mail_is_available_for_low_review(message, user_state, auto_state):
        raise json_error(404, "NOT_FOUND", "Mail is not available for review.")
    return {
        "ok": True,
        "data": low_mail_review_item_data(
            session,
            message,
            user_state,
            auto_state,
            include_body=True,
        ),
    }


@router.post("/review/{message_id}/promote-to-middle")
def promote_review_mail_to_middle(
    message_id: str,
    request: Request,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    require_session_access_mode(session, request, ACCESS_MODE_LOW_MAIL_REVIEW)
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    if not mail_is_available_for_low_review(message, user_state, auto_state):
        raise json_error(409, "CONFLICT", "Mail is not available for review.")

    now = jst_iso()
    previous_importance = user_state.user_importance or auto_state.effective_importance
    user_state.user_importance = "middle"
    clear_done_after_leaving_skip(
        user_state,
        previous_importance=previous_importance,
        new_importance="middle",
    )
    user_state.updated_at = now
    user_state.version += 1
    auto_state.effective_importance = "middle"
    auto_state.updated_at = now
    auto_state.version += 1
    enqueue_mail_summary_job(session, message, now)
    session.commit()
    kick_job_drain(reason="review_mail_promoted")
    return {"ok": True, "data": {"id": message.id, "importance": "middle"}}


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
    contact_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "newest",
    limit: int = 50,
    cursor: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized_tab = normalize_tab_filter(tab)
    normalized_processed = normalize_processed_filter(processed)
    normalized_contact_status = normalize_contact_status_filter(contact_status)
    normalized_read = normalize_read_filter(read)
    normalized_importance_any = normalize_importance_filter_set(importance_any)
    normalized_sort = normalize_mail_sort(sort)
    normalized_limit = normalize_limit(limit)
    query_tokens = [token.lower() for token in q.strip().split()] if q else []
    statement = (
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .options(
            load_only(
                GmailMessage.id,
                GmailMessage.gmail_message_id,
                GmailMessage.gmail_thread_id,
                GmailMessage.thread_id,
                GmailMessage.received_at,
                GmailMessage.subject,
                GmailMessage.from_address,
                GmailMessage.from_name,
                GmailMessage.sender_address,
                GmailMessage.reply_to_address,
                GmailMessage.to_addresses_json,
                GmailMessage.cc_addresses_json,
                GmailMessage.bcc_addresses_json,
                GmailMessage.message_id_header,
                GmailMessage.list_id,
                GmailMessage.gmail_labels_json,
            )
        )
    )
    if date_from is not None and date_from.strip() != "":
        statement = statement.where(GmailMessage.received_at >= date_from.strip())
    if date_to is not None and date_to.strip() != "":
        statement = statement.where(GmailMessage.received_at <= date_to.strip())
    if query_tokens:
        searchable_columns = (
            GmailMessage.subject,
            GmailMessage.from_address,
            GmailMessage.from_name,
            GmailMessage.sender_address,
            GmailMessage.reply_to_address,
            GmailMessage.to_addresses_json,
            GmailMessage.cc_addresses_json,
            GmailMessage.bcc_addresses_json,
            GmailMessage.message_id_header,
            GmailMessage.list_id,
            GmailMessage.body_text,
            GmailMessage.snippet,
        )
        matching_threads = select(GmailMessage.thread_id).where(
            *[
                or_(
                    *[
                        func.instr(func.lower(func.coalesce(column, "")), token) > 0
                        for column in searchable_columns
                    ]
                )
                for token in query_tokens
            ]
        )
        statement = statement.where(GmailMessage.thread_id.in_(matching_threads))
    statement = statement.order_by(GmailMessage.received_at.desc(), GmailMessage.id)
    all_rows = session.execute(statement).all()
    participant_addresses: set[str] | None = None
    if contact_id is not None and contact_id.strip() != "":
        participant_addresses = contact_participant_addresses(session, contact_id.strip())
        matching_thread_ids = {
            message.thread_id
            for message, _, _ in all_rows
            if message_has_participant(message, participant_addresses)
        }
        all_rows = [row for row in all_rows if row[0].thread_id in matching_thread_ids]
    if needs_action:
        all_rows = [row for row in all_rows if row_needs_action(row)]

    aggregated_rows = aggregate_thread_rows(all_rows)
    if needs_action:
        pass
    else:
        if normalized_processed in {"0", "unprocessed"}:
            aggregated_rows = [
                row
                for row in aggregated_rows
                if row[4] == "unprocessed"
            ]
        elif normalized_processed in {"1", "processed"}:
            aggregated_rows = [
                row for row in aggregated_rows if row[4] == "processed"
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
                and row[4] == "processed"
            ]
        elif normalized_tab == "unprocessed":
            aggregated_rows = [
                row
                for row in aggregated_rows
                if row[2].pending_reason is None
                and row[3] != "skip"
                and row[4] == "unprocessed"
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
            row for row in aggregated_rows if row[5] == normalized_read
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
        if participant_addresses is not None:
            send_requests = [
                send_request
                for send_request in send_requests
                if send_request_has_participant(send_request, participant_addresses)
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

    cursor_values: tuple[str, str] | None = None
    if cursor is not None and cursor.strip() != "":
        cursor_values = decode_cursor(cursor.strip())
        cursor_received_at, cursor_id = cursor_values
    if cursor_values is not None and normalized_sort == "newest":
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

    real_candidates = [
        (
            row[0].received_at,
            row[0].id,
            "mail",
            row,
            IMPORTANCE_RANKS.get(row[3], 99),
        )
        for row in aggregated_rows
    ]
    send_candidates = [
        (
            send_request_visible_at(send_request),
            send_request.id,
            "send_request",
            send_request,
            IMPORTANCE_RANKS["sent"],
        )
        for send_request in send_requests
    ]
    combined_candidates = sorted(
        [*real_candidates, *send_candidates],
        key=lambda row: (row[0], row[1]),
        reverse=True,
    )
    if normalized_sort == "importance":
        # The existing newest-first order remains the stable tie breaker.
        combined_candidates.sort(key=lambda row: row[4])
        if cursor_values is not None:
            cursor_index = next(
                (
                    index
                    for index, row in enumerate(combined_candidates)
                    if (row[0], row[1]) == cursor_values
                ),
                None,
            )
            combined_candidates = (
                combined_candidates[cursor_index + 1 :]
                if cursor_index is not None
                else []
            )
    visible_candidates = combined_candidates[:normalized_limit]
    has_next = len(combined_candidates) > normalized_limit
    next_cursor = (
        encode_cursor_values(visible_candidates[-1][0], visible_candidates[-1][1])
        if has_next and visible_candidates
        else None
    )
    visible_mail_rows = [
        candidate[3]
        for candidate in visible_candidates
        if candidate[2] == "mail"
    ]
    item_context = build_mail_list_item_context(session, visible_mail_rows)
    items: list[dict[str, object]] = []
    for candidate in visible_candidates:
        if candidate[2] == "send_request":
            items.append(send_request_list_item_data(session, candidate[3]))
            continue
        (
            message,
            user_state,
            auto_state,
            effective_importance,
            processed_status,
            thread_read_status,
            thread_read_at,
        ) = candidate[3]
        items.append(
            list_item_data(
                session,
                message,
                user_state,
                auto_state,
                effective_importance_override=effective_importance,
                processed_status_override=processed_status,
                read_status_override=thread_read_status,
                read_at_override=thread_read_at,
                context=item_context,
            )
        )
    return {
        "ok": True,
        "data": {
            "items": items,
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
        .options(
            load_only(
                GmailMessage.id,
                GmailMessage.thread_id,
                GmailMessage.received_at,
                GmailMessage.gmail_labels_json,
            )
        )
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
            and row[4] == "processed"
        ]
    elif normalized_tab == "unprocessed":
        aggregated_rows = [
            row
            for row in aggregated_rows
            if row[2].pending_reason is None
            and row[3] != "skip"
            and row[4] == "unprocessed"
        ]

    date_counts: dict[str, int] = {}
    for message, _, _, _, _, _, _ in aggregated_rows:
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
        .options(
            load_only(
                GmailMessage.id,
                GmailMessage.received_at,
                GmailMessage.gmail_labels_json,
            )
        )
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


def mail_case_assignment_target(
    session: DatabaseSession,
    target_id: str,
) -> tuple[GmailMessage | None, MailSendRequest | None]:
    message = session.get(GmailMessage, target_id)
    if message is not None:
        return message, None
    send_request = session.get(MailSendRequest, target_id)
    if send_request is None:
        raise json_error(404, "NOT_FOUND", "Mail not found.")
    if send_request.sent_message_id is not None:
        sent_message = session.get(GmailMessage, send_request.sent_message_id)
        if sent_message is None:
            raise json_error(409, "SEND_NOT_INGESTED", "Sent mail is not available yet.")
        return sent_message, send_request
    if send_request.status == "canceled":
        raise json_error(409, "SEND_CANCELED", "Canceled mail cannot be assigned to a Case.")
    return None, send_request


@router.get("/{message_id}/case-links")
def get_mail_thread_case_links(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, send_request = mail_case_assignment_target(session, message_id)
    if message is not None:
        return {
            "ok": True,
            "data": {"items": mail_thread_case_link_items(session, message.thread_id)},
        }
    assert send_request is not None
    return {
        "ok": True,
        "data": {"items": send_request_case_link_items(session, send_request.id)},
    }


@router.post("/{message_id}/case-links")
def assign_mail_thread_to_case(
    message_id: str,
    payload: MailThreadCaseAssignRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, send_request = mail_case_assignment_target(session, message_id)
    case = ensure_case_for_mail_assignment(session, payload.case_id)
    now = jst_iso()
    if message is None:
        assert send_request is not None
        existing = session.scalar(
            select(MailSendRequestCaseLink).where(
                MailSendRequestCaseLink.send_request_id == send_request.id,
                MailSendRequestCaseLink.case_id == case.id,
            )
        )
        if existing is None:
            session.add(
                MailSendRequestCaseLink(
                    id=new_id("mail_send_case_link"),
                    send_request_id=send_request.id,
                    case_id=case.id,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
            case.updated_at = now
            case.version += 1
        session.commit()
        return {"ok": True, "data": send_request_detail_data(session, send_request)}

    user_state = session.scalar(
        select(MailUserState).where(MailUserState.message_id == message.id)
    )
    auto_state = session.scalar(
        select(MailAutoState).where(MailAutoState.message_id == message.id)
    )
    if user_state is None or auto_state is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Mail state is missing.")
    messages = thread_messages(session, message.thread_id)
    message_ids = [thread_message.id for thread_message in messages]
    existing_message_ids = set(
        session.scalars(
            select(CaseMailLink.message_id)
            .where(CaseMailLink.case_id == case.id)
            .where(CaseMailLink.message_id.in_(message_ids))
        ).all()
    )
    for thread_message in messages:
        if thread_message.id in existing_message_ids:
            continue
        session.add(
            CaseMailLink(
                id=new_id("case_mail_link"),
                case_id=case.id,
                message_id=thread_message.id,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
    ensure_case_stakeholders_for_mail_senders(session, case, messages, now=now)
    apply_case_link_importance_floor(session, message.thread_id, now)
    case.updated_at = now
    case.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.delete("/{message_id}/case-links/{case_id}")
def unassign_mail_thread_from_case(
    message_id: str,
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, send_request = mail_case_assignment_target(session, message_id)
    case = ensure_case_for_mail_assignment(session, case_id)
    if message is None:
        assert send_request is not None
        links = session.scalars(
            select(MailSendRequestCaseLink).where(
                MailSendRequestCaseLink.send_request_id == send_request.id,
                MailSendRequestCaseLink.case_id == case.id,
            )
        ).all()
        for link in links:
            session.delete(link)
        if links:
            now = jst_iso()
            case.updated_at = now
            case.version += 1
        session.commit()
        return {"ok": True, "data": send_request_detail_data(session, send_request)}

    user_state = session.scalar(
        select(MailUserState).where(MailUserState.message_id == message.id)
    )
    auto_state = session.scalar(
        select(MailAutoState).where(MailAutoState.message_id == message.id)
    )
    if user_state is None or auto_state is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Mail state is missing.")
    message_ids = [thread_message.id for thread_message in thread_messages(session, message.thread_id)]
    links = session.scalars(
        select(CaseMailLink)
        .where(CaseMailLink.case_id == case.id)
        .where(CaseMailLink.message_id.in_(message_ids))
    ).all()
    for link in links:
        session.delete(link)
    if links:
        now = jst_iso()
        case.updated_at = now
        case.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.patch("/{message_id}/thread-importance-rule")
def update_mail_thread_importance_rule(
    message_id: str,
    payload: MailThreadImportanceRuleRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    rule = payload.future_importance_rule
    if rule not in {None, "low"}:
        raise json_error(422, "VALIDATION_ERROR", "Unsupported thread importance rule.")
    thread = session.get(GmailThread, message.thread_id)
    if thread is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Mail thread is missing.")
    now = jst_iso()
    thread.future_importance_rule = rule
    thread.updated_at = now
    thread.version += 1
    session.commit()
    return {"ok": True, "data": detail_data(session, message, user_state, auto_state)}


@router.get("/{message_id}")
def get_mail_detail(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message = session.get(GmailMessage, message_id)
    if message is None:
        send_request = session.get(MailSendRequest, message_id)
        if send_request is None or send_request.reply_to_message_id is not None:
            raise json_error(404, "NOT_FOUND", "Mail not found.")
        if send_request.sent_message_id is not None:
            message = session.get(GmailMessage, send_request.sent_message_id)
            if message is None:
                raise json_error(409, "SEND_NOT_INGESTED", "Sent mail is not available yet.")
        elif send_request.status in SEND_REQUEST_VISIBLE_STATUSES:
            return {"ok": True, "data": send_request_detail_data(session, send_request)}
        else:
            raise json_error(404, "NOT_FOUND", "Mail not found.")
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
    previous_importance = user_state.user_importance or auto_state.effective_importance
    user_state.user_importance = importance
    clear_done_after_leaving_skip(
        user_state,
        previous_importance=previous_importance,
        new_importance=importance,
    )
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


@router.post("/{message_id}/allow-llm")
def allow_mail_llm(
    message_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message, user_state, auto_state = get_mail_bundle(session, message_id)
    if message_is_sent(message):
        raise json_error(409, "CONFLICT", "Sent mail does not need LLM allow.")
    if auto_state.pending_reason is not None:
        raise json_error(409, "CONFLICT", "Pending mail cannot be allowed for LLM yet.")

    now = jst_iso()
    auto_state.llm_blocked = 0
    auto_state.llm_block_reason = None
    auto_state.llm_blocked_at = None

    contact = contact_for_address(session, message.from_address)
    queued_job_id: str | None = None
    if contact is not None:
        result = apply_contact_mail_importance_rule(
            session,
            message=message,
            auto_state=auto_state,
            contact=contact,
            now=now,
        )
        queued_job_id = result.queued_job_id
    else:
        auto_state.effective_importance = (
            "high" if auto_state.external_importance == "high" else "unclassified"
        )
        queued_job_id = enqueue_importance_job(session, message, now)

    auto_state.updated_at = now
    auto_state.version += 1
    session.commit()
    if queued_job_id is not None:
        kick_job_drain(reason="mail_llm_allowed")
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
