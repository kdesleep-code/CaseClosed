from __future__ import annotations

import json

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailAutoState
from caseclosed.services.mail_ingestion import enqueue_importance_job


def handle_contact_resolution_followup(job: Job) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    contact_id = payload["contact_id"]
    email_address_id = payload["email_address_id"]
    now = runtime.jst_iso()

    with runtime.SessionLocal() as session:
        contact = session.get(Contact, contact_id)
        if contact is None or contact.deleted_at is not None:
            raise LookupError(f"Contact not found: {contact_id}")
        email_address = session.get(ContactEmailAddress, email_address_id)
        if email_address is None or email_address.contact_id != contact.id:
            raise LookupError(f"Contact email address not found: {email_address_id}")
        if email_address.resolution_status != "linked":
            raise ValueError(f"Contact email address is not linked: {email_address_id}")

        pending_states = session.scalars(
            select(MailAutoState).where(
                MailAutoState.pending_from_address_id == email_address.id
            )
        ).all()
        queued_job_count = 0
        for auto_state in pending_states:
            message = session.get(GmailMessage, auto_state.message_id)
            if message is None:
                continue

            auto_state.pending_reason = None
            auto_state.pending_from_address_id = None
            auto_state.updated_at = now
            auto_state.version += 1
            if contact.status == "skipped":
                auto_state.effective_importance = "skip"
                continue

            auto_state.effective_importance = (
                "high" if auto_state.external_importance == "high" else "unclassified"
            )
            enqueue_importance_job(session, message, now)
            queued_job_count += 1

        session.commit()
        return {
            "released_message_count": len(pending_states),
            "queued_job_count": queued_job_count,
            "contact_id": contact.id,
        }
