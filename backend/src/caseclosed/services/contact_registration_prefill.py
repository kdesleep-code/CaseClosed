from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactRegistrationSuggestion
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.services.llm_provider import LlmProvider
from caseclosed.services.llm_provider import MockContactPrefillProvider

FUNCTION_TYPE = "contact_registration_prefill"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def handle_contact_registration_prefill(
    job: Job,
    provider: LlmProvider | None = None,
) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    email_address_id = payload["email_address_id"]
    email_address_text = payload["email_address"]
    source_message_id = payload.get("message_id")
    now = runtime.jst_iso()
    llm_provider = provider or MockContactPrefillProvider()

    with runtime.SessionLocal() as session:
        email_address = session.get(ContactEmailAddress, email_address_id)
        if email_address is None:
            raise LookupError(f"Contact email address not found: {email_address_id}")
        if email_address.resolution_status != "unresolved":
            raise ValueError(
                f"Contact email address is already resolved: {email_address_id}"
            )

        existing_suggestion = session.scalar(
            select(ContactRegistrationSuggestion)
            .where(
                ContactRegistrationSuggestion.email_address_id == email_address.id,
                ContactRegistrationSuggestion.status == "suggested",
            )
            .order_by(ContactRegistrationSuggestion.created_at.desc())
        )
        if existing_suggestion is not None:
            return {
                "suggestion_id": existing_suggestion.id,
                "reused": True,
                "provider": "existing",
                "llm_run_id": existing_suggestion.llm_run_id,
            }

        provider_response = llm_provider.complete_json(
            function_type=FUNCTION_TYPE,
            input_payload={
                "email_address_id": email_address.id,
                "email_address": email_address_text,
                "message_id": source_message_id,
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
                    "email_address_id": email_address.id,
                    "email_address": email_address_text,
                    "message_id": source_message_id,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            input_diagnostic_json=json.dumps(
                {
                    "has_source_message": source_message_id is not None,
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

        suggestion = ContactRegistrationSuggestion(
            id=new_id("contact_suggestion"),
            email_address_id=email_address.id,
            source_message_id=source_message_id,
            suggested_display_name=str(output.get("suggested_display_name") or ""),
            suggested_organization=None,
            suggested_role=None,
            suggested_tags_json=json.dumps(
                output.get("suggested_tags") or [],
                ensure_ascii=True,
            ),
            suggested_memo=None,
            suggested_skip_reason=None,
            confidence=float(output.get("confidence") or 0),
            llm_run_id=llm_run.id,
            status="suggested",
            created_at=now,
            updated_at=now,
        )
        session.add(suggestion)
        session.commit()
        return {
            "suggestion_id": suggestion.id,
            "reused": False,
            "provider": llm_provider.provider_name,
            "llm_run_id": llm_run.id,
        }
