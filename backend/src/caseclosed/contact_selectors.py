from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import Case
from caseclosed.db.models import CaseStakeholder
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactTag
from caseclosed.email_addressing import normalize_email_address


def split_selector_list(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    selectors: list[str] = []
    for value in values:
        selectors.extend(
            selector.strip()
            for selector in re.split(r"[,;\n]", value)
            if selector.strip() != ""
        )
    return selectors


def selector_terms(selector: str) -> list[str]:
    return [
        term.strip()
        for term in selector.strip().strip("{}").split("&")
        if term.strip() != ""
    ]


def active_primary_email_address(
    session: DatabaseSession,
    contact_id: str,
) -> ContactEmailAddress | None:
    active_addresses = session.scalars(
        select(ContactEmailAddress)
        .where(
            ContactEmailAddress.contact_id == contact_id,
            ContactEmailAddress.deleted_at.is_(None),
            ContactEmailAddress.status == "active",
        )
        .order_by(ContactEmailAddress.is_primary.desc(), ContactEmailAddress.email_address)
    ).all()
    return active_addresses[0] if active_addresses else None


def contact_tags(session: DatabaseSession, contact_id: str) -> set[str]:
    return {
        tag.strip().lower()
        for tag in session.scalars(
            select(ContactTag.tag).where(ContactTag.contact_id == contact_id)
        ).all()
        if tag.strip() != ""
    }


def contact_matches_selector(
    session: DatabaseSession,
    contact: Contact,
    selector: str,
) -> bool:
    terms = selector_terms(selector)
    if len(terms) == 0:
        return False

    tags = contact_tags(session, contact.id)
    for term in terms:
        normalized = term.strip().lower()
        if normalized.startswith("!"):
            if normalized[1:] in tags:
                return False
            continue
        if normalized not in tags:
            return False
    return True


def matching_contacts(
    session: DatabaseSession,
    selector: str,
) -> list[Contact]:
    normalized_selector = selector.strip().lower()
    contacts = session.scalars(
        select(Contact)
        .where(
            Contact.deleted_at.is_(None),
            Contact.status != "spam",
        )
        .order_by(Contact.display_name, Contact.id)
    ).all()

    exact_matches: list[Contact] = []
    for contact in contacts:
        if contact.display_name.strip().lower() == normalized_selector:
            exact_matches.append(contact)
            continue
        active_addresses = session.scalars(
            select(ContactEmailAddress).where(
                ContactEmailAddress.contact_id == contact.id,
                ContactEmailAddress.deleted_at.is_(None),
                ContactEmailAddress.status == "active",
            )
        ).all()
        if any(
            normalize_email_address(address.email_address) == normalized_selector
            for address in active_addresses
        ):
            exact_matches.append(contact)
    if exact_matches:
        return exact_matches

    return [
        contact
        for contact in contacts
        if contact_matches_selector(session, contact, selector)
    ]


def case_role_selector_parts(selector: str) -> tuple[str, str] | None:
    match = re.match(r"^case:([^:]+):([^:]+)$", selector.strip(), flags=re.IGNORECASE)
    if match is None:
        return None
    case_name = match.group(1).strip().lower()
    role = match.group(2).strip().lower()
    if case_name == "" or role == "":
        return None
    return case_name, role


def matching_case_role_contacts(
    session: DatabaseSession,
    selector: str,
) -> list[Contact]:
    parts = case_role_selector_parts(selector)
    if parts is None:
        return []
    case_name, role = parts
    statement = (
        select(Contact)
        .join(CaseStakeholder, CaseStakeholder.contact_id == Contact.id)
        .join(Case, Case.id == CaseStakeholder.case_id)
        .where(Contact.deleted_at.is_(None))
        .where(Contact.status != "spam")
        .where(
            (func.lower(Case.name) == case_name)
            | (func.lower(Case.id) == case_name)
        )
        .order_by(CaseStakeholder.sort_order.asc(), Contact.display_name, Contact.id)
    )
    if role != "all":
        statement = statement.where(func.lower(CaseStakeholder.role) == role)
    rows = session.execute(statement).scalars().all()
    seen: set[str] = set()
    contacts: list[Contact] = []
    for contact in rows:
        if contact.id in seen:
            continue
        seen.add(contact.id)
        contacts.append(contact)
    return contacts


def resolve_recipient_selectors(
    session: DatabaseSession,
    values: list[str] | None,
) -> list[str]:
    resolved_addresses: list[str] = []
    seen: set[str] = set()
    for selector in split_selector_list(values):
        if "@" in selector:
            candidates = [selector]
        else:
            contacts = matching_case_role_contacts(session, selector) or matching_contacts(
                session,
                selector,
            )
            candidates = [
                email_address.email_address
                for contact in contacts
                if (email_address := active_primary_email_address(session, contact.id))
                is not None
            ]
            if not candidates:
                candidates = [selector]
        for address in candidates:
            normalized = normalize_email_address(address)
            if normalized == "" or normalized in seen:
                continue
            seen.add(normalized)
            resolved_addresses.append(address)
    return resolved_addresses
