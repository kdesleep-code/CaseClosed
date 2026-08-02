from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import Contact
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.services.llm_provider import FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import llm_applied_instruction_rule_ids
from caseclosed.services.llm_provider import with_llm_personalization
from caseclosed.services.llm_provider import build_contact_ai_memo_update_provider

FUNCTION_TYPE = FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE
WEEKLY_UPDATE_INTERVAL_DAYS = 7
WEEKLY_SLOT_COUNT = 7 * 24
MAX_BATCH_MESSAGES = 20


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def enqueue_contact_ai_memo_update_job(
    session,
    *,
    contact: Contact,
    message: GmailMessage,
    now: str,
    reason: str,
    allow_archived_initial: bool = False,
) -> str | None:
    if not should_update_contact_ai_memo(contact) and not should_create_archived_initial_ai_memo(
        contact,
        allow_archived_initial=allow_archived_initial,
    ):
        return None
    available_at = None
    schedule_scope = "single_message"
    if (
        should_update_contact_ai_memo(contact)
        and not allow_archived_initial
        and not contact_needs_initial_ai_memo(contact)
    ):
        existing_job_id = pending_contact_ai_memo_update_job_id(session, contact.id)
        if existing_job_id is not None:
            return existing_job_id
        available_at = next_weekly_contact_update_at(contact.id, now)
        schedule_scope = "weekly_batch"

    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type=FUNCTION_TYPE,
            priority=140,
            status="pending",
            payload_json=json.dumps(
                {
                    "contact_id": contact.id,
                    "message_id": message.id,
                    "gmail_message_id": message.gmail_message_id,
                    "reason": reason,
                    "allow_archived_initial": allow_archived_initial,
                    "schedule_scope": schedule_scope,
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


def pending_contact_ai_memo_update_job_id(session, contact_id: str) -> str | None:
    for job in session.scalars(
        select(Job).where(
            Job.job_type == FUNCTION_TYPE,
            Job.status.in_(["pending", "running"]),
        )
    ).all():
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            continue
        if payload.get("contact_id") == contact_id:
            return job.id
    return None


def next_weekly_contact_update_at(contact_id: str, now_iso: str) -> str:
    now = runtime.parse_iso_datetime(now_iso)
    digest = sha256(contact_id.encode("utf-8")).digest()
    slot = int.from_bytes(digest[:2], "big") % WEEKLY_SLOT_COUNT
    slot_weekday = slot // 24
    slot_hour = slot % 24
    days_ahead = (slot_weekday - now.weekday()) % 7
    candidate = (
        now.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
        + timedelta(days=days_ahead)
    )
    if candidate <= now:
        candidate += timedelta(days=WEEKLY_UPDATE_INTERVAL_DAYS)
    return runtime.jst_iso(candidate)


def should_update_contact_ai_memo(contact: Contact) -> bool:
    return (
        contact.kind == "person"
        and contact.status == "active"
        and contact.deleted_at is None
    )


def contact_needs_initial_ai_memo(contact: Contact) -> bool:
    return contact.ai_memo is None or contact.ai_memo.strip() == ""


def should_create_archived_initial_ai_memo(
    contact: Contact,
    *,
    allow_archived_initial: bool,
) -> bool:
    return (
        allow_archived_initial
        and contact.kind == "person"
        and contact.status == "archived"
        and contact.deleted_at is None
        and contact.ai_memo is None
    )


def handle_contact_ai_memo_update(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    contact_id = payload["contact_id"]
    message_id = payload["message_id"]
    allow_archived_initial = bool(payload.get("allow_archived_initial"))
    schedule_scope = str(payload.get("schedule_scope") or "single_message")
    now = runtime.jst_iso()
    llm_provider = provider or build_contact_ai_memo_update_provider()

    with runtime.SessionLocal() as session:
        contact = session.get(Contact, contact_id)
        if contact is None or contact.deleted_at is not None:
            raise LookupError(f"Contact not found: {contact_id}")
        if not should_update_contact_ai_memo(contact) and not should_create_archived_initial_ai_memo(
            contact,
            allow_archived_initial=allow_archived_initial,
        ):
            return {
                "contact_id": contact.id,
                "message_id": message_id,
                "skipped": True,
                "reason": "not_active_person_contact",
            }

        message = session.get(GmailMessage, message_id)
        if message is None:
            raise LookupError(f"Gmail message not found: {message_id}")
        messages = (
            contact_messages_since_last_ai_memo_update(
                session,
                contact=contact,
                fallback_message=message,
            )
            if schedule_scope == "weekly_batch"
            else [message]
        )
        if not messages:
            return {
                "contact_id": contact.id,
                "message_id": message_id,
                "skipped": True,
                "reason": "no_new_contact_messages",
            }

        input_payload = {
                "contact_id": contact.id,
                "contact_display_name": contact.display_name,
                "current_ai_memo": contact.ai_memo,
                "message_id": messages[-1].id,
                "gmail_message_id": messages[-1].gmail_message_id,
                "received_at": messages[-1].received_at,
                "subject": messages[-1].subject,
                "from_address": messages[-1].from_address,
                "snippet": messages[-1].snippet,
                "body_text": messages[-1].body_text,
                "messages": [contact_ai_memo_message_payload(item) for item in messages],
        }
        provider_input_payload = with_llm_personalization(
            session, FUNCTION_TYPE, input_payload
        )
        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload=provider_input_payload,
        )
        output = provider_response.output
        ai_memo = str(output["ai_memo"])
        llm_run = LlmRun(
            id=new_id("llm_run"),
            function_type=FUNCTION_TYPE,
            provider_name=llm_provider.provider_name,
            model_name=llm_provider.model_name,
            prompt_version_id=None,
            input_hash=None,
            input_source_json=json.dumps(
                {
                    "contact_id": contact.id,
                    "message_id": messages[-1].id,
                    "gmail_message_id": messages[-1].gmail_message_id,
                    "subject": messages[-1].subject,
                    "message_count": len(messages),
                    "message_ids": [item.id for item in messages],
                    "schedule_scope": schedule_scope,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                {
                    "had_existing_ai_memo": contact.ai_memo is not None,
                    "has_body_text": any(item.body_text is not None for item in messages),
                    "has_snippet": any(item.snippet is not None for item in messages),
                    "body_text_length": sum(len(item.body_text or "") for item in messages),
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
            retry_count=0,
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
        contact.ai_memo = ai_memo
        contact.updated_at = now
        contact.version += 1
        session.commit()
        return {
            "contact_id": contact.id,
            "message_id": messages[-1].id,
            "message_count": len(messages),
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
            "skipped": False,
        }


def contact_messages_since_last_ai_memo_update(
    session,
    *,
    contact: Contact,
    fallback_message: GmailMessage,
) -> list[GmailMessage]:
    last_finished_at = None
    runs = session.scalars(
        select(LlmRun)
        .where(LlmRun.function_type == FUNCTION_TYPE)
        .order_by(LlmRun.finished_at.desc(), LlmRun.created_at.desc())
    ).all()
    for run in runs:
        try:
            input_source = json.loads(run.input_source_json or "{}")
        except json.JSONDecodeError:
            continue
        if input_source.get("contact_id") == contact.id:
            last_finished_at = run.finished_at
            break
    return contact_messages_after(session, contact, last_finished_at, fallback_message)


def contact_messages_after(
    session,
    contact: Contact,
    since: str | None,
    fallback_message: GmailMessage,
) -> list[GmailMessage]:
    from caseclosed.db.models import ContactEmailAddress

    addresses = [
        row.normalized_email_address
        for row in session.scalars(
            select(ContactEmailAddress).where(
                ContactEmailAddress.contact_id == contact.id,
                ContactEmailAddress.deleted_at.is_(None),
            )
        ).all()
    ]
    if not addresses:
        return [fallback_message]
    query = (
        select(GmailMessage)
        .where(GmailMessage.from_address.in_(addresses))
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
        .limit(MAX_BATCH_MESSAGES)
    )
    if since is not None:
        query = query.where(GmailMessage.received_at > since)
    messages = [
        message
        for message in session.scalars(query).all()
        if not message_is_sent_for_contact_memo(message)
    ]
    if fallback_message.id not in {message.id for message in messages}:
        messages.append(fallback_message)
    return sorted(messages, key=lambda item: (item.received_at, item.id))


def message_is_sent_for_contact_memo(message: GmailMessage) -> bool:
    try:
        labels = json.loads(message.gmail_labels_json or "[]")
    except json.JSONDecodeError:
        labels = []
    if not isinstance(labels, list):
        return False
    return any(str(label).upper() == "SENT" for label in labels)


def contact_ai_memo_message_payload(message: GmailMessage) -> dict[str, object]:
    return {
        "message_id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "snippet": message.snippet,
        "body_text": message.body_text,
    }
