from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import GmailThread
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailThreadSummary
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import build_mail_thread_summary_provider
from caseclosed.services.mail_ingestion import message_is_sent

FUNCTION_TYPE = "mail_thread_summary"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def enqueue_mail_thread_summary_job(
    session,
    *,
    thread_id: str,
    gmail_thread_id: str,
    now: str,
    reason: str,
) -> str:
    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type=FUNCTION_TYPE,
            priority=130,
            status="pending",
            payload_json=json.dumps(
                {
                    "thread_id": thread_id,
                    "gmail_thread_id": gmail_thread_id,
                    "reason": reason,
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


def handle_mail_thread_summary(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    thread_id = payload["thread_id"]
    now = runtime.jst_iso()
    llm_provider = provider or build_mail_thread_summary_provider()

    with runtime.SessionLocal() as session:
        thread = session.get(GmailThread, thread_id)
        if thread is None:
            raise LookupError(f"Gmail thread not found: {thread_id}")

        rows = session.execute(
            select(GmailMessage, MailAutoState)
            .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
            .where(GmailMessage.thread_id == thread.id)
            .order_by(GmailMessage.received_at, GmailMessage.id)
        ).all()
        summary_messages = [
            (message, auto_state)
            for message, auto_state in rows
            if should_include_message(message, auto_state)
        ]
        if not summary_messages:
            return {
                "thread_id": thread.id,
                "skipped": True,
                "reason": "no_summary_target_messages",
            }

        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload={
                "thread_id": thread.id,
                "gmail_thread_id": thread.gmail_thread_id,
                "subject": thread.subject_snapshot,
                "messages": [
                    {
                        "message_id": message.id,
                        "gmail_message_id": message.gmail_message_id,
                        "received_at": message.received_at,
                        "subject": message.subject,
                        "from_address": message.from_address,
                        "to_addresses_json": message.to_addresses_json,
                        "cc_addresses_json": message.cc_addresses_json,
                        "snippet": message.snippet,
                        "body_text": message.body_text,
                        "importance": auto_state.effective_importance,
                    }
                    for message, auto_state in summary_messages
                ],
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
                    "thread_id": thread.id,
                    "gmail_thread_id": thread.gmail_thread_id,
                    "subject": thread.subject_snapshot,
                    "message_count": len(summary_messages),
                    "message_ids": [message.id for message, _ in summary_messages],
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                {
                    "messages_with_body_text": sum(
                        1 for message, _ in summary_messages if message.body_text
                    ),
                    "messages_with_snippet": sum(
                        1 for message, _ in summary_messages if message.snippet
                    ),
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
            select(MailThreadSummary).where(MailThreadSummary.thread_id == thread.id)
        )
        if summary is None:
            summary = MailThreadSummary(
                id=new_id("mail_thread_summary"),
                thread_id=thread.id,
                summary_text=str(output["summary"]),
                action_required=1 if output.get("needs_action") is True else 0,
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
            "thread_id": thread.id,
            "summary_id": summary.id,
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
            "message_count": len(summary_messages),
            "skipped": False,
        }


def should_include_message(message: GmailMessage, auto_state: MailAutoState) -> bool:
    return (
        not message_is_sent(message)
        and auto_state.pending_reason is None
        and not bool(auto_state.llm_blocked)
    )


def string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
