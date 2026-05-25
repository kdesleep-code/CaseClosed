from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSummary
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import MockMailSummaryProvider
from caseclosed.services.mail_ingestion import message_is_sent

FUNCTION_TYPE = "mail_summary"
SUMMARY_TARGET_IMPORTANCE = {"high", "middle"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def enqueue_mail_summary_job(
    session,
    message: GmailMessage,
    now: str,
) -> str:
    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type="mail_summary",
            priority=120,
            status="pending",
            payload_json=json.dumps(
                {
                    "message_id": message.id,
                    "gmail_message_id": message.gmail_message_id,
                    "thread_id": message.thread_id,
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


def handle_mail_summary(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    message_id = payload["message_id"]
    now = runtime.jst_iso()
    llm_provider = provider or MockMailSummaryProvider()

    with runtime.SessionLocal() as session:
        message = session.get(GmailMessage, message_id)
        if message is None:
            raise LookupError(f"Gmail message not found: {message_id}")
        auto_state = session.scalar(
            select(MailAutoState).where(MailAutoState.message_id == message.id)
        )
        if auto_state is None:
            raise LookupError(f"Mail auto state not found: {message.id}")
        if not should_summarize(message, auto_state):
            return {
                "message_id": message.id,
                "skipped": True,
                "reason": "not_summary_target",
            }

        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload={
                "message_id": message.id,
                "gmail_message_id": message.gmail_message_id,
                "thread_id": message.thread_id,
                "subject": message.subject,
                "from_address": message.from_address,
                "to_addresses_json": message.to_addresses_json,
                "cc_addresses_json": message.cc_addresses_json,
                "snippet": message.snippet,
                "body_text": message.body_text,
                "importance": auto_state.effective_importance,
            },
        )
        output = provider_response.output
        llm_run = LlmRun(
            id=new_id("llm_run"),
            function_type=FUNCTION_TYPE,
            provider_name=llm_provider.provider_name,
            model_name=llm_provider.model_name,
            prompt_version_id=None,
            input_hash=None,
            input_source_json=json.dumps(
                {
                    "message_id": message.id,
                    "gmail_message_id": message.gmail_message_id,
                    "thread_id": message.thread_id,
                    "subject": message.subject,
                    "importance": auto_state.effective_importance,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                {
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
        summary = session.scalar(
            select(MailSummary).where(MailSummary.message_id == message.id)
        )
        if summary is None:
            summary = MailSummary(
                id=new_id("mail_summary"),
                message_id=message.id,
                summary_text=str(output["summary"]),
                action_required=1 if output.get("needs_action") is True else 0,
                deadline_text=deadline_text(output),
                next_action=string_or_none(output.get("next_action")),
                key_points_json=json.dumps(
                    output.get("key_points") or [],
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                translation_text=string_or_none(output.get("translation")),
                language="ja",
                llm_run_id=llm_run.id,
                created_at=now,
                updated_at=now,
                version=1,
            )
            session.add(summary)
        else:
            summary.summary_text = str(output["summary"])
            summary.action_required = 1 if output.get("needs_action") is True else 0
            summary.deadline_text = deadline_text(output)
            summary.next_action = string_or_none(output.get("next_action"))
            summary.key_points_json = json.dumps(
                output.get("key_points") or [],
                ensure_ascii=True,
                sort_keys=True,
            )
            summary.translation_text = string_or_none(output.get("translation"))
            summary.llm_run_id = llm_run.id
            summary.updated_at = now
            summary.version += 1
        session.commit()
        return {
            "message_id": message.id,
            "summary_id": summary.id,
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
            "skipped": False,
        }


def should_summarize(message: GmailMessage, auto_state: MailAutoState) -> bool:
    return (
        not message_is_sent(message)
        and auto_state.pending_reason is None
        and auto_state.effective_importance in SUMMARY_TARGET_IMPORTANCE
    )


def string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def deadline_text(output: dict[str, object]) -> str | None:
    deadline = output.get("deadline")
    if not isinstance(deadline, dict):
        return None
    return string_or_none(deadline.get("date_text") or deadline.get("normalized_date"))
