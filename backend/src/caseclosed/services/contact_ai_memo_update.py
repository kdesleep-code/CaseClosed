from __future__ import annotations

import json
from uuid import uuid4

from caseclosed.db import runtime
from caseclosed.db.models import Contact
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.services.llm_provider import FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import build_contact_ai_memo_update_provider

FUNCTION_TYPE = FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE


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


def should_update_contact_ai_memo(contact: Contact) -> bool:
    return (
        contact.kind == "person"
        and contact.status == "active"
        and contact.deleted_at is None
    )


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

        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload={
                "contact_id": contact.id,
                "contact_display_name": contact.display_name,
                "current_ai_memo": contact.ai_memo,
                "message_id": message.id,
                "gmail_message_id": message.gmail_message_id,
                "received_at": message.received_at,
                "subject": message.subject,
                "from_address": message.from_address,
                "snippet": message.snippet,
                "body_text": message.body_text,
            },
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
                    "message_id": message.id,
                    "gmail_message_id": message.gmail_message_id,
                    "subject": message.subject,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                {
                    "had_existing_ai_memo": contact.ai_memo is not None,
                    "has_body_text": message.body_text is not None,
                    "has_snippet": message.snippet is not None,
                    "body_text_length": len(message.body_text or ""),
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
            "message_id": message.id,
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
            "skipped": False,
        }
