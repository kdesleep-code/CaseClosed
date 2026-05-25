from __future__ import annotations

import json

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailAutoState
from caseclosed.services.mail_ingestion import apply_contact_mail_importance_rule


def handle_contact_resolution_followup(job: Job) -> dict[str, object]:
    payload = json.loads(job.payload_json)
    email_address_id = payload["email_address_id"]
    now = runtime.jst_iso()

    with runtime.SessionLocal() as session:
        email_address = session.get(ContactEmailAddress, email_address_id)
        if email_address is None:
            raise LookupError(f"Contact email address not found: {email_address_id}")
        if email_address.contact_id is None:
            raise LookupError(
                f"Contact email address is not linked to a contact: {email_address_id}"
            )
        contact = session.get(Contact, email_address.contact_id)
        if contact is None or contact.deleted_at is not None:
            raise LookupError(f"Contact not found: {email_address.contact_id}")
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

            result = apply_contact_mail_importance_rule(
                session,
                message=message,
                auto_state=auto_state,
                contact=contact,
                now=now,
            )
            if result.queued_job_id is not None:
                queued_job_count += 1

        session.commit()
        return {
            "released_message_count": len(pending_states),
            "queued_job_count": queued_job_count,
            "contact_id": contact.id,
        }
