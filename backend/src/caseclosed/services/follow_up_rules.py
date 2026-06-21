from __future__ import annotations

import json
import re
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import FollowUp
from caseclosed.db.models import GmailMessage
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import parse_iso_datetime
from caseclosed.email_addressing import normalize_email_address

FOLLOW_UP_PHRASES = [
    "ご確認",
    "ご査収",
    "ご検討",
    "ご返信",
    "お返事",
    "ご回答",
    "回答",
    "確認お願いします",
    "ご対応",
    "お願いいたします",
    "お願いします",
    "いかがでしょうか",
]

AUTO_BODY_START_PATTERNS = [
    re.compile(
        r"\d{4}\s*\u5e74\s*\d{1,2}\s*\u6708\s*\d{1,2}\s*\u65e5"
        r"(?:\([^)]*\))?\s+\d{1,2}:\d{2}.*<[^>\n]+>.*:",
        re.IGNORECASE,
    ),
    re.compile(
        r"\d{4}[/-]\d{1,2}[/-]\d{1,2}.*\d{1,2}:\d{2}.*<[^>\n]+>.*:",
        re.IGNORECASE,
    ),
    re.compile(
        r"<[^>\n]+>.*\d{4}\s*\u5e74\s*\d{1,2}\s*\u6708\s*\d{1,2}"
        r"\s*\u65e5.*(?:[:\uff1a]|\u5199\u9053)",
        re.IGNORECASE,
    ),
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^From:\s+.+", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^>"),
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def body_text_without_auto_body(body_text: str | None) -> str:
    if body_text is None:
        return ""
    kept_lines: list[str] = []
    for line in body_text.splitlines():
        stripped = line.strip()
        if stripped != "" and any(pattern.search(stripped) for pattern in AUTO_BODY_START_PATTERNS):
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def first_matched_phrase(message: GmailMessage) -> str | None:
    haystack = f"{message.subject or ''}\n{body_text_without_auto_body(message.body_text)}"
    return next((phrase for phrase in FOLLOW_UP_PHRASES if phrase in haystack), None)


def recipient_contact_kind(session: DatabaseSession, email_address: str) -> str | None:
    normalized = normalize_email_address(email_address)
    email = session.scalar(
        select(ContactEmailAddress).where(
            ContactEmailAddress.normalized_email_address == normalized,
            ContactEmailAddress.deleted_at.is_(None),
        )
    )
    if email is None or email.contact_id is None:
        return None
    contact = session.get(Contact, email.contact_id)
    if contact is None or contact.deleted_at is not None:
        return None
    return contact.kind


def has_person_or_unknown_recipient(session: DatabaseSession, message: GmailMessage) -> bool:
    recipients = [
        *json_list(message.to_addresses_json),
        *json_list(message.cc_addresses_json),
        *json_list(message.bcc_addresses_json),
    ]
    if not recipients:
        return False
    kinds = [recipient_contact_kind(session, recipient) for recipient in recipients]
    return any(kind is None or kind == "person" for kind in kinds)


def source_case_id(session: DatabaseSession, source_message: GmailMessage) -> str | None:
    direct_case_id = session.scalar(
        select(CaseMailLink.case_id)
        .where(CaseMailLink.message_id == source_message.id)
        .order_by(CaseMailLink.created_at.desc(), CaseMailLink.id.desc())
    )
    if direct_case_id is not None:
        return direct_case_id
    replied_message = None
    if source_message.in_reply_to_header is not None and source_message.in_reply_to_header.strip() != "":
        replied_message = session.scalar(
            select(GmailMessage).where(
                GmailMessage.message_id_header == source_message.in_reply_to_header
            )
        )
    if replied_message is None:
        return None
    return session.scalar(
        select(CaseMailLink.case_id)
        .where(CaseMailLink.message_id == replied_message.id)
        .order_by(CaseMailLink.created_at.desc(), CaseMailLink.id.desc())
    )


def create_follow_up_for_sent_message(
    session: DatabaseSession,
    message: GmailMessage,
    now: str | None = None,
) -> FollowUp | None:
    phrase = first_matched_phrase(message)
    if phrase is None:
        return None
    if not has_person_or_unknown_recipient(session, message):
        return None
    existing = session.scalar(
        select(FollowUp).where(FollowUp.source_message_id == message.id)
    )
    if existing is not None:
        return existing
    created_at = now or jst_iso()
    due_on = (parse_iso_datetime(message.received_at) + timedelta(days=7)).date().isoformat()
    follow_up = FollowUp(
        id=new_id("follow_up"),
        source_message_id=message.id,
        thread_id=message.thread_id,
        case_id=source_case_id(session, message),
        status="active",
        due_on=due_on,
        reason=f"{phrase} を含むため",
        matched_phrase=phrase,
        source="rule",
        created_at=created_at,
        updated_at=created_at,
        version=1,
    )
    session.add(follow_up)
    return follow_up


def resolve_follow_ups_for_reply(
    session: DatabaseSession,
    message: GmailMessage,
    now: str | None = None,
) -> int:
    resolved_at = now or jst_iso()
    follow_ups = session.scalars(
        select(FollowUp).where(
            FollowUp.thread_id == message.thread_id,
            FollowUp.status == "active",
            FollowUp.source_message_id != message.id,
        )
    ).all()
    resolved_count = 0
    for follow_up in follow_ups:
        source_message = session.get(GmailMessage, follow_up.source_message_id)
        if source_message is None or message.received_at <= source_message.received_at:
            continue
        follow_up.status = "resolved"
        follow_up.resolved_by_message_id = message.id
        follow_up.resolved_at = resolved_at
        follow_up.updated_at = resolved_at
        follow_up.version += 1
        resolved_count += 1
    return resolved_count
