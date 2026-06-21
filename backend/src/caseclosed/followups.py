from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Case
from caseclosed.db.models import FollowUp
from caseclosed.db.models import GmailMessage
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/follow-ups", tags=["follow-ups"])

FOLLOW_UP_STATUSES = {"active", "resolved", "dismissed"}


class FollowUpDismissPayload(BaseModel):
    reason: str | None = None


class FollowUpSnoozePayload(BaseModel):
    due_on: str = Field(min_length=10, max_length=10)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def validate_due_on(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise json_error(422, "VALIDATION_ERROR", "Invalid follow-up due date.") from error
    return value


def get_follow_up_or_404(session: DatabaseSession, follow_up_id: str) -> FollowUp:
    follow_up = session.get(FollowUp, follow_up_id)
    if follow_up is None:
        raise json_error(404, "NOT_FOUND", "Follow-up not found.")
    return follow_up


def follow_up_data(follow_up: FollowUp, session: DatabaseSession) -> dict[str, object]:
    source_message = session.get(GmailMessage, follow_up.source_message_id)
    resolved_message = (
        session.get(GmailMessage, follow_up.resolved_by_message_id)
        if follow_up.resolved_by_message_id is not None
        else None
    )
    case = session.get(Case, follow_up.case_id) if follow_up.case_id is not None else None
    return {
        "id": follow_up.id,
        "source_message_id": follow_up.source_message_id,
        "thread_id": follow_up.thread_id,
        "case_id": follow_up.case_id,
        "case_name": case.name if case is not None else None,
        "status": follow_up.status,
        "due_on": follow_up.due_on,
        "reason": follow_up.reason,
        "matched_phrase": follow_up.matched_phrase,
        "source": follow_up.source,
        "resolved_by_message_id": follow_up.resolved_by_message_id,
        "resolved_by_subject": resolved_message.subject if resolved_message is not None else None,
        "resolved_at": follow_up.resolved_at,
        "dismissed_at": follow_up.dismissed_at,
        "dismissed_reason": follow_up.dismissed_reason,
        "created_at": follow_up.created_at,
        "updated_at": follow_up.updated_at,
        "version": follow_up.version,
        "message": None
        if source_message is None
        else {
            "id": source_message.id,
            "subject": source_message.subject,
            "from_address": source_message.from_address,
            "from_name": source_message.from_name,
            "received_at": source_message.received_at,
            "snippet": source_message.snippet,
        },
    }


@router.get("")
def list_follow_ups(
    status: str = "active",
    due_on_or_before: str | None = None,
    case_id: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if status != "all" and status not in FOLLOW_UP_STATUSES:
        raise json_error(422, "VALIDATION_ERROR", "Invalid follow-up status.")
    statement = select(FollowUp)
    if status != "all":
        statement = statement.where(FollowUp.status == status)
    if due_on_or_before is not None and due_on_or_before.strip() != "":
        statement = statement.where(FollowUp.due_on <= validate_due_on(due_on_or_before.strip()))
    if case_id is not None and case_id.strip() != "":
        statement = statement.where(FollowUp.case_id == case_id.strip())
    follow_ups = session.scalars(
        statement.order_by(FollowUp.due_on.asc(), FollowUp.created_at.desc(), FollowUp.id)
    ).all()
    return {"ok": True, "data": {"items": [follow_up_data(item, session) for item in follow_ups]}}


@router.post("/{follow_up_id}/dismiss")
def dismiss_follow_up(
    follow_up_id: str,
    payload: FollowUpDismissPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    follow_up = get_follow_up_or_404(session, follow_up_id)
    now = jst_iso()
    follow_up.status = "dismissed"
    follow_up.dismissed_at = now
    follow_up.dismissed_reason = payload.reason
    follow_up.updated_at = now
    follow_up.version += 1
    session.commit()
    return {"ok": True, "data": follow_up_data(follow_up, session)}


@router.post("/{follow_up_id}/resolve")
def resolve_follow_up(
    follow_up_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    follow_up = get_follow_up_or_404(session, follow_up_id)
    now = jst_iso()
    follow_up.status = "resolved"
    follow_up.resolved_at = now
    follow_up.updated_at = now
    follow_up.version += 1
    session.commit()
    return {"ok": True, "data": follow_up_data(follow_up, session)}


@router.patch("/{follow_up_id}/snooze")
def snooze_follow_up(
    follow_up_id: str,
    payload: FollowUpSnoozePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    follow_up = get_follow_up_or_404(session, follow_up_id)
    now = jst_iso()
    follow_up.due_on = validate_due_on(payload.due_on)
    follow_up.updated_at = now
    follow_up.version += 1
    session.commit()
    return {"ok": True, "data": follow_up_data(follow_up, session)}
