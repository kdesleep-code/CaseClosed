from __future__ import annotations

import json
import re
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
from caseclosed.services.llm_provider import LlmProviderResponse
from caseclosed.services.llm_provider import build_mail_thread_summary_provider
from caseclosed.services.mail_ingestion import message_is_sent

FUNCTION_TYPE = "mail_thread_summary"
SUMMARY_TARGET_IMPORTANCE = {"high", "middle"}
THREAD_SUMMARY_INPUT_CHAR_LIMIT = 36000
THREAD_SUMMARY_CHUNK_CHAR_LIMIT = 24000

QUOTED_REPLY_INTRO_PATTERNS = [
    re.compile(
        r"\d{4}\s*\u5e74\s*\d{1,2}\s*\u6708\s*\d{1,2}\s*\u65e5"
        r"(?:\([^)]*\))?\s+\d{1,2}:\d{2}.*<[^>\n]+>.*:",
        re.IGNORECASE,
    ),
    re.compile(
        r"\d{4}[/-]\d{1,2}[/-]\d{1,2}.*\d{1,2}:\d{2}.*<[^>\n]+>.*:",
        re.IGNORECASE,
    ),
    re.compile(
        r"<[^>\n]+>.*\d{4}\s*\u5e74\s*\d{1,2}\s*\u6708\s*\d{1,2}"
        r"\s*\u65e5.*(?:[:\uff1a]|\u5199\u9053)",
        re.IGNORECASE,
    ),
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^From:\s+.+", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^>"),
]


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

        message_payloads = [
            thread_summary_message_payload(message, auto_state)
            for message, auto_state in summary_messages
        ]
        provider_response, chunk_count = complete_thread_summary(
            llm_provider,
            thread_id=thread.id,
            gmail_thread_id=thread.gmail_thread_id,
            subject=thread.subject_snapshot,
            messages=message_payloads,
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
                    "chunk_count": chunk_count,
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
                    "input_body_characters_after_quote_trim": sum(
                        len(str(message_payload.get("body_text") or ""))
                        for message_payload in message_payloads
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
            "chunk_count": chunk_count,
            "skipped": False,
        }


def should_include_message(message: GmailMessage, auto_state: MailAutoState) -> bool:
    return (
        not message_is_sent(message)
        and auto_state.pending_reason is None
        and not bool(auto_state.llm_blocked)
        and auto_state.effective_importance in SUMMARY_TARGET_IMPORTANCE
    )


def thread_summary_message_payload(
    message: GmailMessage,
    auto_state: MailAutoState,
) -> dict[str, object]:
    return {
        "message_id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "to_addresses_json": message.to_addresses_json,
        "cc_addresses_json": message.cc_addresses_json,
        "snippet": message.snippet,
        "body_text": strip_quoted_reply_sections(message.body_text or ""),
        "importance": auto_state.effective_importance,
    }


def strip_quoted_reply_sections(body_text: str) -> str:
    lines = body_text.splitlines()
    kept_lines: list[str] = []
    for line in lines:
        if looks_like_quoted_reply_intro(line):
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def looks_like_quoted_reply_intro(line: str) -> bool:
    stripped = line.strip()
    if stripped == "":
        return False
    return any(pattern.search(stripped) for pattern in QUOTED_REPLY_INTRO_PATTERNS)


def complete_thread_summary(
    provider: LlmProvider,
    *,
    thread_id: str,
    gmail_thread_id: str,
    subject: str | None,
    messages: list[dict[str, object]],
) -> tuple[LlmProviderResponse, int]:
    base_payload = thread_summary_payload(
        thread_id=thread_id,
        gmail_thread_id=gmail_thread_id,
        subject=subject,
        messages=messages,
    )
    if thread_summary_payload_size(base_payload) <= THREAD_SUMMARY_INPUT_CHAR_LIMIT:
        return (
            provider.complete_json(
                function_type=FUNCTION_TYPE,
                input_payload=base_payload,
            ),
            1,
        )

    partial_summaries: list[dict[str, object]] = []
    partial_responses: list[LlmProviderResponse] = []
    chunks = chunk_thread_messages(messages)
    for index, chunk in enumerate(chunks, start=1):
        partial_payload = thread_summary_payload(
            thread_id=thread_id,
            gmail_thread_id=gmail_thread_id,
            subject=subject,
            messages=chunk,
            summary_scope="partial",
            chunk_index=index,
            chunk_count=len(chunks),
        )
        partial_response = provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload=partial_payload,
        )
        partial_responses.append(partial_response)
        partial_summaries.append(
            {
                "chunk_index": index,
                "summary": partial_response.output.get("summary"),
                "next_action": partial_response.output.get("next_action"),
                "key_points": partial_response.output.get("key_points") or [],
                "needs_action": partial_response.output.get("needs_action"),
            }
        )

    final_payload = thread_summary_payload(
        thread_id=thread_id,
        gmail_thread_id=gmail_thread_id,
        subject=subject,
        messages=[],
        summary_scope="final_from_partial_summaries",
        partial_summaries=partial_summaries,
    )
    final_response = provider.complete_json(
        function_type=FUNCTION_TYPE,
        input_payload=final_payload,
    )
    return combine_thread_summary_responses(final_response, partial_responses), len(chunks)


def thread_summary_payload(
    *,
    thread_id: str,
    gmail_thread_id: str,
    subject: str | None,
    messages: list[dict[str, object]],
    summary_scope: str = "full",
    chunk_index: int | None = None,
    chunk_count: int | None = None,
    partial_summaries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "thread_id": thread_id,
        "gmail_thread_id": gmail_thread_id,
        "subject": subject,
        "summary_scope": summary_scope,
        "messages": messages,
    }
    if chunk_index is not None:
        payload["chunk_index"] = chunk_index
    if chunk_count is not None:
        payload["chunk_count"] = chunk_count
    if partial_summaries is not None:
        payload["partial_summaries"] = partial_summaries
    return payload


def thread_summary_payload_size(payload: dict[str, object]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def chunk_thread_messages(messages: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    chunks: list[list[dict[str, object]]] = []
    current_chunk: list[dict[str, object]] = []
    for message in messages:
        trial_chunk = [*current_chunk, message]
        if (
            current_chunk
            and thread_summary_payload_size({"messages": trial_chunk})
            > THREAD_SUMMARY_CHUNK_CHAR_LIMIT
        ):
            chunks.append(current_chunk)
            current_chunk = [message]
        else:
            current_chunk = trial_chunk
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def combine_thread_summary_responses(
    final_response: LlmProviderResponse,
    partial_responses: list[LlmProviderResponse],
) -> LlmProviderResponse:
    responses = [*partial_responses, final_response]
    return LlmProviderResponse(
        output=final_response.output,
        output_preview=final_response.output_preview,
        prompt_tokens=sum_optional_int(response.prompt_tokens for response in responses),
        completion_tokens=sum_optional_int(
            response.completion_tokens for response in responses
        ),
        total_tokens=sum_optional_int(response.total_tokens for response in responses),
        estimated_cost=sum_optional_float(
            response.estimated_cost for response in responses
        ),
    )


def sum_optional_int(values) -> int | None:
    total = 0
    found = False
    for value in values:
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def sum_optional_float(values) -> float | None:
    total = 0.0
    found = False
    for value in values:
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
