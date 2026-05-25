from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import MockMailImportanceProvider
from caseclosed.services.mail_summary import SUMMARY_TARGET_IMPORTANCE
from caseclosed.services.mail_summary import enqueue_mail_summary_job

FUNCTION_TYPE = "mail_importance_classification"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def handle_mail_importance_classification(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    message_id = payload["message_id"]
    llm_instruction = payload.get("llm_instruction")
    now = runtime.jst_iso()
    llm_provider = provider or MockMailImportanceProvider()

    with runtime.SessionLocal() as session:
        message = session.get(GmailMessage, message_id)
        if message is None:
            raise LookupError(f"Gmail message not found: {message_id}")
        auto_state = session.scalar(
            select(MailAutoState).where(MailAutoState.message_id == message.id)
        )
        if auto_state is None:
            raise LookupError(f"Mail auto state not found: {message.id}")
        if auto_state.pending_reason is not None:
            raise ValueError(f"Mail is still pending: {message.id}")

        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload={
                "message_id": message.id,
                "gmail_message_id": message.gmail_message_id,
                "subject": message.subject,
                "snippet": message.snippet,
                "body_text": message.body_text,
                "additional_instruction": llm_instruction,
            },
        )
        suggested_importance = str(provider_response.output["importance"])
        input_source = {
            "message_id": message.id,
            "gmail_message_id": message.gmail_message_id,
            "subject": message.subject,
        }
        if llm_instruction is not None:
            input_source["has_contact_instruction"] = True

        input_diagnostic = {
            "has_body_text": message.body_text is not None,
            "has_snippet": message.snippet is not None,
        }
        if llm_instruction is not None:
            input_diagnostic["contact_instruction"] = llm_instruction

        llm_run = LlmRun(
            id=new_id("llm_run"),
            function_type=FUNCTION_TYPE,
            provider_name=llm_provider.provider_name,
            model_name=llm_provider.model_name,
            prompt_version_id=None,
            input_hash=None,
            input_source_json=json.dumps(
                input_source,
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                input_diagnostic,
                ensure_ascii=True,
                sort_keys=True,
            ),
            applied_instruction_rule_ids_json=json.dumps([], ensure_ascii=True),
            output_json=json.dumps(
                provider_response.output,
                ensure_ascii=True,
                sort_keys=True,
            ),
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
        auto_state.suggested_importance = suggested_importance
        auto_state.llm_run_id = llm_run.id
        auto_state.effective_importance = effective_importance(
            external_importance=auto_state.external_importance,
            suggested_importance=suggested_importance,
        )
        auto_state.updated_at = now
        auto_state.version += 1
        queued_summary_job_id = None
        if auto_state.effective_importance in SUMMARY_TARGET_IMPORTANCE:
            queued_summary_job_id = enqueue_mail_summary_job(session, message, now)
        session.commit()
        return {
            "message_id": message.id,
            "suggested_importance": suggested_importance,
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
            "queued_summary_job_id": queued_summary_job_id,
        }


def effective_importance(
    *,
    external_importance: str | None,
    suggested_importance: str,
) -> str:
    if external_importance == "high":
        return "high"
    return suggested_importance
