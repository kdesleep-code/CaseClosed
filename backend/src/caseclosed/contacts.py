from __future__ import annotations

import json
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactRegistrationSuggestion
from caseclosed.db.models import ContactTag
from caseclosed.db.models import Job
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])

CONTACT_STATUSES = {"active", "skipped", "archived"}
EMAIL_ADDRESS_STATUSES = {"active", "inactive", "deleted"}


class ContactEmailAddressInput(BaseModel):
    email_address: str
    is_primary: bool = False


class ContactCreate(BaseModel):
    display_name: str
    avatar_url: str | None = None
    memo: str | None = None
    status: str = "active"
    tags: list[str] = []
    email_addresses: list[ContactEmailAddressInput] = []
    source_suggestion_id: str | None = None


class ContactPatch(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    memo: str | None = None
    status: str | None = None
    tags: list[str] | None = None


class PrefillRequest(BaseModel):
    message_id: str | None = None


class ContactEmailAddressMove(BaseModel):
    target_contact_id: str


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_email_address(email_address: str) -> str:
    return email_address.strip().lower()


def validate_contact_status(status: str) -> None:
    if status not in CONTACT_STATUSES:
        raise json_error(422, "VALIDATION_ERROR", "Invalid contact status.")


def validate_email_address(email_address: str) -> str:
    normalized = normalize_email_address(email_address)
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise json_error(422, "VALIDATION_ERROR", "Invalid email address.")
    return normalized


def contact_tags(session: DatabaseSession, contact_id: str) -> list[str]:
    return sorted(
        session.scalars(
            select(ContactTag.tag).where(ContactTag.contact_id == contact_id)
        ).all()
    )


def contact_email_addresses(
    session: DatabaseSession,
    contact_id: str,
) -> list[ContactEmailAddress]:
    return list(
        session.scalars(
            select(ContactEmailAddress)
            .where(
                ContactEmailAddress.contact_id == contact_id,
                ContactEmailAddress.deleted_at.is_(None),
            )
            .order_by(
                ContactEmailAddress.status,
                ContactEmailAddress.is_primary.desc(),
                ContactEmailAddress.email_address,
            )
        ).all()
    )


def active_contact_email_addresses(
    session: DatabaseSession,
    contact_id: str,
) -> list[ContactEmailAddress]:
    return [
        email_address
        for email_address in contact_email_addresses(session, contact_id)
        if email_address.status == "active"
    ]


def email_address_data(email_address: ContactEmailAddress) -> dict[str, object]:
    return {
        "id": email_address.id,
        "email_address": email_address.email_address,
        "normalized_email_address": email_address.normalized_email_address,
        "resolution_status": email_address.resolution_status,
        "status": email_address.status,
        "is_primary": bool(email_address.is_primary),
        "source": email_address.source,
        "first_seen_at": email_address.first_seen_at,
        "last_seen_at": email_address.last_seen_at,
        "has_inbound_message_history": bool(
            email_address.has_inbound_message_history
        ),
        "deactivated_at": email_address.deactivated_at,
    }


def contact_data(contact: Contact, session: DatabaseSession) -> dict[str, object]:
    return {
        "id": contact.id,
        "display_name": contact.display_name,
        "avatar_url": contact.avatar_url,
        "memo": contact.memo,
        "status": contact.status,
        "tags": contact_tags(session, contact.id),
        "email_addresses": [
            email_address_data(email_address)
            for email_address in contact_email_addresses(session, contact.id)
        ],
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
        "version": contact.version,
    }


def set_contact_tags(
    session: DatabaseSession,
    contact_id: str,
    tags: list[str],
    created_at: str,
) -> None:
    existing = session.scalars(
        select(ContactTag).where(ContactTag.contact_id == contact_id)
    ).all()
    for tag in existing:
        session.delete(tag)

    for tag in sorted({tag.strip() for tag in tags if tag.strip()}):
        session.add(
            ContactTag(
                id=new_id("contact_tag"),
                contact_id=contact_id,
                tag=tag,
                created_at=created_at,
            )
        )


def mark_source_suggestion_adopted(
    session: DatabaseSession,
    *,
    suggestion_id: str,
    payload: ContactCreate,
    now: str,
) -> None:
    suggestion = session.get(ContactRegistrationSuggestion, suggestion_id)
    if suggestion is None:
        raise json_error(404, "NOT_FOUND", "Contact suggestion not found.")

    payload_tags = sorted({tag.strip() for tag in payload.tags if tag.strip()})
    suggested_tags = sorted(json.loads(suggestion.suggested_tags_json or "[]"))
    suggestion.status = (
        "adopted"
        if suggestion.suggested_display_name == payload.display_name.strip()
        and suggested_tags == payload_tags
        else "edited_and_adopted"
    )
    suggestion.updated_at = now


def find_email_address(
    session: DatabaseSession,
    normalized_email_address: str,
) -> ContactEmailAddress | None:
    return session.scalar(
        select(ContactEmailAddress).where(
            ContactEmailAddress.normalized_email_address == normalized_email_address,
            ContactEmailAddress.deleted_at.is_(None),
        )
    )


def enqueue_contact_resolution_followup(
    session: DatabaseSession,
    *,
    contact: Contact,
    email_address: ContactEmailAddress,
    now: str,
) -> None:
    session.add(
        Job(
            id=new_id("job_contact_resolution_followup"),
            job_type="contact_resolution_followup",
            priority=60,
            status="pending",
            payload_json=json.dumps(
                {
                    "contact_id": contact.id,
                    "email_address_id": email_address.id,
                    "email_address": email_address.email_address,
                    "normalized_email_address": email_address.normalized_email_address,
                    "reason": "unresolved_contact_linked",
                },
                ensure_ascii=True,
            ),
            retry_count=0,
            max_retries=3,
            created_at=now,
            updated_at=now,
        )
    )


def link_email_address(
    session: DatabaseSession,
    contact: Contact,
    payload: ContactEmailAddressInput,
    *,
    now: str,
    source: str,
) -> ContactEmailAddress:
    normalized = validate_email_address(payload.email_address)
    existing = find_email_address(session, normalized)
    current_active_email_addresses = active_contact_email_addresses(session, contact.id)
    should_be_primary = payload.is_primary or len(current_active_email_addresses) == 0

    if should_be_primary:
        for email_address in current_active_email_addresses:
            email_address.is_primary = 0
            email_address.updated_at = now

    if existing is None:
        email_address = ContactEmailAddress(
            id=new_id("contact_email"),
            contact_id=contact.id,
            email_address=payload.email_address.strip(),
            normalized_email_address=normalized,
            resolution_status="linked",
            status="active",
            has_inbound_message_history=0,
            deactivated_at=None,
            deleted_at=None,
            is_primary=1 if should_be_primary else 0,
            source=source,
            first_seen_at=now if source == "manual" else None,
            last_seen_at=now if source == "manual" else None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(email_address)
        return email_address

    if (
        existing.contact_id is not None
        and existing.contact_id != contact.id
        and existing.status == "active"
    ):
        raise json_error(409, "CONFLICT", "Email address belongs to another contact.")

    was_unresolved = existing.resolution_status == "unresolved"
    existing.contact_id = contact.id
    existing.email_address = payload.email_address.strip()
    existing.resolution_status = "linked"
    existing.is_primary = 1 if should_be_primary else existing.is_primary
    existing.status = "active"
    existing.deactivated_at = None
    existing.source = existing.source or source
    existing.updated_at = now
    existing.version += 1
    if was_unresolved:
        enqueue_contact_resolution_followup(
            session,
            contact=contact,
            email_address=existing,
            now=now,
        )
    return existing


def get_contact_or_404(session: DatabaseSession, contact_id: str) -> Contact:
    contact = session.get(Contact, contact_id)
    if contact is None or contact.deleted_at is not None:
        raise json_error(404, "NOT_FOUND", "Contact not found.")
    return contact


def get_contact_email_address_or_404(
    session: DatabaseSession,
    contact_id: str,
    email_address_id: str,
) -> ContactEmailAddress:
    email_address = session.get(ContactEmailAddress, email_address_id)
    if (
        email_address is None
        or email_address.contact_id != contact_id
        or email_address.deleted_at is not None
    ):
        raise json_error(404, "NOT_FOUND", "Contact email address not found.")
    return email_address


def get_contact_email_address_by_id_or_404(
    session: DatabaseSession,
    email_address_id: str,
) -> ContactEmailAddress:
    email_address = session.get(ContactEmailAddress, email_address_id)
    if email_address is None or email_address.deleted_at is not None:
        raise json_error(404, "NOT_FOUND", "Contact email address not found.")
    return email_address


def ensure_active_primary_email_address(
    session: DatabaseSession,
    contact: Contact,
    *,
    now: str,
) -> None:
    active_email_addresses = active_contact_email_addresses(session, contact.id)
    if len(active_email_addresses) == 0:
        return
    if any(email_address.is_primary for email_address in active_email_addresses):
        return

    active_email_addresses[0].is_primary = 1
    active_email_addresses[0].updated_at = now
    active_email_addresses[0].version += 1


@router.get("")
def list_contacts(
    status: str = "all",
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = select(Contact).where(Contact.deleted_at.is_(None)).order_by(
        Contact.display_name,
        Contact.id,
    )
    if status != "all":
        validate_contact_status(status)
        statement = statement.where(Contact.status == status)

    contacts = session.scalars(statement).all()
    return {
        "ok": True,
        "data": {"items": [contact_data(contact, session) for contact in contacts]},
    }


@router.get("/unresolved-from-addresses")
def list_unresolved_from_addresses(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    email_addresses = session.scalars(
        select(ContactEmailAddress)
        .where(ContactEmailAddress.resolution_status == "unresolved")
        .order_by(ContactEmailAddress.last_seen_at.desc(), ContactEmailAddress.email_address)
    ).all()

    items = []
    for email_address in email_addresses:
        suggestion = session.scalar(
            select(ContactRegistrationSuggestion)
            .where(
                ContactRegistrationSuggestion.email_address_id == email_address.id,
                ContactRegistrationSuggestion.status.in_(
                    ["suggested", "adopted", "edited_and_adopted"]
                ),
            )
            .order_by(ContactRegistrationSuggestion.created_at.desc())
        )
        items.append(
            {
                "email_address_id": email_address.id,
                "email_address": email_address.email_address,
                "normalized_email_address": email_address.normalized_email_address,
                "message_count": 0,
                "latest_message_id": None,
                "latest_subject": None,
                "suggestion_status": "succeeded" if suggestion is not None else "not_started",
                "suggestion": None
                if suggestion is None
                else {
                    "id": suggestion.id,
                    "suggested_display_name": suggestion.suggested_display_name,
                    "suggested_tags": json.loads(suggestion.suggested_tags_json or "[]"),
                    "confidence": suggestion.confidence,
                },
            }
        )

    return {"ok": True, "data": {"items": items}}


@router.post("/unresolved-from-addresses/{encoded_email}/generate-prefill")
def generate_unresolved_from_prefill(
    encoded_email: str,
    payload: PrefillRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized = validate_email_address(unquote(encoded_email))
    email_address = find_email_address(session, normalized)
    if email_address is None or email_address.resolution_status != "unresolved":
        raise json_error(404, "NOT_FOUND", "Unresolved email address not found.")

    now = jst_iso()
    job = Job(
        id=new_id("job_contact_prefill"),
        job_type="contact_registration_prefill",
        priority=50,
        status="pending",
        payload_json=json.dumps(
            {
                "email_address_id": email_address.id,
                "email_address": email_address.email_address,
                "normalized_email_address": normalized,
                "message_id": payload.message_id,
            },
            ensure_ascii=True,
        ),
        retry_count=0,
        max_retries=3,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    return {"ok": True, "data": {"job_id": job.id}}


@router.get("/{contact_id}")
def get_contact_detail(
    contact_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    return {
        "ok": True,
        "data": {
            "contact": contact_data(contact, session),
            "related_cases": [],
        },
    }


@router.post("")
def create_contact(
    payload: ContactCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    validate_contact_status(payload.status)
    display_name = payload.display_name.strip()
    if display_name == "":
        raise json_error(422, "VALIDATION_ERROR", "Display name is required.")

    now = jst_iso()
    contact = Contact(
        id=new_id("contact"),
        display_name=display_name,
        avatar_url=payload.avatar_url,
        memo=payload.memo,
        status=payload.status,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(contact)
    session.flush()

    set_contact_tags(session, contact.id, payload.tags, now)
    for email_address in payload.email_addresses:
        link_email_address(session, contact, email_address, now=now, source="manual")
    if payload.source_suggestion_id is not None:
        mark_source_suggestion_adopted(
            session,
            suggestion_id=payload.source_suggestion_id,
            payload=payload,
            now=now,
        )

    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.patch("/{contact_id}")
def update_contact(
    contact_id: str,
    payload: ContactPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)

    if payload.status is not None:
        validate_contact_status(payload.status)
        contact.status = payload.status
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if display_name == "":
            raise json_error(422, "VALIDATION_ERROR", "Display name is required.")
        contact.display_name = display_name
    if payload.avatar_url is not None:
        contact.avatar_url = payload.avatar_url.strip() or None
    if payload.memo is not None:
        contact.memo = payload.memo

    now = jst_iso()
    if payload.tags is not None:
        set_contact_tags(session, contact.id, payload.tags, now)

    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/skip")
def skip_contact(
    contact_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)

    contact.status = "skipped"
    contact.version += 1
    contact.updated_at = jst_iso()
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/activate")
def activate_contact(
    contact_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)

    contact.status = "active"
    contact.version += 1
    contact.updated_at = jst_iso()
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/email-addresses")
def add_contact_email_address(
    contact_id: str,
    payload: ContactEmailAddressInput,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)

    now = jst_iso()
    link_email_address(session, contact, payload, now=now, source="manual")
    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/email-addresses/{email_address_id}/primary")
def set_contact_primary_email_address(
    contact_id: str,
    email_address_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    selected_email_address = get_contact_email_address_or_404(
        session,
        contact.id,
        email_address_id,
    )
    if selected_email_address.status != "active":
        raise json_error(409, "CONFLICT", "Inactive email address cannot be primary.")

    now = jst_iso()
    for email_address in active_contact_email_addresses(session, contact.id):
        email_address.is_primary = 1 if email_address.id == selected_email_address.id else 0
        email_address.updated_at = now
        email_address.version += 1
    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/email-addresses/{email_address_id}/activate")
def activate_contact_email_address(
    contact_id: str,
    email_address_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    email_address = get_contact_email_address_or_404(
        session,
        contact.id,
        email_address_id,
    )
    if email_address.status == "active":
        return {"ok": True, "data": contact_data(contact, session)}

    now = jst_iso()
    had_active_email_addresses = len(active_contact_email_addresses(session, contact.id)) > 0
    email_address.status = "active"
    email_address.deactivated_at = None
    email_address.is_primary = 0 if had_active_email_addresses else 1
    email_address.updated_at = now
    email_address.version += 1
    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}


@router.post("/{contact_id}/email-addresses/{email_address_id}/move")
def move_contact_email_address(
    contact_id: str,
    email_address_id: str,
    payload: ContactEmailAddressMove,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    source_contact = get_contact_or_404(session, contact_id)
    target_contact = get_contact_or_404(session, payload.target_contact_id)
    if source_contact.id == target_contact.id:
        raise json_error(409, "CONFLICT", "Target contact must be different.")

    email_address = get_contact_email_address_by_id_or_404(session, email_address_id)
    if email_address.contact_id != source_contact.id:
        raise json_error(
            404,
            "NOT_FOUND",
            "Contact email address not found on source contact.",
        )

    now = jst_iso()
    was_primary = bool(email_address.is_primary)
    target_had_active_email_addresses = len(
        active_contact_email_addresses(session, target_contact.id)
    ) > 0

    email_address.contact_id = target_contact.id
    email_address.resolution_status = "linked"
    if email_address.status == "active":
        email_address.is_primary = 0 if target_had_active_email_addresses else 1
    else:
        email_address.is_primary = 0
    email_address.updated_at = now
    email_address.version += 1

    if email_address.status == "active" and not target_had_active_email_addresses:
        for target_email_address in active_contact_email_addresses(
            session,
            target_contact.id,
        ):
            if target_email_address.id != email_address.id:
                target_email_address.is_primary = 0
                target_email_address.updated_at = now
                target_email_address.version += 1

    if was_primary:
        ensure_active_primary_email_address(session, source_contact, now=now)

    source_contact.version += 1
    source_contact.updated_at = now
    target_contact.version += 1
    target_contact.updated_at = now
    session.commit()
    return {
        "ok": True,
        "data": {
            "source_contact": contact_data(source_contact, session),
            "target_contact": contact_data(target_contact, session),
        },
    }


@router.delete("/{contact_id}/email-addresses/{email_address_id}")
def delete_contact_email_address(
    contact_id: str,
    email_address_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    email_address = get_contact_email_address_or_404(
        session,
        contact.id,
        email_address_id,
    )

    was_primary = bool(email_address.is_primary)
    now = jst_iso()
    if email_address.has_inbound_message_history:
        email_address.status = "inactive"
        email_address.is_primary = 0
        email_address.deactivated_at = now
        email_address.updated_at = now
        email_address.version += 1
    else:
        session.delete(email_address)
        session.flush()

    remaining_email_addresses = active_contact_email_addresses(session, contact.id)
    if was_primary and len(remaining_email_addresses) > 0:
        ensure_active_primary_email_address(session, contact, now=now)

    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": contact_data(contact, session)}
