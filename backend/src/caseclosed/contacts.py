from __future__ import annotations

import json
import re
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import AppSetting
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import ContactRegistrationSuggestion
from caseclosed.db.models import ContactTag
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import MailAutoState
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_email_address
from caseclosed.services.mail_ingestion import (
    apply_contact_mail_importance_rule,
    apply_fixed_importance_rule_to_existing_contact_mail,
    apply_spam_status_to_existing_contact_mail,
)
from caseclosed.services.background_worker import kick_job_drain

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])

CONTACT_STATUSES = {"active", "skipped", "spam", "archived"}
EMAIL_ADDRESS_STATUSES = {"active", "inactive", "deleted"}
CONTACT_KINDS = {"person", "mailing_list"}
SENDER_RESOLUTION_MODES = {"self", "reply_to"}
RESERVED_CONTACT_TAGS = {"mailing-list"}
MAIL_IMPORTANCE_RULE_ACTIONS = {"llm", "fixed", "llm_with_instruction"}
MAIL_IMPORTANCE_RULE_VALUES = {"pinned", "high", "middle", "low"}
CONTACT_CUSTOM_TABS_KEY = "contact_custom_tabs"
MAX_CONTACT_CUSTOM_TABS = 4
MAX_CONTACT_CUSTOM_TAB_NAME_LENGTH = 12


class ContactEmailAddressInput(BaseModel):
    email_address: str
    is_primary: bool = False


class ContactCreate(BaseModel):
    display_name: str
    avatar_url: str | None = None
    memo: str | None = None
    user_memo: str | None = None
    ai_memo: str | None = None
    status: str = "active"
    kind: str = "person"
    sender_resolution_mode: str = "self"
    mailing_list_recipient_expression: str | None = None
    mail_importance_rule_action: str = "llm"
    mail_importance_rule_importance: str | None = None
    mail_importance_rule_instruction: str | None = None
    tags: list[str] = []
    email_addresses: list[ContactEmailAddressInput] = []
    source_suggestion_id: str | None = None


class ContactPatch(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    memo: str | None = None
    user_memo: str | None = None
    ai_memo: str | None = None
    status: str | None = None
    kind: str | None = None
    sender_resolution_mode: str | None = None
    mailing_list_recipient_expression: str | None = None
    mail_importance_rule_action: str | None = None
    mail_importance_rule_importance: str | None = None
    mail_importance_rule_instruction: str | None = None
    tags: list[str] | None = None


class PrefillRequest(BaseModel):
    message_id: str | None = None


class ContactEmailAddressMove(BaseModel):
    target_contact_id: str


class ContactMerge(BaseModel):
    target_contact_id: str


class ContactCustomTabInput(BaseModel):
    id: str
    label: str
    expression: str


class ContactCustomTabsPayload(BaseModel):
    items: list[ContactCustomTabInput]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def read_setting_json(session: DatabaseSession, key: str) -> dict[str, object] | None:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        return None
    data = json.loads(setting.value_json)
    return data if isinstance(data, dict) else None


def write_setting_json(
    session: DatabaseSession,
    key: str,
    value: dict[str, object],
    now: str,
) -> None:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    value_json = json.dumps(value, ensure_ascii=True, sort_keys=True)
    if setting is None:
        session.add(
            AppSetting(
                id=f"setting_{key}",
                key=key,
                value_json=value_json,
                updated_at=now,
            )
        )
        return
    setting.value_json = value_json
    setting.updated_at = now


def contact_custom_tab_data(tab: ContactCustomTabInput) -> dict[str, str]:
    return {
        "id": tab.id.strip(),
        "label": tab.label.strip()[:MAX_CONTACT_CUSTOM_TAB_NAME_LENGTH],
        "expression": tab.expression.strip(),
    }


def validate_contact_custom_tabs(tabs: list[ContactCustomTabInput]) -> list[dict[str, str]]:
    if len(tabs) > MAX_CONTACT_CUSTOM_TABS:
        raise json_error(422, "VALIDATION_ERROR", "Too many custom contact tabs.")
    items = []
    seen_ids = set()
    for tab in tabs:
        item = contact_custom_tab_data(tab)
        if item["id"] == "" or item["label"] == "" or item["expression"] == "":
            raise json_error(422, "VALIDATION_ERROR", "Custom contact tab is invalid.")
        if item["id"] in seen_ids:
            raise json_error(422, "VALIDATION_ERROR", "Custom contact tab id is duplicated.")
        seen_ids.add(item["id"])
        items.append(item)
    return items


def validate_contact_status(status: str) -> None:
    if status not in CONTACT_STATUSES:
        raise json_error(422, "VALIDATION_ERROR", "Invalid contact status.")


def validate_contact_kind(kind: str) -> None:
    if kind not in CONTACT_KINDS:
        raise json_error(422, "VALIDATION_ERROR", "Invalid contact kind.")


def validate_sender_resolution_mode(
    *,
    kind: str,
    sender_resolution_mode: str,
) -> None:
    if sender_resolution_mode not in SENDER_RESOLUTION_MODES:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Invalid contact sender resolution mode.",
        )
    if kind == "person" and sender_resolution_mode != "self":
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Person contacts must use self sender resolution.",
        )


def validate_contact_tags(*, kind: str, tags: list[str]) -> None:
    normalized_tags = {tag.strip().lower() for tag in tags if tag.strip()}
    if RESERVED_CONTACT_TAGS & normalized_tags:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Reserved contact tag cannot be used.",
        )
    if kind == "mailing_list" and len(normalized_tags) > 0:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Mailing list contacts do not use contact tags.",
        )


def validate_mail_importance_rule(
    *,
    action: str,
    importance: str | None,
    instruction: str | None,
) -> None:
    if action not in MAIL_IMPORTANCE_RULE_ACTIONS:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Invalid mail importance rule action.",
        )
    if importance is not None and importance not in MAIL_IMPORTANCE_RULE_VALUES:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Invalid mail importance rule value.",
        )
    if action == "fixed" and importance is None:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Fixed mail importance rule requires an importance value.",
        )
    if action != "fixed" and importance is not None:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Only fixed mail importance rules can set an importance value.",
        )
    if action == "llm_with_instruction" and normalize_optional_text(instruction) is None:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "LLM instruction rule requires instruction text.",
        )


def display_name_from_email_address(email_address: str) -> str:
    local_part = email_address.split("@", maxsplit=1)[0]
    words = [word for word in re.split(r"[._+\-]+", local_part) if word]
    if not words:
        return email_address
    return " ".join(word.capitalize() for word in words)


def inferred_pending_display_name(
    email_address: ContactEmailAddress,
    latest_message: GmailMessage | None,
    latest_auto_state: MailAutoState | None,
) -> str:
    if (
        latest_auto_state is None
        or latest_auto_state.pending_reason != "unresolved_reply_to_contact"
    ) and latest_message is not None and latest_message.from_name is not None:
        from_name = latest_message.from_name.strip()
        if from_name != "":
            return from_name
    return display_name_from_email_address(email_address.email_address)


def inferred_pending_kind(
    latest_message: GmailMessage | None,
    latest_auto_state: MailAutoState | None,
) -> str:
    if (
        latest_auto_state is not None
        and latest_auto_state.pending_reason == "unresolved_reply_to_contact"
    ):
        return "person"
    if (
        latest_message is not None
        and latest_message.reply_to_address is not None
        and latest_message.reply_to_address.strip().lower()
        != latest_message.from_address.strip().lower()
    ):
        return "mailing_list"
    return "person"


def inferred_pending_sender_resolution(
    latest_message: GmailMessage | None,
    latest_auto_state: MailAutoState | None,
) -> str:
    return (
        "reply_to"
        if inferred_pending_kind(latest_message, latest_auto_state) == "mailing_list"
        else "self"
    )


def body_preview(message: GmailMessage | None) -> str | None:
    if message is None:
        return None
    text_value = message.snippet or message.body_text
    if text_value is None:
        return None
    return " ".join(text_value.split())[:280]


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


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
    user_memo = contact.user_memo if contact.user_memo is not None else contact.memo
    email_addresses = contact_email_addresses(session, contact.id)
    return {
        "id": contact.id,
        "display_name": contact.display_name,
        "avatar_url": contact.avatar_url,
        "user_memo": user_memo,
        "ai_memo": contact.ai_memo,
        "status": contact.status,
        "kind": contact.kind,
        "sender_resolution_mode": contact.sender_resolution_mode,
        "mailing_list_recipient_expression": contact.mailing_list_recipient_expression,
        "mail_importance_rule_action": contact.mail_importance_rule_action,
        "mail_importance_rule_importance": contact.mail_importance_rule_importance,
        "mail_importance_rule_instruction": contact.mail_importance_rule_instruction,
        "inbound_message_count": contact.inbound_message_count,
        "latest_received_at": contact.latest_received_at,
        "tags": [] if contact.kind == "mailing_list" else contact_tags(session, contact.id),
        "email_addresses": [email_address_data(email_address) for email_address in email_addresses],
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
        "version": contact.version,
    }


def recalculate_contact_inbound_message_count(
    session: DatabaseSession,
    contact: Contact,
) -> None:
    normalized_addresses = list(
        session.scalars(
            select(ContactEmailAddress.normalized_email_address).where(
                ContactEmailAddress.contact_id == contact.id,
                ContactEmailAddress.deleted_at.is_(None),
            )
        ).all()
    )
    if not normalized_addresses:
        contact.inbound_message_count = 0
        contact.latest_received_at = None
        return

    count, latest_received_at = session.execute(
        select(func.count(func.distinct(GmailMessage.id)), func.max(GmailMessage.received_at))
        .where(
            (GmailMessage.from_address.in_(normalized_addresses))
            | (GmailMessage.reply_to_address.in_(normalized_addresses))
        )
        .where(~func.coalesce(GmailMessage.gmail_labels_json, "").like('%"SENT"%'))
    ).one()
    contact.inbound_message_count = int(count or 0)
    contact.latest_received_at = latest_received_at


def unique_contact_display_name(
    session: DatabaseSession,
    desired_display_name: str,
    *,
    exclude_contact_id: str | None = None,
) -> str:
    existing_names = set(
        session.scalars(
            select(Contact.display_name).where(Contact.deleted_at.is_(None))
        ).all()
    )
    if exclude_contact_id is not None:
        current_name = session.scalar(
            select(Contact.display_name).where(Contact.id == exclude_contact_id)
        )
        if current_name is not None:
            existing_names.discard(current_name)

    if desired_display_name not in existing_names:
        return desired_display_name

    suffix = 2
    while f"{desired_display_name}_{suffix}" in existing_names:
        suffix += 1
    return f"{desired_display_name}_{suffix}"


def set_contact_tags(
    session: DatabaseSession,
    contact_id: str,
    tags: list[str],
    created_at: str,
) -> None:
    contact = session.get(Contact, contact_id)
    validate_contact_tags(kind=contact.kind if contact is not None else "person", tags=tags)
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


def release_pending_mail_for_email_address(
    session: DatabaseSession,
    *,
    contact: Contact,
    email_address: ContactEmailAddress,
    now: str,
) -> dict[str, int]:
    pending_states = session.scalars(
        select(MailAutoState).where(
            MailAutoState.pending_from_address_id == email_address.id
        )
    ).all()
    queued = 0
    released = 0
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
        if result.changed:
            released += 1
        if result.queued_job_id is not None:
            queued += 1
    return {"released": released, "queued": queued}


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
    current_email_addresses = contact_email_addresses(session, contact.id)
    if (
        contact.kind == "mailing_list"
        and len(current_email_addresses) > 0
        and (existing is None or existing.contact_id != contact.id)
    ):
        raise json_error(
            409,
            "CONFLICT",
            "Mailing list contact can have only one email address.",
        )
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

    existing.contact_id = contact.id
    existing.email_address = payload.email_address.strip()
    existing.resolution_status = "linked"
    existing.is_primary = 1 if should_be_primary else existing.is_primary
    existing.status = "active"
    existing.deactivated_at = None
    existing.source = existing.source or source
    existing.updated_at = now
    existing.version += 1
    release_pending_mail_for_email_address(
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


@router.get("/custom-tabs")
def get_contact_custom_tabs(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    setting = read_setting_json(session, CONTACT_CUSTOM_TABS_KEY) or {}
    items = setting.get("items")
    if not isinstance(items, list):
        items = []
    safe_items = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "expression": item.get("expression"),
        }
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("label"), str)
        and isinstance(item.get("expression"), str)
    ]
    return {"ok": True, "data": {"items": safe_items[:MAX_CONTACT_CUSTOM_TABS]}}


@router.put("/custom-tabs")
def update_contact_custom_tabs(
    payload: ContactCustomTabsPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    items = validate_contact_custom_tabs(payload.items)
    write_setting_json(session, CONTACT_CUSTOM_TABS_KEY, {"items": items}, now)
    session.commit()
    return {"ok": True, "data": {"items": items}}


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
        pending_rows = session.execute(
            select(GmailMessage, MailAutoState)
            .join(MailAutoState, MailAutoState.message_id == GmailMessage.id)
            .where(MailAutoState.pending_from_address_id == email_address.id)
            .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
        ).all()
        latest_message = pending_rows[0][0] if len(pending_rows) > 0 else None
        latest_auto_state = pending_rows[0][1] if len(pending_rows) > 0 else None
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
                "message_count": len(pending_rows),
                "latest_message_id": latest_message.id if latest_message is not None else None,
                "latest_subject": latest_message.subject if latest_message is not None else None,
                "latest_from_name": latest_message.from_name if latest_message is not None else None,
                "latest_from_address": latest_message.from_address if latest_message is not None else None,
                "latest_reply_to_address": (
                    latest_message.reply_to_address if latest_message is not None else None
                ),
                "latest_received_at": latest_message.received_at if latest_message is not None else None,
                "latest_body_preview": body_preview(latest_message),
                "inferred_display_name": inferred_pending_display_name(
                    email_address,
                    latest_message,
                    latest_auto_state,
                ),
                "inferred_kind": inferred_pending_kind(
                    latest_message,
                    latest_auto_state,
                ),
                "inferred_sender_resolution": inferred_pending_sender_resolution(
                    latest_message,
                    latest_auto_state,
                ),
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
    validate_contact_kind(payload.kind)
    validate_sender_resolution_mode(
        kind=payload.kind,
        sender_resolution_mode=payload.sender_resolution_mode,
    )
    validate_contact_tags(kind=payload.kind, tags=payload.tags)
    validate_mail_importance_rule(
        action=payload.mail_importance_rule_action,
        importance=payload.mail_importance_rule_importance,
        instruction=payload.mail_importance_rule_instruction,
    )
    if payload.kind == "mailing_list" and len(payload.email_addresses) > 1:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Mailing list contact can have only one email address.",
        )
    display_name = payload.display_name.strip()
    if display_name == "":
        raise json_error(422, "VALIDATION_ERROR", "Display name is required.")
    display_name = unique_contact_display_name(session, display_name)

    now = jst_iso()
    contact = Contact(
        id=new_id("contact"),
        display_name=display_name,
        avatar_url=payload.avatar_url,
        memo=payload.memo,
        user_memo=payload.user_memo if payload.user_memo is not None else payload.memo,
        ai_memo=payload.ai_memo,
        status=payload.status,
        kind=payload.kind,
        sender_resolution_mode=payload.sender_resolution_mode,
        mailing_list_recipient_expression=normalize_optional_text(
            payload.mailing_list_recipient_expression
        ),
        mail_importance_rule_action=payload.mail_importance_rule_action,
        mail_importance_rule_importance=payload.mail_importance_rule_importance,
        mail_importance_rule_instruction=normalize_optional_text(
            payload.mail_importance_rule_instruction
        ),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(contact)
    session.flush()

    set_contact_tags(session, contact.id, payload.tags, now)
    for email_address in payload.email_addresses:
        link_email_address(session, contact, email_address, now=now, source="manual")
    recalculate_contact_inbound_message_count(session, contact)
    if contact.status == "spam":
        apply_spam_status_to_existing_contact_mail(
            session,
            contact=contact,
            now=now,
        )
    if payload.source_suggestion_id is not None:
        mark_source_suggestion_adopted(
            session,
            suggestion_id=payload.source_suggestion_id,
            payload=payload,
            now=now,
        )

    session.commit()
    kick_job_drain(reason="contact_created")
    return {"ok": True, "data": contact_data(contact, session)}


@router.patch("/{contact_id}")
def update_contact(
    contact_id: str,
    payload: ContactPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    previous_status = contact.status
    previous_mail_importance_rule_action = contact.mail_importance_rule_action
    previous_mail_importance_rule_importance = contact.mail_importance_rule_importance

    next_kind = payload.kind if payload.kind is not None else contact.kind
    if next_kind != contact.kind:
        raise json_error(
            409,
            "CONTACT_KIND_CHANGE_NOT_ALLOWED",
            "Contact kind cannot be changed after creation.",
        )
    next_sender_resolution_mode = (
        payload.sender_resolution_mode
        if payload.sender_resolution_mode is not None
        else contact.sender_resolution_mode
    )
    validate_contact_kind(next_kind)
    validate_sender_resolution_mode(
        kind=next_kind,
        sender_resolution_mode=next_sender_resolution_mode,
    )
    next_tags = payload.tags if payload.tags is not None else contact_tags(session, contact.id)
    validate_contact_tags(kind=next_kind, tags=next_tags)
    next_mail_importance_rule_action = (
        payload.mail_importance_rule_action
        if payload.mail_importance_rule_action is not None
        else contact.mail_importance_rule_action
    )
    next_mail_importance_rule_importance = (
        payload.mail_importance_rule_importance
        if payload.mail_importance_rule_importance is not None
        else contact.mail_importance_rule_importance
    )
    next_mail_importance_rule_instruction = (
        payload.mail_importance_rule_instruction
        if payload.mail_importance_rule_instruction is not None
        else contact.mail_importance_rule_instruction
    )
    validate_mail_importance_rule(
        action=next_mail_importance_rule_action,
        importance=next_mail_importance_rule_importance,
        instruction=next_mail_importance_rule_instruction,
    )

    if payload.status is not None:
        validate_contact_status(payload.status)
        contact.status = payload.status
    contact.kind = next_kind
    contact.sender_resolution_mode = next_sender_resolution_mode
    contact.mail_importance_rule_action = next_mail_importance_rule_action
    contact.mail_importance_rule_importance = (
        next_mail_importance_rule_importance
        if next_mail_importance_rule_action == "fixed"
        else None
    )
    contact.mail_importance_rule_instruction = normalize_optional_text(
        next_mail_importance_rule_instruction
    )
    if next_mail_importance_rule_action != "llm_with_instruction":
        contact.mail_importance_rule_instruction = None
    if payload.mailing_list_recipient_expression is not None:
        contact.mailing_list_recipient_expression = normalize_optional_text(
            payload.mailing_list_recipient_expression
        )
    if next_kind != "mailing_list":
        contact.mailing_list_recipient_expression = None
    if payload.display_name is not None:
        display_name = payload.display_name.strip()
        if display_name == "":
            raise json_error(422, "VALIDATION_ERROR", "Display name is required.")
        contact.display_name = unique_contact_display_name(
            session,
            display_name,
            exclude_contact_id=contact.id,
        )
    if payload.avatar_url is not None:
        contact.avatar_url = payload.avatar_url.strip() or None
    if payload.user_memo is not None:
        contact.user_memo = payload.user_memo
        contact.memo = payload.user_memo
    elif payload.memo is not None:
        contact.user_memo = payload.memo
        contact.memo = payload.memo
    if payload.ai_memo is not None:
        contact.ai_memo = payload.ai_memo

    now = jst_iso()
    if payload.tags is not None:
        set_contact_tags(session, contact.id, payload.tags, now)
    elif next_kind == "mailing_list":
        set_contact_tags(session, contact.id, [], now)

    contact.version += 1
    contact.updated_at = now
    fixed_importance_rule_changed = (
        contact.mail_importance_rule_action == "fixed"
        and (
            previous_mail_importance_rule_action != contact.mail_importance_rule_action
            or previous_mail_importance_rule_importance
            != contact.mail_importance_rule_importance
            or previous_status != contact.status
        )
    )
    if fixed_importance_rule_changed:
        apply_fixed_importance_rule_to_existing_contact_mail(
            session,
            contact=contact,
            now=now,
        )
    if contact.status == "spam" and previous_status != "spam":
        apply_spam_status_to_existing_contact_mail(
            session,
            contact=contact,
            now=now,
        )
    session.commit()
    kick_job_drain(reason="contact_updated")
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
    recalculate_contact_inbound_message_count(session, contact)
    if contact.status == "spam":
        apply_spam_status_to_existing_contact_mail(
            session,
            contact=contact,
            now=now,
        )
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
    if contact.kind == "mailing_list":
        raise json_error(
            409,
            "CONFLICT",
            "Mailing list email address is always primary.",
        )
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
    if contact.kind == "mailing_list":
        raise json_error(
            409,
            "CONFLICT",
            "Mailing list email address is always active.",
        )
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
    if source_contact.kind != target_contact.kind:
        raise json_error(
            409,
            "CONFLICT",
            "Email addresses cannot move between contact kinds.",
        )

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
    if target_contact.kind == "mailing_list" and len(
        contact_email_addresses(session, target_contact.id)
    ) > 0:
        raise json_error(
            409,
            "CONFLICT",
            "Mailing list contact can have only one email address.",
        )

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
    release_pending_mail_for_email_address(
        session,
        contact=target_contact,
        email_address=email_address,
        now=now,
    )
    recalculate_contact_inbound_message_count(session, source_contact)
    recalculate_contact_inbound_message_count(session, target_contact)

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


@router.post("/{contact_id}/merge")
def merge_contact(
    contact_id: str,
    payload: ContactMerge,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    source_contact = get_contact_or_404(session, contact_id)
    target_contact = get_contact_or_404(session, payload.target_contact_id)
    if source_contact.id == target_contact.id:
        raise json_error(409, "CONFLICT", "Target contact must be different.")
    if (
        source_contact.kind != "person"
        or target_contact.kind != "person"
        or source_contact.status != "active"
        or target_contact.status != "active"
    ):
        raise json_error(
            409,
            "CONFLICT",
            "Only active person contacts can be merged.",
        )

    now = jst_iso()
    older_contact, newer_contact = (
        (source_contact, target_contact)
        if source_contact.created_at <= target_contact.created_at
        else (target_contact, source_contact)
    )
    older_user_memo = (
        older_contact.user_memo
        if older_contact.user_memo is not None
        else older_contact.memo
    )
    newer_user_memo = (
        newer_contact.user_memo
        if newer_contact.user_memo is not None
        else newer_contact.memo
    )
    target_contact.user_memo = (
        older_user_memo
        if normalize_optional_text(older_user_memo) is not None
        else newer_user_memo
    )
    target_contact.memo = target_contact.user_memo
    target_contact.ai_memo = (
        older_contact.ai_memo
        if normalize_optional_text(older_contact.ai_memo) is not None
        else newer_contact.ai_memo
    )
    target_has_active_primary = any(
        email_address.is_primary
        for email_address in active_contact_email_addresses(session, target_contact.id)
    )
    for email_address in contact_email_addresses(session, source_contact.id):
        email_address.contact_id = target_contact.id
        email_address.resolution_status = "linked"
        if email_address.status == "active" and not target_has_active_primary:
            email_address.is_primary = 1
            target_has_active_primary = True
        else:
            email_address.is_primary = 0
        email_address.updated_at = now
        email_address.version += 1
        release_pending_mail_for_email_address(
            session,
            contact=target_contact,
            email_address=email_address,
            now=now,
        )
    recalculate_contact_inbound_message_count(session, source_contact)
    recalculate_contact_inbound_message_count(session, target_contact)

    merged_tags = sorted(
        set(contact_tags(session, source_contact.id))
        | set(contact_tags(session, target_contact.id))
    )
    set_contact_tags(session, target_contact.id, merged_tags, now)
    set_contact_tags(session, source_contact.id, [], now)
    source_contact.deleted_at = now
    source_contact.version += 1
    source_contact.updated_at = now
    target_contact.version += 1
    target_contact.updated_at = now
    session.commit()
    return {
        "ok": True,
        "data": {
            "deleted_contact_id": source_contact.id,
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
    if contact.kind == "mailing_list":
        raise json_error(
            409,
            "CONFLICT",
            "Mailing list email address cannot be removed.",
        )
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


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    contact = get_contact_or_404(session, contact_id)
    email_addresses = contact_email_addresses(session, contact.id)
    if any(email_address.has_inbound_message_history for email_address in email_addresses):
        raise json_error(
            409,
            "CONFLICT",
            "Contact has email address history and cannot be removed.",
        )

    now = jst_iso()
    for email_address in email_addresses:
        session.delete(email_address)
    set_contact_tags(session, contact.id, [], now)
    contact.deleted_at = now
    contact.version += 1
    contact.updated_at = now
    session.commit()
    return {"ok": True, "data": {"deleted_contact_id": contact.id}}
