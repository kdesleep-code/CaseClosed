from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import GmailThread
from caseclosed.db.models import Job
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailUserState
from caseclosed.db.runtime import jst_iso


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_email_address(email_address: str) -> str:
    return email_address.strip().lower()


@dataclass(frozen=True)
class MockMailInput:
    gmail_message_id: str
    gmail_thread_id: str
    from_address: str
    received_at: str
    subject: str | None = None
    from_name: str | None = None
    sender_address: str | None = None
    reply_to_address: str | None = None
    to_addresses: list[str] | None = None
    cc_addresses: list[str] | None = None
    bcc_addresses: list[str] | None = None
    message_id_header: str | None = None
    in_reply_to_header: str | None = None
    references_header: str | None = None
    list_id: str | None = None
    internal_date: str | None = None
    snippet: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    gmail_link: str | None = None
    gmail_labels: list[str] | None = None
    external_starred: bool = False


@dataclass(frozen=True)
class MailIngestionResult:
    message_id: str
    gmail_message_id: str
    pending: bool
    pending_address: str | None
    pending_reason: str | None
    queued_job_id: str | None


def ingest_mock_mail(
    session: DatabaseSession,
    mail_input: MockMailInput,
) -> MailIngestionResult:
    existing_message = session.scalar(
        select(GmailMessage).where(
            GmailMessage.gmail_message_id == mail_input.gmail_message_id
        )
    )
    if existing_message is not None:
        existing_auto_state = session.scalar(
            select(MailAutoState).where(MailAutoState.message_id == existing_message.id)
        )
        pending_email_address = (
            session.get(ContactEmailAddress, existing_auto_state.pending_from_address_id)
            if existing_auto_state is not None
            and existing_auto_state.pending_from_address_id is not None
            else None
        )
        return MailIngestionResult(
            message_id=existing_message.id,
            gmail_message_id=existing_message.gmail_message_id,
            pending=existing_auto_state is not None
            and existing_auto_state.pending_reason is not None,
            pending_address=(
                pending_email_address.normalized_email_address
                if pending_email_address is not None
                else None
            ),
            pending_reason=(
                existing_auto_state.pending_reason
                if existing_auto_state is not None
                else None
            ),
            queued_job_id=None,
        )

    now = jst_iso()
    thread = upsert_thread(session, mail_input, now)
    message = GmailMessage(
        id=new_id("mail"),
        gmail_message_id=mail_input.gmail_message_id,
        gmail_thread_id=mail_input.gmail_thread_id,
        thread_id=thread.id,
        internal_date=mail_input.internal_date,
        received_at=mail_input.received_at,
        subject=mail_input.subject,
        from_address=normalize_email_address(mail_input.from_address),
        from_name=mail_input.from_name,
        sender_address=normalize_optional_email(mail_input.sender_address),
        reply_to_address=normalize_optional_email(mail_input.reply_to_address),
        to_addresses_json=json_or_none(mail_input.to_addresses),
        cc_addresses_json=json_or_none(mail_input.cc_addresses),
        bcc_addresses_json=json_or_none(mail_input.bcc_addresses),
        message_id_header=mail_input.message_id_header,
        in_reply_to_header=mail_input.in_reply_to_header,
        references_header=mail_input.references_header,
        list_id=mail_input.list_id,
        snippet=mail_input.snippet,
        body_text=mail_input.body_text,
        body_html=mail_input.body_html,
        gmail_link=mail_input.gmail_link,
        gmail_labels_json=json_or_none(mail_input.gmail_labels),
        external_starred=1 if mail_input.external_starred else 0,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(message)
    session.add(
        MailUserState(
            id=new_id("mail_user_state"),
            message_id=message.id,
            user_importance=None,
            processed_status="unprocessed",
            processed_at=None,
            read_status="unread",
            read_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )

    sender_resolution = resolve_sender(session, mail_input, now)
    queued_job_id = None
    if sender_resolution.pending_address is None and sender_resolution.should_classify:
        queued_job_id = enqueue_importance_job(session, message, now)

    effective_importance = effective_importance_for_message(
        pending=sender_resolution.pending_address is not None,
        skipped=sender_resolution.skipped,
        external_starred=mail_input.external_starred,
    )
    session.add(
        MailAutoState(
            id=new_id("mail_auto_state"),
            message_id=message.id,
            external_importance="high" if mail_input.external_starred else None,
            suggested_importance=None,
            llm_run_id=None,
            effective_importance=effective_importance,
            pending_reason=sender_resolution.pending_reason,
            pending_from_address_id=(
                sender_resolution.pending_address.id
                if sender_resolution.pending_address is not None
                else None
            ),
            created_at=now,
            updated_at=now,
            version=1,
        )
    )
    session.commit()

    return MailIngestionResult(
        message_id=message.id,
        gmail_message_id=message.gmail_message_id,
        pending=sender_resolution.pending_address is not None,
        pending_address=(
            sender_resolution.pending_address.normalized_email_address
            if sender_resolution.pending_address is not None
            else None
        ),
        pending_reason=sender_resolution.pending_reason,
        queued_job_id=queued_job_id,
    )


def upsert_thread(
    session: DatabaseSession,
    mail_input: MockMailInput,
    now: str,
) -> GmailThread:
    thread = session.scalar(
        select(GmailThread).where(GmailThread.gmail_thread_id == mail_input.gmail_thread_id)
    )
    if thread is None:
        thread = GmailThread(
            id=new_id("gmail_thread"),
            gmail_thread_id=mail_input.gmail_thread_id,
            subject_snapshot=mail_input.subject,
            first_message_at=mail_input.received_at,
            last_message_at=mail_input.received_at,
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(thread)
        return thread

    if thread.first_message_at is None or mail_input.received_at < thread.first_message_at:
        thread.first_message_at = mail_input.received_at
    if thread.last_message_at is None or mail_input.received_at > thread.last_message_at:
        thread.last_message_at = mail_input.received_at
    if thread.subject_snapshot is None:
        thread.subject_snapshot = mail_input.subject
    thread.updated_at = now
    thread.version += 1
    return thread


@dataclass(frozen=True)
class SenderResolution:
    pending_address: ContactEmailAddress | None
    pending_reason: str | None
    skipped: bool
    should_classify: bool


def resolve_sender(
    session: DatabaseSession,
    mail_input: MockMailInput,
    now: str,
) -> SenderResolution:
    from_email_address = upsert_observed_email_address(
        session,
        mail_input.from_address,
        now,
    )
    from_contact = (
        session.get(Contact, from_email_address.contact_id)
        if from_email_address.contact_id is not None
        else None
    )

    if unresolved_email_address(from_email_address, from_contact):
        return SenderResolution(
            pending_address=from_email_address,
            pending_reason="unresolved_from_contact",
            skipped=False,
            should_classify=False,
        )

    if from_contact is not None and from_contact.kind == "mailing_list":
        if from_contact.sender_resolution_mode == "reply_to":
            if mail_input.reply_to_address is None or mail_input.reply_to_address.strip() == "":
                return SenderResolution(
                    pending_address=None,
                    pending_reason="mailing_list_reply_to_missing",
                    skipped=False,
                    should_classify=False,
                )
            reply_to_email_address = upsert_observed_email_address(
                session,
                mail_input.reply_to_address,
                now,
            )
            reply_to_contact = (
                session.get(Contact, reply_to_email_address.contact_id)
                if reply_to_email_address.contact_id is not None
                else None
            )
            if unresolved_email_address(reply_to_email_address, reply_to_contact):
                return SenderResolution(
                    pending_address=reply_to_email_address,
                    pending_reason="unresolved_reply_to_contact",
                    skipped=False,
                    should_classify=False,
                )
            return SenderResolution(
                pending_address=None,
                pending_reason=None,
                skipped=reply_to_contact is not None and reply_to_contact.status == "skipped",
                should_classify=reply_to_contact is None
                or reply_to_contact.status != "skipped",
            )

    skipped = from_contact is not None and from_contact.status == "skipped"
    return SenderResolution(
        pending_address=None,
        pending_reason=None,
        skipped=skipped,
        should_classify=not skipped,
    )


def upsert_observed_email_address(
    session: DatabaseSession,
    email_address: str,
    now: str,
) -> ContactEmailAddress:
    normalized_email_address = normalize_email_address(email_address)
    contact_email_address = session.scalar(
        select(ContactEmailAddress).where(
            ContactEmailAddress.normalized_email_address == normalized_email_address
        )
    )
    if contact_email_address is None:
        contact_email_address = ContactEmailAddress(
            id=new_id("email"),
            contact_id=None,
            email_address=email_address.strip(),
            normalized_email_address=normalized_email_address,
            resolution_status="unresolved",
            status="active",
            has_inbound_message_history=1,
            is_primary=0,
            source="gmail",
            first_seen_at=now,
            last_seen_at=now,
            deactivated_at=None,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(contact_email_address)
        return contact_email_address

    if contact_email_address.first_seen_at is None:
        contact_email_address.first_seen_at = now
    contact_email_address.last_seen_at = now
    contact_email_address.has_inbound_message_history = 1
    contact_email_address.updated_at = now
    contact_email_address.version += 1
    return contact_email_address


def unresolved_email_address(
    email_address: ContactEmailAddress,
    contact: Contact | None,
) -> bool:
    return (
        email_address.contact_id is None
        or email_address.resolution_status != "linked"
        or contact is None
        or contact.deleted_at is not None
    )


def enqueue_importance_job(
    session: DatabaseSession,
    message: GmailMessage,
    now: str,
) -> str:
    job_id = new_id("job")
    session.add(
        Job(
            id=job_id,
            job_type="mail_importance_classification",
            priority=100,
            status="pending",
            payload_json=json.dumps(
                {
                    "message_id": message.id,
                    "gmail_message_id": message.gmail_message_id,
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


def effective_importance_for_message(
    *,
    pending: bool,
    skipped: bool,
    external_starred: bool,
) -> str:
    if pending:
        return "pending"
    if skipped:
        return "skip"
    if external_starred:
        return "high"
    return "unclassified"


def normalize_optional_email(email_address: str | None) -> str | None:
    if email_address is None or email_address.strip() == "":
        return None
    return normalize_email_address(email_address)


def json_or_none(values: list[str] | None) -> str | None:
    if values is None:
        return None
    return json.dumps(values, ensure_ascii=True, sort_keys=True)
