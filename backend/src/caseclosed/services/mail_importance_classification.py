from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db.models import AppSetting
from caseclosed.db import runtime
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import GmailThread
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailUserState
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import llm_applied_instruction_rule_ids
from caseclosed.services.llm_provider import with_llm_personalization
from caseclosed.services.llm_provider import build_mail_importance_provider
from caseclosed.services.mail_summary import SUMMARY_TARGET_IMPORTANCE
from caseclosed.services.mail_summary import enqueue_mail_summary_job
from caseclosed.services.mail_state_transitions import mark_skip_mail_done

FUNCTION_TYPE = "mail_importance_classification"
USER_PROFILE_KEY = "user_profile"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def profile_text_lines(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [line.strip() for line in value.splitlines() if line.strip()]


def read_mail_importance_profile_context(session) -> dict[str, object]:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == USER_PROFILE_KEY))
    if setting is None:
        return {}
    try:
        data = json.loads(setting.value_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    context: dict[str, object] = {}
    for key in (
        "display_name",
        "affiliation",
        "academic_title",
        "lab_or_group",
        "research_fields",
        "priority_keywords",
        "low_priority_keywords",
        "important_senders_or_domains",
        "expected_response_policy",
        "unavailable_times",
        "llm_self_description",
        "mail_importance_notes",
    ):
        value = data.get(key)
        if isinstance(value, str) and value.strip() != "":
            context[key] = value.strip()
    for key in (
        "teaching_responsibilities",
        "committee_roles",
        "administrative_roles",
        "important_projects",
    ):
        lines = profile_text_lines(data.get(key))
        if lines:
            context[key] = lines
    aliases = data.get("email_aliases")
    if isinstance(aliases, list):
        context["email_aliases"] = [
            value for value in aliases if isinstance(value, str) and value.strip() != ""
        ]
    primary_email = data.get("primary_email")
    if isinstance(primary_email, str) and primary_email.strip() != "":
        context["primary_email"] = primary_email.strip()
    return context


def mail_thread_has_case_link(session, thread_id: str) -> bool:
    return session.scalar(
        select(CaseMailLink.id)
        .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
        .where(GmailMessage.thread_id == thread_id)
        .limit(1)
    ) is not None


def handle_mail_importance_classification(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    message_id = payload["message_id"]
    llm_instruction = payload.get("llm_instruction")
    now = runtime.jst_iso()
    llm_provider = provider or build_mail_importance_provider()

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
        if bool(auto_state.llm_blocked):
            auto_state.effective_importance = "pinned"
            auto_state.updated_at = now
            auto_state.version += 1
            session.commit()
            return {
                "message_id": message.id,
                "skipped": True,
                "reason": "llm_blocked",
                "effective_importance": "pinned",
            }

        thread = session.get(GmailThread, message.thread_id)
        if thread is not None and thread.future_importance_rule == "low":
            auto_state.effective_importance = (
                "high" if auto_state.external_importance == "high" else "low"
            )
            auto_state.updated_at = now
            auto_state.version += 1
            session.commit()
            return {
                "message_id": message.id,
                "skipped": True,
                "reason": "thread_future_importance_rule",
                "effective_importance": auto_state.effective_importance,
            }

        profile_context = read_mail_importance_profile_context(session)
        input_payload = {
                "message_id": message.id,
                "gmail_message_id": message.gmail_message_id,
                "subject": message.subject,
                "snippet": message.snippet,
                "body_text": message.body_text,
                "additional_instruction": llm_instruction,
                "profile_context": profile_context,
        }
        provider_input_payload = with_llm_personalization(
            session, FUNCTION_TYPE, input_payload
        )
        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload=provider_input_payload,
        )
        suggested_importance = str(provider_response.output["importance"])
        input_source = {
            "message_id": message.id,
            "gmail_message_id": message.gmail_message_id,
            "subject": message.subject,
        }
        if llm_instruction is not None:
            input_source["has_contact_instruction"] = True
        if profile_context:
            input_source["has_profile_context"] = True

        input_diagnostic = {
            "has_body_text": message.body_text is not None,
            "has_snippet": message.snippet is not None,
            "has_profile_context": bool(profile_context),
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
            applied_instruction_rule_ids_json=json.dumps(
                llm_applied_instruction_rule_ids(provider_input_payload),
                ensure_ascii=True,
            ),
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
            case_linked=mail_thread_has_case_link(session, message.thread_id),
        )
        user_state = session.scalar(
            select(MailUserState).where(MailUserState.message_id == message.id)
        )
        if user_state is not None and mark_skip_mail_done(
            user_state,
            effective_importance=auto_state.effective_importance,
            now=now,
        ):
            user_state.updated_at = now
            user_state.version += 1
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
    case_linked: bool = False,
) -> str:
    if external_importance == "high":
        return "high"
    if case_linked and suggested_importance not in {"pinned", "high", "middle"}:
        return "middle"
    return suggested_importance
