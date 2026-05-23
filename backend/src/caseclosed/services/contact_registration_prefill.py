from __future__ import annotations

import json
import re
from uuid import uuid4

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactRegistrationSuggestion
from caseclosed.db.models import Job


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def display_name_from_email(email_address: str) -> str:
    local_part = email_address.split("@", maxsplit=1)[0]
    words = [word for word in re.split(r"[._+\-]+", local_part) if word]
    if not words:
        return email_address
    return " ".join(word.capitalize() for word in words)


def suggested_tags_for_email(email_address: str) -> list[str]:
    local_part, _, domain = email_address.partition("@")
    low_value = f"{local_part} {domain}".lower()
    if any(token in low_value for token in ["no-reply", "noreply", "notification"]):
        return ["system-sender"]
    if any(token in low_value for token in ["list", "newsletter", "announce"]):
        return ["broadcast"]
    return ["unknown-domain"]


def handle_contact_registration_prefill(job: Job) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    email_address_id = payload["email_address_id"]
    email_address_text = payload["email_address"]
    source_message_id = payload.get("message_id")
    now = runtime.jst_iso()

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
            return {"suggestion_id": existing_suggestion.id, "reused": True}

        suggestion = ContactRegistrationSuggestion(
            id=new_id("contact_suggestion"),
            email_address_id=email_address.id,
            source_message_id=source_message_id,
            suggested_display_name=display_name_from_email(email_address_text),
            suggested_organization=None,
            suggested_role=None,
            suggested_tags_json=json.dumps(
                suggested_tags_for_email(email_address_text),
                ensure_ascii=True,
            ),
            suggested_memo=None,
            suggested_skip_reason=None,
            confidence=0.5,
            llm_run_id=None,
            status="suggested",
            created_at=now,
            updated_at=now,
        )
        session.add(suggestion)
        session.commit()
        return {"suggestion_id": suggestion.id, "reused": False}
