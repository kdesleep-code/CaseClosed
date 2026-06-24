from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import Case
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import CaseStakeholder
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import GmailMessage
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_email_address

MAIL_SENDER_STAKEHOLDER_ROLE = "mail_sender"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def sender_contact_for_message(
    session: DatabaseSession,
    message: GmailMessage,
) -> Contact | None:
    normalized_sender = normalize_email_address(message.from_address)
    if normalized_sender == "":
        return None
    return session.scalar(
        select(Contact)
        .join(ContactEmailAddress, ContactEmailAddress.contact_id == Contact.id)
        .where(ContactEmailAddress.normalized_email_address == normalized_sender)
        .where(ContactEmailAddress.resolution_status == "linked")
        .where(ContactEmailAddress.contact_id.is_not(None))
        .where(ContactEmailAddress.deleted_at.is_(None))
        .where(Contact.deleted_at.is_(None))
        .order_by(ContactEmailAddress.status.asc(), ContactEmailAddress.is_primary.desc())
        .limit(1)
    )


def ensure_case_stakeholders_for_mail_senders(
    session: DatabaseSession,
    case: Case,
    messages: Iterable[GmailMessage],
    *,
    now: str | None = None,
) -> int:
    existing_contact_ids = set(
        session.scalars(
            select(CaseStakeholder.contact_id).where(CaseStakeholder.case_id == case.id)
        ).all()
    )
    next_sort_order = (
        session.scalar(
            select(func.max(CaseStakeholder.sort_order)).where(
                CaseStakeholder.case_id == case.id,
            )
        )
        or 0
    ) + 1
    created_at = now or jst_iso()
    added_count = 0
    for message in messages:
        contact = sender_contact_for_message(session, message)
        if contact is None or contact.id in existing_contact_ids:
            continue
        session.add(
            CaseStakeholder(
                id=new_id("case_stakeholder"),
                case_id=case.id,
                contact_id=contact.id,
                role=MAIL_SENDER_STAKEHOLDER_ROLE,
                sort_order=next_sort_order,
                created_at=created_at,
                updated_at=created_at,
                version=1,
            )
        )
        existing_contact_ids.add(contact.id)
        next_sort_order += 1
        added_count += 1
    return added_count


def case_linked_mail_messages(
    session: DatabaseSession,
    case_id: str,
) -> list[GmailMessage]:
    return session.scalars(
        select(GmailMessage)
        .join(CaseMailLink, CaseMailLink.message_id == GmailMessage.id)
        .where(CaseMailLink.case_id == case_id)
        .order_by(GmailMessage.received_at.asc(), GmailMessage.id.asc())
    ).all()


def sync_case_stakeholders_from_linked_mail_senders(
    session: DatabaseSession,
    case: Case,
    *,
    now: str | None = None,
) -> int:
    synced_at = now or jst_iso()
    added_count = ensure_case_stakeholders_for_mail_senders(
        session,
        case,
        case_linked_mail_messages(session, case.id),
        now=synced_at,
    )
    if added_count > 0:
        case.updated_at = synced_at
        case.version += 1
    return added_count


def sync_all_case_stakeholders_from_linked_mail_senders(
    session: DatabaseSession,
    *,
    now: str | None = None,
) -> int:
    cases = session.scalars(select(Case).order_by(Case.created_at.asc(), Case.id.asc())).all()
    return sum(
        sync_case_stakeholders_from_linked_mail_senders(session, case, now=now)
        for case in cases
    )
