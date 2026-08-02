from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from functools import cmp_to_key
from io import BytesIO, StringIO
import re
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy import update
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Case
from caseclosed.db.models import CaseAutoAssignRule
from caseclosed.db.models import CaseContextVersion
from caseclosed.db.models import CaseEvent
from caseclosed.db.models import CalendarEvent
from caseclosed.db.models import CalendarEventLink
from caseclosed.db.models import CaseGenre
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import CaseStakeholder
from caseclosed.db.models import CaseToolIconSetting
from caseclosed.db.models import CaseToolLink
from caseclosed.db.models import ExtensionDefinition
from caseclosed.db.models import Contact
from caseclosed.db.models import ContactEmailAddress
from caseclosed.db.models import FileLink
from caseclosed.db.models import FileSummary
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailThreadSummary
from caseclosed.db.models import MailUserState
from caseclosed.db.models import AuditLog
from caseclosed.db.models import StorageDirectory
from caseclosed.db.models import StorageObject
from caseclosed.db.models import Task
from caseclosed.db.runtime import archive_case_genre_storage_directory
from caseclosed.db.runtime import case_handover_storage_directory_id
from caseclosed.db.runtime import case_storage_directory_id
from caseclosed.db.runtime import ensure_case_genre_storage_directory
from caseclosed.db.runtime import ensure_case_storage_directory
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_email_address
from caseclosed.services.case_mail_stakeholders import sync_all_case_stakeholders_from_linked_mail_senders
from caseclosed.services.llm_provider import FUNCTION_TYPE_CASE_PREFILL_GENERATION
from caseclosed.services.llm_provider import OpenAIProviderError
from caseclosed.services.llm_provider import llm_applied_instruction_rule_ids
from caseclosed.services.llm_provider import with_llm_personalization
from caseclosed.services.llm_provider import build_case_current_situation_provider
from caseclosed.services.llm_provider import build_case_prefill_provider
from caseclosed.storage import delete_storage_object
from caseclosed.storage import ensure_storage_object_llm_digest
from caseclosed.storage import prepare_file_icon_image
from caseclosed.storage import record_storage_operation
from caseclosed.storage import save_storage_object
from caseclosed.storage import storage_object_absolute_path
from caseclosed.storage import storage_object_url
from caseclosed.storage import storage_object_data

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

CASE_PROGRESS_STATUSES = {
    "not_started",
    "in_progress",
    "waiting",
    "blocked",
    "completed",
}
CASE_BALL_STATUSES = {"user", "other", "date_wait", "stalled", "none"}


class CaseCreate(BaseModel):
    name: str
    description: str | None = None
    open_when_date: str | None = None
    open_when_text: str | None = None
    closed_when_text: str | None = None
    progress_status: str = "not_started"
    ball_status: str | None = None
    genre_id: str | None = None
    tags: list[str] | None = None


class CaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    open_when_date: str | None = None
    open_when_text: str | None = None
    closed_when_text: str | None = None
    genre_id: str | None = None
    tags: list[str] | None = None


class CaseGenreCreate(BaseModel):
    title: str
    color_hex: str = Field(default="#ffffff")
    template_extension_id: str | None = None
    template_context: dict[str, object] | None = None


class CaseGenreUpdate(BaseModel):
    title: str | None = None
    color_hex: str | None = None
    template_extension_id: str | None = None
    template_context: dict[str, object] | None = None


class CaseGenreReorder(BaseModel):
    genre_ids: list[str]


class CaseStakeholderCreate(BaseModel):
    contact_id: str
    role: str = ""


class CaseAutoAssignRuleCreate(BaseModel):
    sender_email: str | None = None
    contact_id: str | None = None
    label: str | None = None


class CaseFileLinkCreate(BaseModel):
    directory_id: str | None = None


class CaseStakeholderUpdate(BaseModel):
    role: str | None = None


class CaseStakeholderReorder(BaseModel):
    stakeholder_ids: list[str]


class CaseToolLinkCreate(BaseModel):
    url: str
    icon_label: str | None = None


class CaseToolLinkReorder(BaseModel):
    tool_link_ids: list[str]


class CaseToolIconSettingCreate(BaseModel):
    icon_filename: str | None = None
    icon_content_type: str
    icon_data_base64: str
    match_url: str


class CaseToolIconSettingUpdate(BaseModel):
    icon_filename: str | None = None
    icon_content_type: str | None = None
    icon_data_base64: str | None = None
    match_url: str | None = None


class CasePrefillPayload(BaseModel):
    prompt: str = Field(min_length=1)
    current_fields: dict[str, object] | None = None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_stakeholder_role(role: str | None) -> str:
    normalized = (role or "").strip()
    return normalized


def normalize_genre_color(value: str) -> str:
    color = value.strip().lower()
    if color.startswith("0x"):
        color = color[2:]
    if color.startswith("#"):
        color = color[1:]
    if len(color) == 3:
        color = "".join(character * 2 for character in color)
    if len(color) != 6 or any(character not in "0123456789abcdef" for character in color):
        raise json_error(422, "VALIDATION_ERROR", "Color must be RGB hex.")
    return f"#{color}"


def normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None


def normalized_optional_date(value: str | None) -> str | None:
    stripped = normalized_optional_text(value)
    if stripped is None:
        return None
    try:
        return date.fromisoformat(stripped).isoformat()
    except ValueError as exc:
        raise json_error(422, "VALIDATION_ERROR", "Open when must be a date.") from exc


def is_case_open_by_date(case: Case, today: str | None = None) -> bool:
    if case.open_when_date is None:
        return True
    current_date = today or jst_iso()[:10]
    return case.open_when_date <= current_date


def normalize_case_tags(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_tag in value.replace("\n", ",").split(","):
            tag = raw_tag.strip()
            if tag == "":
                continue
            if len(tag) > 40:
                raise json_error(422, "VALIDATION_ERROR", "Case tag is too long.")
            tag_key = tag.casefold()
            if tag_key not in seen:
                tags.append(tag)
                seen.add(tag_key)
    if len(tags) > 12:
        raise json_error(422, "VALIDATION_ERROR", "Too many case tags.")
    return tags


def normalize_case_prefill_output(output: dict[str, object]) -> dict[str, object]:
    tags_value = output.get("tags")
    tags = normalize_case_tags(tags_value if isinstance(tags_value, list) else None)
    return {
        "name": normalized_optional_text(str(output.get("name") or "")),
        "description": normalized_optional_text(str(output.get("description") or "")),
        "open_when_date": normalized_optional_date(
            str(output.get("open_when_date"))
            if output.get("open_when_date") is not None
            else None
        ),
        "closed_when_text": normalized_optional_text(
            str(output.get("closed_when_text") or "")
        ),
        "tags": tags,
        "reasoning_summary": normalized_optional_text(
            str(output.get("reasoning_summary") or "")
        ),
        "warnings": output.get("warnings") if isinstance(output.get("warnings"), list) else [],
    }


def run_case_prefill(
    session: DatabaseSession,
    input_payload: dict[str, object],
) -> tuple[dict[str, object], str]:
    provider = build_case_prefill_provider()
    provider_input_payload = with_llm_personalization(
        session, FUNCTION_TYPE_CASE_PREFILL_GENERATION, input_payload
    )
    now = jst_iso()
    try:
        provider_response = provider.complete_json(
            function_type=FUNCTION_TYPE_CASE_PREFILL_GENERATION,
            input_payload=provider_input_payload,
        )
        status = "succeeded"
        error_type = None
        error_message = None
        output = provider_response.output
    except OpenAIProviderError as exc:
        provider_response = None
        status = "failed"
        error_type = exc.__class__.__name__
        error_message = str(exc)
        output = {}
    llm_run = LlmRun(
        id=new_id("llm_run"),
        function_type=FUNCTION_TYPE_CASE_PREFILL_GENERATION,
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps(input_payload, ensure_ascii=False),
        input_diagnostic_json=None,
        applied_instruction_rule_ids_json=json.dumps(
            llm_applied_instruction_rule_ids(provider_input_payload),
            ensure_ascii=True,
        ),
        output_json=json.dumps(output, ensure_ascii=False) if output else None,
        output_text_preview=provider_response.output_preview if provider_response else None,
        status=status,
        error_type=error_type,
        error_message=error_message,
        retry_count=0,
        max_retry_count=0,
        prompt_tokens=provider_response.prompt_tokens if provider_response else None,
        completion_tokens=provider_response.completion_tokens if provider_response else None,
        total_tokens=provider_response.total_tokens if provider_response else None,
        estimated_cost=provider_response.estimated_cost if provider_response else None,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    session.add(llm_run)
    session.flush()
    if status != "succeeded":
        raise json_error(502, "LLM_PREFILL_FAILED", error_message or "Case prefill failed.")
    return normalize_case_prefill_output(output), llm_run.id


def case_tags(case: Case) -> list[str]:
    if case.tags_json is None:
        return []
    try:
        parsed = json.loads(case.tags_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(tag) for tag in parsed if str(tag).strip() != ""]


def genre_template_context(genre: CaseGenre) -> dict[str, object] | None:
    if genre.template_context_json is None:
        return None
    try:
        loaded = json.loads(genre.template_context_json)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def validate_genre_template_extension(
    session: DatabaseSession,
    extension_id: str | None,
) -> str | None:
    if extension_id is None:
        return None
    normalized = extension_id.strip()
    if normalized == "":
        return None
    extension = session.get(ExtensionDefinition, normalized)
    if extension is None:
        raise json_error(422, "VALIDATION_ERROR", "Case template Extension not found.")
    return normalized


def genre_data(genre: CaseGenre) -> dict[str, object]:
    return {
        "id": genre.id,
        "title": genre.title,
        "color_hex": genre.color_hex,
        "sort_order": genre.sort_order,
        "template_extension_id": genre.template_extension_id,
        "template_context": genre_template_context(genre),
        "created_at": genre.created_at,
        "updated_at": genre.updated_at,
        "version": genre.version,
    }


OPEN_TASK_STATUSES = {"not_started", "in_progress"}
TASK_PRIORITY_RANKS = {"high": 0, "middle": 1, "low": 2}


def case_task_data(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "case_id": task.case_id,
        "title": task.title,
        "description": task.description,
        "done_when_text": task.done_when_text,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at,
        "estimate_minutes": task.estimate_minutes,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def compare_case_tasks(left: Task, right: Task) -> int:
    left_due = left.due_at or "9999-12-31T23:59:59+09:00"
    right_due = right.due_at or "9999-12-31T23:59:59+09:00"
    if left_due != right_due:
        return -1 if left_due < right_due else 1
    left_priority_rank = TASK_PRIORITY_RANKS.get(left.priority, 1)
    right_priority_rank = TASK_PRIORITY_RANKS.get(right.priority, 1)
    if left_priority_rank != right_priority_rank:
        return left_priority_rank - right_priority_rank
    left_status_rank = 0 if left.status == "in_progress" else 1
    right_status_rank = 0 if right.status == "in_progress" else 1
    if left_status_rank != right_status_rank:
        return left_status_rank - right_status_rank
    if left.updated_at != right.updated_at:
        return -1 if left.updated_at > right.updated_at else 1
    return -1 if left.id < right.id else 1 if left.id > right.id else 0


def task_is_actionable_for_case(task: Task, today: str | None = None) -> bool:
    if task.deleted_at is not None:
        return False
    if task.status not in OPEN_TASK_STATUSES:
        return False
    if task.start_at is None:
        return True
    current_date = today or jst_iso()[:10]
    return task.start_at[:10] <= current_date


def case_open_tasks(session: DatabaseSession, case_id: str) -> list[Task]:
    tasks = session.scalars(
        select(Task)
        .where(Task.case_id == case_id)
        .where(Task.deleted_at.is_(None))
        .where(Task.status.in_(OPEN_TASK_STATUSES))
    ).all()
    today = jst_iso()[:10]
    tasks = [task for task in tasks if task_is_actionable_for_case(task, today)]
    return sorted(tasks, key=cmp_to_key(compare_case_tasks))


def case_not_started_preview_tasks(session: DatabaseSession, case_id: str) -> list[Task]:
    today = jst_iso()[:10]
    tasks = session.scalars(
        select(Task)
        .where(Task.case_id == case_id)
        .where(Task.deleted_at.is_(None))
        .where(Task.status == "not_started")
    ).all()
    tasks = [task for task in tasks if not task_is_actionable_for_case(task, today)]
    return sorted(tasks, key=cmp_to_key(compare_case_tasks))


def case_next_task(session: DatabaseSession, case_id: str) -> Task | None:
    open_tasks = case_open_tasks(session, case_id)
    if open_tasks:
        return open_tasks[0]
    preview_tasks = case_not_started_preview_tasks(session, case_id)
    return preview_tasks[0] if preview_tasks else None


def case_task_counts(session: DatabaseSession, case_id: str) -> tuple[int, int]:
    open_tasks = case_open_tasks(session, case_id)
    now = jst_iso()
    overdue_count = sum(
        1 for task in open_tasks if task.due_at is not None and task.due_at < now
    )
    return len(open_tasks), overdue_count


def case_has_open_mail(session: DatabaseSession, case_id: str) -> bool:
    effective_importance = func.coalesce(
        MailUserState.user_importance,
        MailAutoState.effective_importance,
        "unclassified",
    )
    open_mail_id = session.scalar(
        select(CaseMailLink.message_id)
        .outerjoin(MailUserState, MailUserState.message_id == CaseMailLink.message_id)
        .outerjoin(MailAutoState, MailAutoState.message_id == CaseMailLink.message_id)
        .where(CaseMailLink.case_id == case_id)
        .where(or_(MailUserState.id.is_(None), MailUserState.processed_status != "processed"))
        .where(effective_importance.notin_(["low", "skip"]))
        .limit(1)
    )
    return open_mail_id is not None


@dataclass
class CaseListContext:
    mail_counts: dict[str, int]
    open_tasks: dict[str, list[Task]]
    preview_tasks: dict[str, list[Task]]
    open_mail_case_ids: set[str]
    next_calendar_events: dict[str, dict[str, object]]


def load_case_list_context(
    session: DatabaseSession,
    cases: list[Case],
) -> CaseListContext:
    case_ids = [case.id for case in cases]
    if not case_ids:
        return CaseListContext({}, {}, {}, set(), {})

    today = jst_iso()[:10]
    open_tasks: dict[str, list[Task]] = {}
    preview_tasks: dict[str, list[Task]] = {}
    tasks = session.scalars(
        select(Task)
        .where(Task.case_id.in_(case_ids))
        .where(Task.deleted_at.is_(None))
        .where(Task.status.in_(OPEN_TASK_STATUSES))
    ).all()
    for task in tasks:
        if task_is_actionable_for_case(task, today):
            open_tasks.setdefault(task.case_id, []).append(task)
        elif task.status == "not_started":
            preview_tasks.setdefault(task.case_id, []).append(task)
    for task_group in list(open_tasks.values()) + list(preview_tasks.values()):
        task_group.sort(key=cmp_to_key(compare_case_tasks))

    effective_importance = func.coalesce(
        MailUserState.user_importance,
        MailAutoState.effective_importance,
        "unclassified",
    )
    open_mail_case_ids = set(
        session.scalars(
            select(CaseMailLink.case_id)
            .outerjoin(MailUserState, MailUserState.message_id == CaseMailLink.message_id)
            .outerjoin(MailAutoState, MailAutoState.message_id == CaseMailLink.message_id)
            .where(CaseMailLink.case_id.in_(case_ids))
            .where(or_(MailUserState.id.is_(None), MailUserState.processed_status != "processed"))
            .where(effective_importance.notin_(["low", "skip"]))
            .distinct()
        ).all()
    )

    mail_counts = {
        case_id: int(mail_count)
        for case_id, mail_count in session.execute(
            select(
                CaseMailLink.case_id,
                func.count(func.distinct(GmailMessage.thread_id)),
            )
            .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
            .where(CaseMailLink.case_id.in_(case_ids))
            .group_by(CaseMailLink.case_id)
        )
    }

    now = jst_iso()
    ranked_events = (
        select(
            CalendarEventLink.linked_id.label("case_id"),
            CalendarEventLink.calendar_event_id.label("event_id"),
            func.row_number()
            .over(
                partition_by=CalendarEventLink.linked_id,
                order_by=(
                    CalendarEvent.start_at.asc(),
                    CalendarEvent.summary.asc(),
                    CalendarEvent.id.asc(),
                ),
            )
            .label("event_rank"),
        )
        .join(CalendarEvent, CalendarEvent.id == CalendarEventLink.calendar_event_id)
        .where(CalendarEventLink.linked_type == "case")
        .where(CalendarEventLink.linked_id.in_(case_ids))
        .where(CalendarEvent.sync_status != "missing_from_google")
        .where(CalendarEvent.sync_status != "cancelled")
        .where(
            (CalendarEvent.google_status.is_(None))
            | (CalendarEvent.google_status != "cancelled"),
        )
        .where(CalendarEvent.end_at > now)
        .subquery()
    )
    next_calendar_events = {
        case_id: {
            "id": event.id,
            "title": event.summary,
            "starts_at": event.start_at,
            "ends_at": event.end_at,
            "all_day": bool(event.all_day),
            "location": event.location,
        }
        for case_id, event in session.execute(
            select(ranked_events.c.case_id, CalendarEvent)
            .join(CalendarEvent, CalendarEvent.id == ranked_events.c.event_id)
            .where(ranked_events.c.event_rank == 1)
        )
    }
    return CaseListContext(
        mail_counts=mail_counts,
        open_tasks=open_tasks,
        preview_tasks=preview_tasks,
        open_mail_case_ids=open_mail_case_ids,
        next_calendar_events=next_calendar_events,
    )


def case_effective_ball_status(
    case: Case,
    session: DatabaseSession | None = None,
    list_context: CaseListContext | None = None,
) -> str:
    if case.closed_at is not None or case.archived_at is not None:
        return "none"
    if not is_case_open_by_date(case):
        return "none"
    if list_context is not None:
        if list_context.open_tasks.get(case.id):
            return "user"
        if case.id in list_context.open_mail_case_ids:
            return "user"
        return "none"
    if session is None:
        return case.ball_status
    if case_open_tasks(session, case.id):
        return "user"
    if case_has_open_mail(session, case.id):
        return "user"
    return "none"


def case_data(
    case: Case,
    session: DatabaseSession | None = None,
    list_context: CaseListContext | None = None,
) -> dict[str, object]:
    mail_count = 0
    open_task_count = 0
    overdue_task_count = 0
    next_task: dict[str, object] | None = None
    next_calendar_event: dict[str, object] | None = None
    if list_context is not None:
        mail_count = list_context.mail_counts.get(case.id, 0)
        open_tasks = list_context.open_tasks.get(case.id, [])
        open_task_count = len(open_tasks)
        now = jst_iso()
        overdue_task_count = sum(
            1 for task in open_tasks if task.due_at is not None and task.due_at < now
        )
        next_case_task = (
            open_tasks[0]
            if open_tasks
            else next(iter(list_context.preview_tasks.get(case.id, [])), None)
        )
        if next_case_task is not None:
            next_task = case_task_data(next_case_task)
        next_calendar_event = list_context.next_calendar_events.get(case.id)
    elif session is not None:
        mail_count = session.scalar(
            select(func.count(func.distinct(GmailMessage.thread_id)))
            .select_from(CaseMailLink)
            .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
            .where(CaseMailLink.case_id == case.id)
        ) or 0
        open_tasks = case_open_tasks(session, case.id)
        open_task_count = len(open_tasks)
        now = jst_iso()
        overdue_task_count = sum(
            1 for task in open_tasks if task.due_at is not None and task.due_at < now
        )
        next_case_task = case_next_task(session, case.id)
        if next_case_task is not None:
            next_task = case_task_data(next_case_task)
        next_calendar_event = case_next_calendar_event_data(session, case.id)
    return {
        "id": case.id,
        "genre_id": case.genre_id,
        "name": case.name,
        "description": case.description,
        "open_when_date": case.open_when_date,
        "open_when_text": case.open_when_text,
        "closed_when_text": case.closed_when_text,
        "progress_status": case.progress_status,
        "ball_status": case_effective_ball_status(case, session, list_context),
        "closed_at": case.closed_at,
        "archived_at": case.archived_at,
        "is_system_case": bool(case.is_system_case),
        "system_case_key": case.system_case_key,
        "tags": case_tags(case),
        "mail_count": mail_count,
        "open_task_count": open_task_count,
        "overdue_task_count": overdue_task_count,
        "file_count": 0,
        "storage_directory_id": case_storage_directory_id(case.id),
        "handover_storage_directory_id": case_handover_storage_directory_id(case.id),
        "next_task": next_task,
        "next_calendar_event": next_calendar_event,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "version": case.version,
    }


def case_next_calendar_event_data(
    session: DatabaseSession,
    case_id: str,
) -> dict[str, object] | None:
    now = jst_iso()
    event = session.scalar(
        select(CalendarEvent)
        .join(CalendarEventLink, CalendarEventLink.calendar_event_id == CalendarEvent.id)
        .where(CalendarEventLink.linked_type == "case")
        .where(CalendarEventLink.linked_id == case_id)
        .where(CalendarEvent.sync_status != "missing_from_google")
        .where(CalendarEvent.sync_status != "cancelled")
        .where(
            (CalendarEvent.google_status.is_(None))
            | (CalendarEvent.google_status != "cancelled"),
        )
        .where(CalendarEvent.end_at > now)
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.summary.asc())
        .limit(1)
    )
    if event is None:
        return None
    return {
        "id": event.id,
        "title": event.summary,
        "starts_at": event.start_at,
        "ends_at": event.end_at,
        "all_day": bool(event.all_day),
        "location": event.location,
    }


def case_calendar_event_items(
    session: DatabaseSession,
    case_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, object]]:
    events = session.scalars(
        select(CalendarEvent)
        .join(CalendarEventLink, CalendarEventLink.calendar_event_id == CalendarEvent.id)
        .where(CalendarEventLink.linked_type == "case")
        .where(CalendarEventLink.linked_id == case_id)
        .where(CalendarEvent.sync_status != "cancelled")
        .where(
            (CalendarEvent.google_status.is_(None))
            | (CalendarEvent.google_status != "cancelled"),
        )
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.summary.asc())
        .limit(limit)
    ).all()
    return [
        {
            "id": event.id,
            "title": event.summary,
            "starts_at": event.start_at,
            "ends_at": event.end_at,
            "all_day": bool(event.all_day),
            "location": event.location,
        }
        for event in events
    ]


def case_mail_link_data(
    link: CaseMailLink,
    message: GmailMessage,
    user_state: MailUserState | None,
    auto_state: MailAutoState | None,
    summary: MailSummary | None,
) -> dict[str, object]:
    effective_importance = (
        user_state.user_importance
        if user_state is not None and user_state.user_importance is not None
        else auto_state.effective_importance if auto_state is not None else "unclassified"
    )
    return {
        "id": link.id,
        "case_id": link.case_id,
        "message_id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "thread_id": message.thread_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "from_name": message.from_name,
        "processed_status": (
            user_state.processed_status if user_state is not None else "unprocessed"
        ),
        "read_status": user_state.read_status if user_state is not None else "read",
        "effective_importance": effective_importance,
        "summary": summary.summary_text if summary is not None else message.snippet,
        "mail_url": f"/mail/{message.id}",
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "version": link.version,
    }


def case_auto_assign_rule_data(
    session: DatabaseSession,
    rule: CaseAutoAssignRule,
    case: Case | None = None,
) -> dict[str, object]:
    case = case or session.get(Case, rule.case_id)
    contact = (
        session.get(Contact, rule.rule_value)
        if rule.rule_type == "sender_contact"
        else None
    )
    return {
        "id": rule.id,
        "case_id": rule.case_id,
        "case_name": case.name if case is not None else rule.case_id,
        "case_progress_status": case.progress_status if case is not None else None,
        "case_archived_at": case.archived_at if case is not None else None,
        "rule_type": rule.rule_type,
        "rule_value": rule.rule_value,
        "contact_id": contact.id if contact is not None else None,
        "contact_display_name": contact.display_name if contact is not None else None,
        "display_value": (
            contact.display_name
            if contact is not None
            else rule.rule_value
        ),
        "label": rule.label,
        "is_enabled": bool(rule.is_enabled),
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
        "version": rule.version,
    }


def case_auto_assign_rule_items(
    session: DatabaseSession,
    case_id: str,
) -> list[dict[str, object]]:
    rules = session.scalars(
        select(CaseAutoAssignRule)
        .where(CaseAutoAssignRule.case_id == case_id)
        .order_by(CaseAutoAssignRule.created_at.desc(), CaseAutoAssignRule.id.desc())
    ).all()
    return [case_auto_assign_rule_data(session, rule) for rule in rules]


def all_case_auto_assign_rule_items(session: DatabaseSession) -> list[dict[str, object]]:
    rows = session.execute(
        select(CaseAutoAssignRule, Case)
        .join(Case, Case.id == CaseAutoAssignRule.case_id)
        .order_by(
            Case.name.asc(),
            CaseAutoAssignRule.created_at.desc(),
            CaseAutoAssignRule.id.desc(),
        )
    ).all()
    return [case_auto_assign_rule_data(session, rule, case) for rule, case in rows]


def case_mail_link_items(
    session: DatabaseSession,
    case_id: str,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(CaseMailLink, GmailMessage, MailUserState, MailAutoState, MailSummary)
        .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
        .outerjoin(MailUserState, MailUserState.message_id == GmailMessage.id)
        .outerjoin(MailAutoState, MailAutoState.message_id == GmailMessage.id)
        .outerjoin(MailSummary, MailSummary.message_id == GmailMessage.id)
        .where(CaseMailLink.case_id == case_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    latest_rows_by_thread: dict[
        str,
        tuple[CaseMailLink, GmailMessage, MailUserState | None, MailAutoState | None, MailSummary | None],
    ] = {}
    for link, message, user_state, auto_state, summary in rows:
        if message.thread_id in latest_rows_by_thread:
            continue
        latest_rows_by_thread[message.thread_id] = (
            link,
            message,
            user_state,
            auto_state,
            summary,
        )
    return [
        case_mail_link_data(link, message, user_state, auto_state, summary)
        for link, message, user_state, auto_state, summary in latest_rows_by_thread.values()
    ]


def case_event_data(event: CaseEvent) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if event.metadata_json is not None:
        try:
            parsed_metadata = json.loads(event.metadata_json)
        except json.JSONDecodeError:
            parsed_metadata = {}
        if isinstance(parsed_metadata, dict):
            metadata = parsed_metadata
    return {
        "id": event.id,
        "case_id": event.case_id,
        "event_type": event.event_type,
        "title": event.title,
        "summary": event.summary,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "occurred_at": event.occurred_at,
        "created_at": event.created_at,
        "metadata": metadata,
    }


def case_context_version_data(context: CaseContextVersion | None) -> dict[str, object] | None:
    if context is None:
        return None
    return {
        "id": context.id,
        "case_id": context.case_id,
        "version_no": context.version_no,
        "context_markdown": context.context_markdown,
        "source_event_until_at": context.source_event_until_at,
        "llm_run_id": context.llm_run_id,
        "created_at": context.created_at,
        "created_by": context.created_by,
    }


def latest_case_context_version(
    session: DatabaseSession,
    case_id: str,
) -> CaseContextVersion | None:
    return session.scalar(
        select(CaseContextVersion)
        .where(CaseContextVersion.case_id == case_id)
        .order_by(CaseContextVersion.version_no.desc(), CaseContextVersion.created_at.desc())
        .limit(1)
    )


def next_case_context_version_no(session: DatabaseSession, case_id: str) -> int:
    return (
        session.scalar(
            select(func.max(CaseContextVersion.version_no)).where(
                CaseContextVersion.case_id == case_id
            )
        )
        or 0
    ) + 1


def case_task_status_context(_session: DatabaseSession, _case_id: str) -> dict[str, object]:
    return {
        "connected": False,
        "open_count": 0,
        "completed_count": 0,
        "overdue_count": 0,
        "items": [],
        "note": "Task module is not connected yet.",
    }


def safe_json_list(value: str | None) -> list[object]:
    if value is None:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def case_calendar_status_context(_session: DatabaseSession, _case_id: str) -> dict[str, object]:
    return {
        "connected": False,
        "items": [],
        "note": "Calendar module is not connected yet.",
    }


def case_storage_directory_ids(session: DatabaseSession, case: Case) -> set[str]:
    root_id = case_storage_directory_id(case.id)
    directory_ids = {root_id}
    expanded = True
    while expanded:
        expanded = False
        child_ids = session.scalars(
            select(StorageDirectory.id).where(StorageDirectory.parent_id.in_(directory_ids))
        ).all()
        for child_id in child_ids:
            if child_id not in directory_ids:
                directory_ids.add(child_id)
                expanded = True
    return directory_ids


def normalize_case_file_link_directory_id(
    session: DatabaseSession,
    case: Case,
    directory_id: str | None,
) -> str:
    target_directory_id = directory_id or case_storage_directory_id(case.id)
    if target_directory_id not in case_storage_directory_ids(session, case):
        raise json_error(400, "INVALID_DIRECTORY", "Directory is not in this Case.")
    return target_directory_id


def case_linked_storage_object_ids(session: DatabaseSession, case_id: str) -> set[str]:
    return set(
        session.scalars(
            select(FileLink.storage_object_id)
            .where(FileLink.linked_type == "case")
            .where(FileLink.linked_id == case_id)
            .where(FileLink.status == "active")
        ).all()
    )


def case_storage_objects(
    session: DatabaseSession,
    case: Case,
    *,
    limit: int = 200,
) -> list[StorageObject]:
    safe_limit = max(1, min(limit, 500))
    directory_ids = case_storage_directory_ids(session, case)
    linked_object_ids = case_linked_storage_object_ids(session, case.id)
    conditions = []
    if directory_ids:
        conditions.append(StorageObject.directory_id.in_(directory_ids))
    if linked_object_ids:
        conditions.append(StorageObject.id.in_(linked_object_ids))
    if not conditions:
        return []
    statement = (
        select(StorageObject)
        .where(StorageObject.status == "active")
        .where(StorageObject.scope == "managed")
        .where(or_(*conditions))
        .order_by(StorageObject.file_updated_at.desc(), StorageObject.id.desc())
        .limit(safe_limit)
    )
    return session.scalars(statement).all()


def case_root_visible_storage_objects(
    session: DatabaseSession,
    case: Case,
    *,
    limit: int = 200,
) -> list[StorageObject]:
    safe_limit = max(1, min(limit, 500))
    root_id = case_storage_directory_id(case.id)
    directory_ids = case_storage_directory_ids(session, case)
    linked_root_object_ids = set(
        session.scalars(
            select(FileLink.storage_object_id)
            .where(FileLink.linked_type == "case")
            .where(FileLink.linked_id == case.id)
            .where(FileLink.status == "active")
            .where((FileLink.directory_id.is_(None)) | (FileLink.directory_id == root_id))
        ).all()
    )
    conditions = [StorageObject.directory_id == root_id]
    if linked_root_object_ids:
        conditions.append(
            StorageObject.id.in_(linked_root_object_ids)
            & (
                StorageObject.directory_id.is_(None)
                | StorageObject.directory_id.not_in(directory_ids)
            )
        )
    statement = (
        select(StorageObject)
        .where(StorageObject.status == "active")
        .where(StorageObject.scope == "managed")
        .where(or_(*conditions))
        .order_by(StorageObject.file_updated_at.desc(), StorageObject.id.desc())
        .limit(safe_limit)
    )
    return session.scalars(statement).all()


def case_file_summary_contexts(
    session: DatabaseSession,
    case: Case,
) -> list[dict[str, object]]:
    storage_object_ids = [storage_object.id for storage_object in case_storage_objects(session, case, limit=500)]
    if not storage_object_ids:
        return []
    rows = session.execute(
        select(StorageObject, FileSummary)
        .join(FileSummary, FileSummary.storage_object_id == StorageObject.id)
        .where(StorageObject.id.in_(storage_object_ids))
        .where(StorageObject.status == "active")
        .where(StorageObject.scope == "managed")
        .where(FileSummary.summary_type == "llm_digest")
        .order_by(StorageObject.file_updated_at.desc(), FileSummary.updated_at.desc())
        .limit(20)
    ).all()
    contexts: list[dict[str, object]] = []
    seen_objects: set[str] = set()
    for storage_object, summary in rows:
        if storage_object.id in seen_objects:
            continue
        seen_objects.add(storage_object.id)
        contexts.append(
            {
                "storage_object_id": storage_object.id,
                "storage_object_version_id": summary.storage_object_version_id,
                "filename": storage_object.original_filename,
                "content_type": storage_object.content_type,
                "byte_size": storage_object.byte_size,
                "file_updated_at": storage_object.file_updated_at,
                "summary_created_at": summary.created_at,
                "summary_updated_at": summary.updated_at,
                "summary_source_sha256_hex": summary.source_sha256_hex,
                "current_sha256_hex": storage_object.sha256_hex,
                "summary_is_current": summary.source_sha256_hex == storage_object.sha256_hex,
                "file_description": summary.file_description,
                "summary_points": [
                    str(point)
                    for point in safe_json_list(summary.summary_points_json)[:5]
                    if str(point).strip()
                ],
                "llm_digest": summary.llm_digest,
            }
        )
    return contexts


def case_mail_thread_contexts(
    session: DatabaseSession,
    case_id: str,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(CaseMailLink, GmailMessage, MailThreadSummary, MailSummary)
        .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
        .outerjoin(MailThreadSummary, MailThreadSummary.thread_id == GmailMessage.thread_id)
        .outerjoin(MailSummary, MailSummary.message_id == GmailMessage.id)
        .where(CaseMailLink.case_id == case_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    contexts_by_thread: dict[str, dict[str, object]] = {}
    for _link, message, thread_summary, mail_summary in rows:
        if message.thread_id in contexts_by_thread:
            continue
        summary_text = (
            thread_summary.summary_text
            if thread_summary is not None
            else mail_summary.summary_text if mail_summary is not None else message.snippet
        )
        contexts_by_thread[message.thread_id] = {
            "thread_id": message.thread_id,
            "gmail_thread_id": message.gmail_thread_id,
            "representative_message_id": message.id,
            "received_at": message.received_at,
            "subject": message.subject,
            "from_address": message.from_address,
            "from_name": message.from_name,
            "summary": summary_text,
            "summary_source": "thread_summary"
            if thread_summary is not None
            else "mail_summary" if mail_summary is not None else "snippet",
        }
    return list(contexts_by_thread.values())


def case_current_situation_input_payload(
    session: DatabaseSession,
    case: Case,
) -> dict[str, object]:
    return {
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "open_when_text": case.open_when_text,
            "closed_when_text": case.closed_when_text,
            "progress_status": case.progress_status,
            "ball_status": case.ball_status,
            "tags": case_tags(case),
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        },
        "mail_threads": case_mail_thread_contexts(session, case.id),
        "task_status": case_task_status_context(session, case.id),
        "calendar_status": case_calendar_status_context(session, case.id),
        "files": case_file_summary_contexts(session, case),
    }


def case_current_situation_markdown(output: dict[str, object]) -> str:
    lines = [str(output.get("summary") or "").strip()]
    key_points = output.get("key_points")
    if isinstance(key_points, list) and key_points:
        lines.append("")
        lines.append("Key points:")
        lines.extend(f"- {str(point).strip()}" for point in key_points if str(point).strip())
    risks = output.get("risks")
    if isinstance(risks, list) and risks:
        lines.append("")
        lines.append("Risks / open questions:")
        lines.extend(f"- {str(risk).strip()}" for risk in risks if str(risk).strip())
    next_focus = str(output.get("next_focus") or "").strip()
    if next_focus:
        lines.append("")
        lines.append(f"Next focus: {next_focus}")
    return "\n".join(line for line in lines if line is not None).strip()


def is_mail_delivery_daemon(message: GmailMessage) -> bool:
    sender = (message.from_address or "").strip().lower()
    sender_name = (message.from_name or "").strip().lower()
    subject = (message.subject or "").strip().lower()
    sender_local = sender.split("@", maxsplit=1)[0].replace("-", "").replace("_", "")
    normalized_name = sender_name.replace("-", "").replace("_", "").replace(" ", "")
    return (
        sender_local in {"mailerdaemon", "postmaster"}
        or "mailerdaemon" in normalized_name
        or "mail delivery subsystem" in sender_name
        or "mail delivery system" in sender_name
        or subject.startswith("delivery status notification")
        or subject.startswith("undeliverable:")
        or subject.startswith("returned mail:")
        or subject.startswith("mail delivery failed")
        or subject.startswith("failure notice")
    )


def case_handover_mail_rows(
    session: DatabaseSession,
    case_id: str,
) -> list[tuple[GmailMessage, MailSummary | None]]:
    return [
        (message, summary)
        for message, summary in session.execute(
            select(GmailMessage, MailSummary)
            .join(CaseMailLink, CaseMailLink.message_id == GmailMessage.id)
            .outerjoin(MailSummary, MailSummary.message_id == GmailMessage.id)
            .where(CaseMailLink.case_id == case_id)
            .order_by(GmailMessage.received_at.asc(), GmailMessage.id.asc())
        ).all()
        if not is_mail_delivery_daemon(message)
    ]


def case_handover_artifact_data(
    session: DatabaseSession,
    case: Case,
    *,
    source_type: str = "case_handover_report",
) -> dict[str, object] | None:
    storage_object = session.scalar(
        select(StorageObject)
        .where(StorageObject.directory_id == case_handover_storage_directory_id(case.id))
        .where(StorageObject.scope == "managed")
        .where(StorageObject.status == "active")
        .where(StorageObject.source_type == source_type)
        .order_by(StorageObject.created_at.desc(), StorageObject.id.desc())
        .limit(1)
    )
    return storage_object_data(storage_object, session) if storage_object is not None else None


def safe_mail_addresses(value: str | None) -> list[str]:
    if value is None:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def case_handover_eml_bytes(message: GmailMessage) -> bytes:
    eml = EmailMessage()
    eml["Subject"] = message.subject or "(no subject)"
    eml["From"] = (
        f"{message.from_name} <{message.from_address}>"
        if (message.from_name or "").strip()
        else message.from_address
    )
    to_addresses = safe_mail_addresses(message.to_addresses_json)
    cc_addresses = safe_mail_addresses(message.cc_addresses_json)
    if to_addresses:
        eml["To"] = ", ".join(to_addresses)
    if cc_addresses:
        eml["Cc"] = ", ".join(cc_addresses)
    if message.message_id_header:
        eml["Message-ID"] = message.message_id_header
    if message.in_reply_to_header:
        eml["In-Reply-To"] = message.in_reply_to_header
    if message.references_header:
        eml["References"] = message.references_header
    eml["X-CaseClosed-Received-At"] = message.received_at
    eml["X-CaseClosed-Gmail-Message-Id"] = message.gmail_message_id
    eml.set_content(message.body_text or message.snippet or "")
    if (message.body_html or "").strip():
        eml.add_alternative(message.body_html or "", subtype="html")
    return eml.as_bytes()


def handover_filename_part(value: str | None, fallback: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "_", (value or "").strip()).strip("._")
    return (normalized or fallback)[:80]


def archive_visible_filename(value: str | None, fallback: str) -> str:
    filename = (value or fallback).strip().replace("/", "_").replace("\\", "_")
    return filename.replace("\x00", "") or fallback


def unique_archive_path(folder: str, filename: str, used_paths: set[str]) -> str:
    base_path = f"{folder}/{filename}"
    if base_path not in used_paths:
        used_paths.add(base_path)
        return base_path
    stem, separator, suffix = filename.rpartition(".")
    if separator == "" or stem == "":
        stem, suffix = filename, ""
    else:
        suffix = f".{suffix}"
    duplicate_no = 2
    while True:
        candidate = f"{folder}/{stem} ({duplicate_no}){suffix}"
        if candidate not in used_paths:
            used_paths.add(candidate)
            return candidate
        duplicate_no += 1


def case_handover_markdown(
    case: Case,
    output: dict[str, object],
    mail_rows: list[tuple[GmailMessage, MailSummary | None]],
    source_files: list[StorageObject],
    generated_at: str,
) -> str:
    lines = [
        f"# 引継ぎ資料: {case.name}",
        "",
        f"生成日時: {generated_at}",
        f"Case開始: {case.created_at}",
        f"Case完了: {case.closed_at or ''}",
        "",
        "## この仕事について",
        "",
        str(output.get("summary") or case.description or "").strip(),
        "",
        "## 仕事の内容と大まかな流れ",
        "",
    ]
    key_points = output.get("key_points")
    if isinstance(key_points, list) and key_points:
        lines.extend(f"- {str(item).strip()}" for item in key_points if str(item).strip())
    else:
        lines.append("- Caseの概要と保存資料を確認してください。")
    lines.extend(["", "## 引継ぎ時の注意", ""])
    risks = output.get("risks")
    if isinstance(risks, list) and risks:
        lines.extend(f"- {str(item).strip()}" for item in risks if str(item).strip())
    else:
        lines.append("- 特記事項はありません。")
    lines.extend(["", "## 参考資料", ""])
    if source_files:
        lines.extend(f"- {item.original_filename or item.id}" for item in source_files)
    else:
        lines.append("- 追加資料はありません。")
    lines.extend([
        "",
        "## 原本の確認方法",
        "",
        f"関連メール {len(mail_rows)} 件はZIP内の `mail/` に保存しています。",
        "メールの日付・件名・差出人との対応は `mail/mail-index.csv` で確認できます。",
    ])
    return "\n".join(lines).strip() + "\n"


def case_handover_zip_bytes(
    session: DatabaseSession,
    *,
    report_bytes: bytes,
    mail_rows: list[tuple[GmailMessage, MailSummary | None]],
    mail_exports: dict[str, StorageObject],
    source_files: list[StorageObject],
    historical_reports: list[StorageObject],
) -> bytes:
    output = BytesIO()
    used_paths = {"handover.md", "mail/mail-index.csv"}
    mail_index = StringIO(newline="")
    index_writer = csv.writer(mail_index)
    index_writer.writerow(["date", "subject", "from", "eml_file"])
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("handover.md", report_bytes)
        for storage_object in source_files:
            filename = archive_visible_filename(storage_object.original_filename, storage_object.id)
            archive.write(
                storage_object_absolute_path(storage_object, session),
                arcname=unique_archive_path("files", filename, used_paths),
            )
        for message, _summary in mail_rows:
            storage_object = mail_exports.get(message.id)
            if storage_object is None:
                continue
            filename = archive_visible_filename(storage_object.original_filename, f"{message.gmail_message_id}.eml")
            archive_path = unique_archive_path("mail", filename, used_paths)
            archive.write(storage_object_absolute_path(storage_object, session), arcname=archive_path)
            index_writer.writerow([
                message.received_at,
                message.subject or "",
                message.from_name or message.from_address,
                archive_path.removeprefix("mail/"),
            ])
        archive.writestr("mail/mail-index.csv", mail_index.getvalue().encode("utf-8-sig"))
        for storage_object in historical_reports:
            filename = archive_visible_filename(storage_object.original_filename, storage_object.id)
            archive.write(
                storage_object_absolute_path(storage_object, session),
                arcname=unique_archive_path("history", filename, used_paths),
            )
    return output.getvalue()


def add_case_event(
    session: DatabaseSession,
    case: Case,
    *,
    event_type: str,
    title: str,
    now: str,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        CaseEvent(
            id=new_id("case_event"),
            case_id=case.id,
            event_type=event_type,
            title=title,
            summary=None,
            source_type="user",
            source_id=None,
            occurred_at=now,
            created_at=now,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        )
    )


def latest_case_state_event(session: DatabaseSession, case_id: str) -> CaseEvent | None:
    return session.scalar(
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .where(CaseEvent.event_type.in_(("case_closed", "case_archived")))
        .order_by(CaseEvent.occurred_at.desc(), CaseEvent.created_at.desc())
    )


def restore_case_open_state(session: DatabaseSession, case: Case) -> None:
    event = latest_case_state_event(session, case.id)
    metadata: dict[str, object] = {}
    if event is not None and event.metadata_json is not None:
        try:
            parsed_metadata = json.loads(event.metadata_json)
        except json.JSONDecodeError:
            parsed_metadata = {}
        if isinstance(parsed_metadata, dict):
            metadata = parsed_metadata

    previous_progress = metadata.get("previous_progress_status")
    previous_ball = metadata.get("previous_ball_status")

    case.progress_status = (
        previous_progress
        if isinstance(previous_progress, str)
        and previous_progress in CASE_PROGRESS_STATUSES
        and previous_progress != "completed"
        else "in_progress"
    )
    case.ball_status = (
        previous_ball
        if isinstance(previous_ball, str) and previous_ball in CASE_BALL_STATUSES
        else "none"
    )


def primary_contact_email(
    session: DatabaseSession,
    contact_id: str,
) -> str | None:
    primary = session.scalar(
        select(ContactEmailAddress.email_address)
        .where(ContactEmailAddress.contact_id == contact_id)
        .where(ContactEmailAddress.status == "active")
        .where(ContactEmailAddress.is_primary == 1)
        .order_by(ContactEmailAddress.email_address.asc())
        .limit(1)
    )
    if primary is not None:
        return primary
    return session.scalar(
        select(ContactEmailAddress.email_address)
        .where(ContactEmailAddress.contact_id == contact_id)
        .where(ContactEmailAddress.status == "active")
        .order_by(ContactEmailAddress.email_address.asc())
        .limit(1)
    )


def case_stakeholder_data(
    stakeholder: CaseStakeholder,
    contact: Contact,
    session: DatabaseSession,
) -> dict[str, object]:
    return {
        "id": stakeholder.id,
        "case_id": stakeholder.case_id,
        "contact_id": stakeholder.contact_id,
        "contact_display_name": contact.display_name,
        "contact_avatar_url": contact.avatar_url,
        "contact_primary_email": primary_contact_email(session, contact.id),
        "role": stakeholder.role,
        "sort_order": stakeholder.sort_order,
        "created_at": stakeholder.created_at,
        "updated_at": stakeholder.updated_at,
        "version": stakeholder.version,
    }


def stakeholder_items(session: DatabaseSession, case_id: str) -> list[dict[str, object]]:
    rows = session.execute(
        select(CaseStakeholder, Contact)
        .join(Contact, Contact.id == CaseStakeholder.contact_id)
        .where(CaseStakeholder.case_id == case_id)
        .where(Contact.deleted_at.is_(None))
        .order_by(CaseStakeholder.sort_order.asc(), CaseStakeholder.created_at.asc())
    ).all()
    return [case_stakeholder_data(stakeholder, contact, session) for stakeholder, contact in rows]


def tool_icon_label_from_url(url: str) -> str:
    label = (
        url.removeprefix("https://")
        .removeprefix("http://")
        .removeprefix("www.")
        .strip()
        .upper()
    )
    letters = [character for character in label if character.isalnum()]
    return "".join(letters[:2]) or "TL"


def normalize_case_tool_icon_label(value: str | None, *, url: str) -> str:
    text = (value or "").strip()
    if text == "":
        return tool_icon_label_from_url(url)
    characters = list(text)
    is_ascii = all(ord(character) < 128 for character in characters)
    if is_ascii:
        if len(characters) > 2:
            raise json_error(422, "VALIDATION_ERROR", "Icon label must be at most 2 half-width characters.")
        return text.upper()
    if len(characters) != 1:
        raise json_error(422, "VALIDATION_ERROR", "Icon label must be 1 full-width character.")
    return text


def normalize_case_tool_icon_match_url(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "":
        raise json_error(422, "VALIDATION_ERROR", "Match URL is required.")
    if len(normalized) > 512:
        raise json_error(422, "VALIDATION_ERROR", "Match URL is too long.")
    return normalized


def case_tool_icon_url(setting: CaseToolIconSetting | None) -> str | None:
    if setting is None:
        return None
    if setting.storage_object_id is not None:
        return storage_object_url(setting.storage_object_id)
    return setting.icon_data_url


def case_tool_icon_setting_data(setting: CaseToolIconSetting) -> dict[str, object]:
    return {
        "id": setting.id,
        "storage_object_id": setting.storage_object_id,
        "icon_filename": setting.icon_filename,
        "icon_content_type": setting.icon_content_type,
        "icon_url": case_tool_icon_url(setting),
        "icon_data_url": setting.icon_data_url,
        "match_url": setting.match_url,
        "created_at": setting.created_at,
        "updated_at": setting.updated_at,
        "version": setting.version,
    }


def case_tool_icon_for_url(
    session: DatabaseSession,
    url: str,
) -> CaseToolIconSetting | None:
    normalized_url = url.strip().lower()
    if normalized_url == "":
        return None
    settings = session.scalars(
        select(CaseToolIconSetting).order_by(
            CaseToolIconSetting.created_at.asc(),
            CaseToolIconSetting.id.asc(),
        )
    ).all()
    matches = [
        setting
        for setting in settings
        if setting.match_url != "" and setting.match_url in normalized_url
    ]
    if len(matches) == 0:
        return None
    return max(matches, key=lambda setting: len(setting.match_url))


def save_case_tool_icon_storage_object(
    session: DatabaseSession,
    *,
    filename: str | None,
    content_type: str,
    data_base64: str,
    now: str,
) -> StorageObject:
    resized_content_type, resized_data = prepare_file_icon_image(
        content_type=content_type,
        data_base64=data_base64,
    )
    return save_storage_object(
        session,
        scope="case-tool-icons",
        filename=filename,
        content_type=resized_content_type,
        data=resized_data,
        now=now,
    )


def delete_case_tool_icon_storage_object_if_unused(
    session: DatabaseSession,
    *,
    storage_object_id: str | None,
    setting_id: str | None = None,
    now: str,
) -> None:
    if storage_object_id is None:
        return
    statement = select(func.count(CaseToolIconSetting.id)).where(
        CaseToolIconSetting.storage_object_id == storage_object_id
    )
    if setting_id is not None:
        statement = statement.where(CaseToolIconSetting.id != setting_id)
    if session.scalar(statement) != 0:
        return
    storage_object = session.get(StorageObject, storage_object_id)
    if (
        storage_object is None
        or storage_object.status != "active"
        or storage_object.scope != "case-tool-icons"
    ):
        return
    delete_storage_object(storage_object, session=session, now=now)


def case_tool_link_data(session: DatabaseSession, tool_link: CaseToolLink) -> dict[str, object]:
    icon_setting = case_tool_icon_for_url(session, tool_link.url)
    return {
        "id": tool_link.id,
        "case_id": tool_link.case_id,
        "url": tool_link.url,
        "icon_label": tool_link.icon_label,
        "icon_setting_id": icon_setting.id if icon_setting is not None else None,
        "icon_url": case_tool_icon_url(icon_setting),
        "sort_order": tool_link.sort_order,
        "created_at": tool_link.created_at,
        "updated_at": tool_link.updated_at,
        "version": tool_link.version,
    }


def tool_link_items(session: DatabaseSession, case_id: str) -> list[dict[str, object]]:
    tool_links = session.scalars(
        select(CaseToolLink)
        .where(CaseToolLink.case_id == case_id)
        .order_by(CaseToolLink.sort_order.asc(), CaseToolLink.created_at.asc())
    ).all()
    return [case_tool_link_data(session, tool_link) for tool_link in tool_links]


def ensure_case_exists(session: DatabaseSession, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")
    return case


@router.get("")
def list_cases(
    status: str = Query(default="user_ball"),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = select(Case)
    should_filter_open_date = False
    should_filter_ball: str | None = None
    if status == "user_ball":
        statement = (
            statement.where(Case.closed_at.is_(None))
            .where(Case.archived_at.is_(None))
        )
        should_filter_open_date = True
        should_filter_ball = "user"
    elif status == "waiting":
        statement = (
            statement.where(Case.closed_at.is_(None))
            .where(Case.archived_at.is_(None))
        )
        should_filter_open_date = True
        should_filter_ball = "waiting"
    elif status == "completed":
        statement = statement.where(
            Case.closed_at.is_not(None)
        ).where(
            Case.archived_at.is_(None)
        )
    elif status == "not_started":
        statement = statement.where(Case.closed_at.is_(None)).where(
            Case.archived_at.is_(None)
        )
    elif status == "open":
        statement = statement.where(Case.closed_at.is_(None)).where(
            Case.archived_at.is_(None)
        )
        should_filter_open_date = True
    elif status == "closed":
        statement = statement.where(Case.closed_at.is_not(None)).where(
            Case.archived_at.is_(None)
        )
    elif status == "archived":
        statement = statement.where(Case.archived_at.is_not(None))
    elif status != "all":
        raise json_error(422, "VALIDATION_ERROR", "Unsupported case status filter.")

    cases = session.scalars(
        statement.order_by(
            Case.is_system_case.desc(),
            Case.updated_at.desc(),
            Case.created_at.desc(),
        )
    ).all()
    today = jst_iso()[:10]
    if should_filter_open_date:
        cases = [case for case in cases if is_case_open_by_date(case, today)]
    if status == "not_started":
        cases = [case for case in cases if not is_case_open_by_date(case, today)]
    list_context = load_case_list_context(session, cases)
    if should_filter_ball == "user":
        cases = [
            case
            for case in cases
            if case_effective_ball_status(case, list_context=list_context) == "user"
        ]
    elif should_filter_ball == "waiting":
        cases = [
            case
            for case in cases
            if case_effective_ball_status(case, list_context=list_context) != "user"
        ]
    return {
        "ok": True,
        "data": {
            "items": [
                case_data(case, list_context=list_context)
                for case in cases
            ]
        },
    }


@router.post("/prefill")
def prefill_case(
    payload: CasePrefillPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    input_payload: dict[str, object] = {
        "prompt": payload.prompt.strip(),
        "current_fields": payload.current_fields or {},
    }
    prefill, llm_run_id = run_case_prefill(session, input_payload)
    session.commit()
    return {
        "ok": True,
        "data": {
            "prefill": prefill,
            "llm_run_id": llm_run_id,
        },
    }


@router.get("/genres")
def list_case_genres(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    genres = session.scalars(
        select(CaseGenre).order_by(
            CaseGenre.sort_order.asc(),
            CaseGenre.title.asc(),
            CaseGenre.created_at.asc(),
        )
    ).all()
    return {"ok": True, "data": {"items": [genre_data(genre) for genre in genres]}}


@router.post("/genres")
def create_case_genre(
    payload: CaseGenreCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    title = payload.title.strip()
    if title == "":
        raise json_error(422, "VALIDATION_ERROR", "Case genre title is required.")
    existing = session.scalar(select(CaseGenre).where(CaseGenre.title == title))
    if existing is not None:
        raise json_error(409, "CONFLICT", "Case genre already exists.")

    now = jst_iso()
    max_sort_order = session.scalar(
        select(CaseGenre.sort_order).order_by(CaseGenre.sort_order.desc())
    )
    template_extension_id = validate_genre_template_extension(session, payload.template_extension_id)
    genre = CaseGenre(
        id=new_id("case_genre"),
        title=title,
        color_hex=normalize_genre_color(payload.color_hex),
        sort_order=(max_sort_order if max_sort_order is not None else -1) + 1,
        template_extension_id=template_extension_id,
        template_context_json=(
            json.dumps(payload.template_context, ensure_ascii=False)
            if payload.template_context is not None
            else None
        ),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(genre)
    ensure_case_genre_storage_directory(session, genre.id, now=now)
    session.commit()
    return {"ok": True, "data": {"genre": genre_data(genre)}}


@router.patch("/genres/reorder")
def reorder_case_genres(
    payload: CaseGenreReorder,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    genres = session.scalars(select(CaseGenre)).all()
    genres_by_id = {genre.id: genre for genre in genres}
    seen: set[str] = set()
    ordered_ids: list[str] = []
    for genre_id in payload.genre_ids:
        if genre_id in seen:
            continue
        if genre_id not in genres_by_id:
            raise json_error(404, "NOT_FOUND", "Case genre not found.")
        seen.add(genre_id)
        ordered_ids.append(genre_id)
    ordered_ids.extend(
        genre.id
        for genre in sorted(
            genres,
            key=lambda item: (item.sort_order, item.title.casefold(), item.created_at),
        )
        if genre.id not in seen
    )

    now = jst_iso()
    for index, genre_id in enumerate(ordered_ids):
        genre = genres_by_id[genre_id]
        genre.sort_order = index
        genre.updated_at = now
        genre.version += 1
    session.commit()
    ordered_genres = sorted(
        genres,
        key=lambda item: (item.sort_order, item.title.casefold(), item.created_at),
    )
    return {"ok": True, "data": {"items": [genre_data(genre) for genre in ordered_genres]}}


@router.patch("/genres/{genre_id}")
def update_case_genre(
    genre_id: str,
    payload: CaseGenreUpdate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    genre = session.get(CaseGenre, genre_id)
    if genre is None:
        raise json_error(404, "NOT_FOUND", "Case genre not found.")

    if payload.title is not None:
        title = payload.title.strip()
        if title == "":
            raise json_error(422, "VALIDATION_ERROR", "Case genre title is required.")
        duplicate = session.scalar(
            select(CaseGenre).where(CaseGenre.title == title, CaseGenre.id != genre.id)
        )
        if duplicate is not None:
            raise json_error(409, "CONFLICT", "Case genre already exists.")
        genre.title = title
    if payload.color_hex is not None:
        genre.color_hex = normalize_genre_color(payload.color_hex)
    if "template_extension_id" in payload.model_fields_set:
        genre.template_extension_id = validate_genre_template_extension(
            session,
            payload.template_extension_id,
        )
    if "template_context" in payload.model_fields_set:
        genre.template_context_json = (
            json.dumps(payload.template_context, ensure_ascii=False)
            if payload.template_context is not None
            else None
        )

    now = jst_iso()
    genre.updated_at = now
    genre.version += 1
    ensure_case_genre_storage_directory(session, genre.id, now=now)
    session.commit()
    return {"ok": True, "data": {"genre": genre_data(genre)}}


@router.delete("/genres/{genre_id}")
def delete_case_genre(
    genre_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    genre = session.get(CaseGenre, genre_id)
    if genre is None:
        raise json_error(404, "NOT_FOUND", "Case genre not found.")
    now = jst_iso()
    cases = session.scalars(select(Case).where(Case.genre_id == genre.id)).all()
    for case in cases:
        case.genre_id = None
        case.updated_at = now
        case.version += 1
        ensure_case_storage_directory(session, case, now=now)
    archive_case_genre_storage_directory(session, genre.id, now=now)
    session.delete(genre)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.get("/tool-icons")
def list_case_tool_icon_settings(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    settings = session.scalars(
        select(CaseToolIconSetting).order_by(
            CaseToolIconSetting.match_url.asc(),
            CaseToolIconSetting.created_at.asc(),
        )
    ).all()
    return {
        "ok": True,
        "data": {"items": [case_tool_icon_setting_data(setting) for setting in settings]},
    }


@router.post("/tool-icons")
def create_case_tool_icon_setting(
    payload: CaseToolIconSettingCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    match_url = normalize_case_tool_icon_match_url(payload.match_url)
    now = jst_iso()
    icon_object = save_case_tool_icon_storage_object(
        session,
        filename=payload.icon_filename,
        content_type=payload.icon_content_type,
        data_base64=payload.icon_data_base64,
        now=now,
    )
    setting = CaseToolIconSetting(
        id=new_id("case_tool_icon_setting"),
        storage_object_id=icon_object.id,
        icon_filename=payload.icon_filename,
        icon_content_type=icon_object.content_type or payload.icon_content_type,
        icon_data_url=None,
        match_url=match_url,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(setting)
    session.commit()
    return {"ok": True, "data": {"tool_icon": case_tool_icon_setting_data(setting)}}


@router.patch("/tool-icons/{tool_icon_id}")
def update_case_tool_icon_setting(
    tool_icon_id: str,
    payload: CaseToolIconSettingUpdate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    setting = session.get(CaseToolIconSetting, tool_icon_id)
    if setting is None:
        raise json_error(404, "NOT_FOUND", "Case tool icon setting not found.")
    old_storage_object_id = setting.storage_object_id
    now = jst_iso()
    if payload.match_url is not None:
        setting.match_url = normalize_case_tool_icon_match_url(payload.match_url)
    if payload.icon_data_base64 is not None:
        if payload.icon_content_type is None:
            raise json_error(422, "VALIDATION_ERROR", "Icon content type is required.")
        icon_object = save_case_tool_icon_storage_object(
            session,
            filename=payload.icon_filename,
            content_type=payload.icon_content_type,
            data_base64=payload.icon_data_base64,
            now=now,
        )
        setting.storage_object_id = icon_object.id
        setting.icon_filename = payload.icon_filename
        setting.icon_content_type = icon_object.content_type or payload.icon_content_type
        setting.icon_data_url = None
    elif payload.icon_filename is not None:
        setting.icon_filename = payload.icon_filename
    setting.updated_at = now
    setting.version += 1
    session.flush()
    delete_case_tool_icon_storage_object_if_unused(
        session,
        storage_object_id=old_storage_object_id,
        setting_id=setting.id,
        now=now,
    )
    session.commit()
    return {"ok": True, "data": {"tool_icon": case_tool_icon_setting_data(setting)}}


@router.delete("/tool-icons/{tool_icon_id}")
def delete_case_tool_icon_setting(
    tool_icon_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    setting = session.get(CaseToolIconSetting, tool_icon_id)
    if setting is None:
        raise json_error(404, "NOT_FOUND", "Case tool icon setting not found.")
    storage_object_id = setting.storage_object_id
    now = jst_iso()
    session.delete(setting)
    session.flush()
    delete_case_tool_icon_storage_object_if_unused(
        session,
        storage_object_id=storage_object_id,
        now=now,
    )
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.post("/sync-mail-sender-stakeholders")
def sync_mail_sender_stakeholders(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    added_count = sync_all_case_stakeholders_from_linked_mail_senders(session)
    session.commit()
    return {"ok": True, "data": {"added_count": added_count}}


@router.get("/auto-assign-rules")
def list_all_case_auto_assign_rules(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {
        "ok": True,
        "data": {"items": all_case_auto_assign_rule_items(session)},
    }


@router.get("/{case_id}")
def get_case(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")
    ensure_case_storage_directory(session, case)
    session.commit()

    events = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.case_id == case.id)
        .order_by(CaseEvent.occurred_at.desc(), CaseEvent.created_at.desc())
        .limit(20)
    ).all()
    return {
        "ok": True,
        "data": {
            "case": case_data(case, session),
            "related_mails": case_mail_link_items(session, case.id),
            "tasks": [case_task_data(task) for task in case_open_tasks(session, case.id)],
            "calendar_events": case_calendar_event_items(session, case.id),
            "contacts": [],
            "files": [],
            "stakeholders": stakeholder_items(session, case.id),
            "tool_links": tool_link_items(session, case.id),
            "current_situation": case_context_version_data(
                latest_case_context_version(session, case.id)
            ),
            "handover_artifact": case_handover_artifact_data(session, case),
            "handover_bundle": case_handover_artifact_data(
                session,
                case,
                source_type="case_handover_bundle",
            ),
            "recent_events": [case_event_data(event) for event in events],
        },
    }


@router.get("/{case_id}/files")
def list_case_files(
    case_id: str,
    limit: int = 200,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    ensure_case_storage_directory(session, case)
    session.commit()
    storage_objects = case_root_visible_storage_objects(session, case, limit=limit)
    return {
        "ok": True,
        "data": {
            "items": [
                storage_object_data(
                    storage_object,
                    session,
                    display_source="physical"
                    if storage_object.directory_id == case_storage_directory_id(case.id)
                    else "link",
                )
                for storage_object in storage_objects
            ]
        },
    }


@router.post("/{case_id}/files/{storage_object_id}/link")
def link_case_file(
    case_id: str,
    storage_object_id: str,
    payload: CaseFileLinkCreate | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    storage_object = session.get(StorageObject, storage_object_id)
    if (
        storage_object is None
        or storage_object.status != "active"
        or storage_object.scope != "managed"
    ):
        raise json_error(404, "NOT_FOUND", "Storage object not found.")

    now = jst_iso()
    target_directory_id = normalize_case_file_link_directory_id(
        session,
        case,
        payload.directory_id if payload is not None else None,
    )
    link_changed = False
    existing_link = session.scalar(
        select(FileLink)
        .where(FileLink.storage_object_id == storage_object.id)
        .where(FileLink.linked_type == "case")
        .where(FileLink.linked_id == case.id)
        .order_by(FileLink.created_at.asc(), FileLink.id.asc())
        .limit(1)
    )
    if existing_link is None:
        file_link = FileLink(
            id=new_id("file_link"),
            storage_object_id=storage_object.id,
            linked_type="case",
            linked_id=case.id,
            directory_id=target_directory_id,
            label=None,
            status="active",
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(file_link)
        link_changed = True
    elif existing_link.status != "active" or existing_link.directory_id != target_directory_id:
        existing_link.status = "active"
        existing_link.directory_id = target_directory_id
        existing_link.updated_at = now
        existing_link.version += 1
        link_changed = True

    if link_changed:
        case.updated_at = now
        case.version += 1
        record_storage_operation(
            session,
            operation_type="case_linked",
            now=now,
            storage_object=storage_object,
            details={
                "case_id": case.id,
                "case_name": case.name,
                "directory_id": target_directory_id,
            },
        )
        add_case_event(
            session,
            case,
            event_type="case_file_linked",
            title="File linked",
            now=now,
            metadata={"storage_object_id": storage_object.id},
        )
        session.commit()
    return {
        "ok": True,
        "data": {"storage_object": storage_object_data(storage_object, session)},
    }


@router.delete("/{case_id}/files/{storage_object_id}/link")
def unlink_case_file(
    case_id: str,
    storage_object_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    storage_object = session.get(StorageObject, storage_object_id)
    if (
        storage_object is None
        or storage_object.status != "active"
        or storage_object.scope != "managed"
    ):
        raise json_error(404, "NOT_FOUND", "Storage object not found.")

    now = jst_iso()
    active_links = session.scalars(
        select(FileLink)
        .where(FileLink.storage_object_id == storage_object.id)
        .where(FileLink.linked_type == "case")
        .where(FileLink.linked_id == case.id)
        .where(FileLink.status == "active")
    ).all()
    for file_link in active_links:
        file_link.status = "deleted"
        file_link.updated_at = now
        file_link.version += 1

    if active_links:
        case.updated_at = now
        case.version += 1
        record_storage_operation(
            session,
            operation_type="case_unlinked",
            now=now,
            storage_object=storage_object,
            details={
                "case_id": case.id,
                "case_name": case.name,
                "deleted_file_link_count": len(active_links),
            },
        )
        add_case_event(
            session,
            case,
            event_type="case_file_unlinked",
            title="File unlinked",
            now=now,
            metadata={"storage_object_id": storage_object.id},
        )
        session.commit()
    return {
        "ok": True,
        "data": {
            "unlinked": bool(active_links),
            "storage_object": storage_object_data(storage_object, session),
        },
    }


@router.post("/{case_id}/current-situation")
def regenerate_case_current_situation(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")

    now = jst_iso()
    provider = build_case_current_situation_provider()
    input_payload = case_current_situation_input_payload(session, case)
    provider_input_payload = with_llm_personalization(
        session, "case_current_situation_summary", input_payload
    )
    provider_response = provider.complete_json(
        function_type="case_current_situation_summary",
        input_payload=provider_input_payload,
    )
    output = provider_response.output
    context_markdown = case_current_situation_markdown(output)
    if context_markdown == "":
        raise json_error(502, "LLM_ERROR", "Case current situation was empty.")

    llm_run = LlmRun(
        id=new_id("llm_run"),
        function_type="case_current_situation_summary",
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps(
            {
                "case_id": case.id,
                "mail_thread_count": len(input_payload.get("mail_threads") or []),
                "file_count": len(input_payload.get("files") or []),
                "calendar_connected": bool(
                    isinstance(input_payload.get("calendar_status"), dict)
                    and input_payload["calendar_status"].get("connected") is True
                ),
                "task_connected": bool(
                    isinstance(input_payload.get("task_status"), dict)
                    and input_payload["task_status"].get("connected") is True
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        input_diagnostic_json=json.dumps(
            {
                "case_has_description": bool((case.description or "").strip()),
                "case_has_open_when": bool((case.open_when_text or "").strip()),
                "case_has_closed_when": bool((case.closed_when_text or "").strip()),
                "input_payload_size": len(json.dumps(input_payload, ensure_ascii=False)),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
        applied_instruction_rule_ids_json=json.dumps(
            llm_applied_instruction_rule_ids(provider_input_payload),
            ensure_ascii=True,
        ),
        output_json=json.dumps(output, ensure_ascii=True, sort_keys=True),
        output_text_preview=provider_response.output_preview,
        status="succeeded",
        error_type=None,
        error_message=None,
        retry_count=0,
        max_retry_count=3,
        prompt_tokens=provider_response.prompt_tokens,
        completion_tokens=provider_response.completion_tokens,
        total_tokens=provider_response.total_tokens,
        estimated_cost=provider_response.estimated_cost,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    session.add(llm_run)
    context = CaseContextVersion(
        id=new_id("case_context"),
        case_id=case.id,
        version_no=next_case_context_version_no(session, case.id),
        context_markdown=context_markdown,
        source_event_until_at=None,
        llm_run_id=llm_run.id,
        created_at=now,
        created_by="llm",
    )
    session.add(context)
    add_case_event(
        session,
        case,
        event_type="case_context_updated",
        title="Current Situation updated",
        now=now,
        metadata={"case_context_version_id": context.id, "llm_run_id": llm_run.id},
    )
    session.commit()
    return {"ok": True, "data": {"current_situation": case_context_version_data(context)}}


@router.post("/{case_id}/handover")
def generate_case_handover(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    if case.closed_at is None or case.progress_status != "completed":
        raise json_error(409, "CASE_NOT_COMPLETED", "Complete the Case before generating handover materials.")

    now = jst_iso()
    ensure_case_storage_directory(session, case)
    handover_directory_id = case_handover_storage_directory_id(case.id)
    mail_rows = case_handover_mail_rows(session, case.id)
    source_files = [
        item
        for item in case_storage_objects(session, case, limit=500)
        if item.source_type not in {
            "case_handover_report",
            "case_handover_mail_export",
            "case_handover_bundle",
        }
    ]
    historical_reports = session.scalars(
        select(StorageObject)
        .where(StorageObject.directory_id == handover_directory_id)
        .where(StorageObject.status == "active")
        .where(StorageObject.source_type == "case_handover_report")
        .order_by(StorageObject.created_at.asc(), StorageObject.id.asc())
    ).all()
    for storage_object in source_files:
        if bool(storage_object.llm_input_allowed):
            ensure_storage_object_llm_digest(
                session,
                storage_object=storage_object,
                version=None,
            )
    session.flush()
    input_payload = case_current_situation_input_payload(session, case)
    input_payload["handover_generation"] = True
    input_payload["mail_timeline"] = [
        {
            "message_id": message.id,
            "gmail_message_id": message.gmail_message_id,
            "received_at": message.received_at,
            "subject": message.subject,
            "from_address": message.from_address,
            "from_name": message.from_name,
            "summary": summary.summary_text if summary is not None else message.snippet,
            "body_text": (message.body_text or "")[:6000],
        }
        for message, summary in mail_rows
    ]
    provider = build_case_current_situation_provider()
    provider_input_payload = with_llm_personalization(
        session, "case_handover_generation", input_payload
    )
    provider_response = provider.complete_json(
        function_type="case_current_situation_summary",
        input_payload=provider_input_payload,
    )
    output = provider_response.output
    llm_run = LlmRun(
        id=new_id("llm_run"),
        function_type="case_handover_generation",
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps({
            "case_id": case.id,
            "mail_count": len(mail_rows),
            "file_count": len(source_files),
        }, ensure_ascii=True, sort_keys=True),
        input_diagnostic_json=json.dumps({
            "input_payload_size": len(json.dumps(input_payload, ensure_ascii=False)),
        }, ensure_ascii=True, sort_keys=True),
        applied_instruction_rule_ids_json=json.dumps(
            llm_applied_instruction_rule_ids(provider_input_payload),
            ensure_ascii=True,
        ),
        output_json=json.dumps(output, ensure_ascii=True, sort_keys=True),
        output_text_preview=provider_response.output_preview,
        status="succeeded",
        error_type=None,
        error_message=None,
        retry_count=0,
        max_retry_count=3,
        prompt_tokens=provider_response.prompt_tokens,
        completion_tokens=provider_response.completion_tokens,
        total_tokens=provider_response.total_tokens,
        estimated_cost=provider_response.estimated_cost,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    session.add(llm_run)
    exported_mails: list[StorageObject] = []
    existing_export_message_ids = set(session.scalars(
        select(StorageObject.source_message_id)
        .where(StorageObject.directory_id == handover_directory_id)
        .where(StorageObject.status == "active")
        .where(StorageObject.source_type == "case_handover_mail_export")
    ).all())
    for message, _summary in mail_rows:
        if message.id in existing_export_message_ids:
            continue
        exported_mails.append(save_storage_object(
            session,
            scope="managed",
            filename=f"{message.gmail_message_id}.eml",
            content_type="message/rfc822",
            data=case_handover_eml_bytes(message),
            now=now,
            directory_id=handover_directory_id,
            source_type="case_handover_mail_export",
            source_message_id=message.id,
        ))
    mail_export_items = session.scalars(
        select(StorageObject)
        .where(StorageObject.directory_id == handover_directory_id)
        .where(StorageObject.status == "active")
        .where(StorageObject.source_type == "case_handover_mail_export")
    ).all()
    mail_exports = {
        item.source_message_id: item
        for item in mail_export_items
        if item.source_message_id is not None
    }
    report_bytes = case_handover_markdown(
        case, output, mail_rows, source_files, now
    ).encode("utf-8")
    timestamp = now[:19].replace(":", "").replace("T", "-")
    report = save_storage_object(
        session,
        scope="managed",
        filename=f"handover-{handover_filename_part(case.name, case.id)}-{timestamp}.md",
        content_type="text/markdown; charset=utf-8",
        data=report_bytes,
        now=now,
        directory_id=handover_directory_id,
        source_type="case_handover_report",
    )
    bundle = save_storage_object(
        session,
        scope="managed",
        filename=f"handover-{handover_filename_part(case.name, case.id)}-{timestamp}.zip",
        content_type="application/zip",
        data=case_handover_zip_bytes(
            session,
            report_bytes=report_bytes,
            mail_rows=mail_rows,
            mail_exports=mail_exports,
            source_files=source_files,
            historical_reports=historical_reports,
        ),
        now=now,
        directory_id=handover_directory_id,
        source_type="case_handover_bundle",
    )
    add_case_event(
        session,
        case,
        event_type="case_handover_generated",
        title="Handover materials generated",
        now=now,
        metadata={
            "storage_object_id": report.id,
            "bundle_storage_object_id": bundle.id,
            "llm_run_id": llm_run.id,
        },
    )
    session.commit()
    return {"ok": True, "data": {
        "handover_artifact": storage_object_data(report, session),
        "handover_bundle": storage_object_data(bundle, session),
        "exported_mail_count": len(exported_mails),
        "related_mail_count": len(mail_rows),
        "source_file_count": len(source_files),
        "llm_run_id": llm_run.id,
    }}


@router.get("/{case_id}/mail-links")
def list_case_mail_links(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    return {"ok": True, "data": {"items": case_mail_link_items(session, case_id)}}


@router.get("/{case_id}/auto-assign-rules")
def list_case_auto_assign_rules(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    return {
        "ok": True,
        "data": {"items": case_auto_assign_rule_items(session, case_id)},
    }


@router.post("/{case_id}/auto-assign-rules")
def create_case_auto_assign_rule(
    case_id: str,
    payload: CaseAutoAssignRuleCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    sender_email = normalize_email_address(payload.sender_email or "")
    contact_id = (payload.contact_id or "").strip()
    if (sender_email == "") == (contact_id == ""):
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Specify exactly one of sender_email or contact_id.",
        )
    if contact_id != "":
        contact = session.get(Contact, contact_id)
        if contact is None or contact.deleted_at is not None:
            raise json_error(404, "NOT_FOUND", "Contact was not found.")
        rule_type = "sender_contact"
        rule_value = contact.id
    else:
        if "@" not in sender_email:
            raise json_error(422, "VALIDATION_ERROR", "Sender email is invalid.")
        rule_type = "sender_email"
        rule_value = sender_email
    existing = session.scalar(
        select(CaseAutoAssignRule)
        .where(CaseAutoAssignRule.case_id == case_id)
        .where(CaseAutoAssignRule.rule_type == rule_type)
        .where(CaseAutoAssignRule.rule_value == rule_value)
        .limit(1)
    )
    if existing is not None:
        raise json_error(409, "CONFLICT", "Auto assign rule already exists.")
    now = jst_iso()
    rule = CaseAutoAssignRule(
        id=new_id("case_auto_assign_rule"),
        case_id=case_id,
        rule_type=rule_type,
        rule_value=rule_value,
        label=(payload.label.strip() if payload.label and payload.label.strip() else None),
        is_enabled=1,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(rule)
    session.commit()
    return {"ok": True, "data": {"rule": case_auto_assign_rule_data(session, rule)}}


@router.delete("/{case_id}/auto-assign-rules/{rule_id}")
def delete_case_auto_assign_rule(
    case_id: str,
    rule_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    rule = session.get(CaseAutoAssignRule, rule_id)
    if rule is None or rule.case_id != case_id:
        raise json_error(404, "NOT_FOUND", "Auto assign rule not found.")
    session.delete(rule)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.get("/{case_id}/stakeholders")
def list_case_stakeholders(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    return {"ok": True, "data": {"items": stakeholder_items(session, case_id)}}


@router.post("/{case_id}/stakeholders")
def create_case_stakeholder(
    case_id: str,
    payload: CaseStakeholderCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    role = normalize_stakeholder_role(payload.role)
    contact = session.get(Contact, payload.contact_id)
    if contact is None or contact.deleted_at is not None:
        raise json_error(422, "VALIDATION_ERROR", "Contact not found.")
    duplicate = session.scalar(
        select(CaseStakeholder)
        .where(CaseStakeholder.case_id == case_id)
        .where(CaseStakeholder.contact_id == contact.id)
        .limit(1)
    )
    if duplicate is not None:
        raise json_error(409, "CONFLICT", "Contact is already linked to this Case.")
    next_order = (
        session.scalar(
            select(CaseStakeholder.sort_order)
            .where(CaseStakeholder.case_id == case_id)
            .order_by(CaseStakeholder.sort_order.desc())
            .limit(1)
        )
        or 0
    ) + 1
    now = jst_iso()
    stakeholder = CaseStakeholder(
        id=new_id("case_stakeholder"),
        case_id=case_id,
        contact_id=contact.id,
        role=role,
        sort_order=next_order,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(stakeholder)
    session.commit()
    return {"ok": True, "data": {"stakeholder": case_stakeholder_data(stakeholder, contact, session)}}


@router.patch("/{case_id}/stakeholders/{stakeholder_id}")
def update_case_stakeholder(
    case_id: str,
    stakeholder_id: str,
    payload: CaseStakeholderUpdate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    stakeholder = session.get(CaseStakeholder, stakeholder_id)
    if stakeholder is None or stakeholder.case_id != case_id:
        raise json_error(404, "NOT_FOUND", "Case stakeholder not found.")
    if payload.role is not None:
        stakeholder.role = normalize_stakeholder_role(payload.role)
    stakeholder.updated_at = jst_iso()
    stakeholder.version += 1
    contact = session.get(Contact, stakeholder.contact_id)
    if contact is None:
        raise json_error(404, "NOT_FOUND", "Contact not found.")
    session.commit()
    return {"ok": True, "data": {"stakeholder": case_stakeholder_data(stakeholder, contact, session)}}


@router.post("/{case_id}/stakeholders/reorder")
def reorder_case_stakeholders(
    case_id: str,
    payload: CaseStakeholderReorder,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    stakeholders = session.scalars(
        select(CaseStakeholder).where(CaseStakeholder.case_id == case_id)
    ).all()
    stakeholder_by_id = {stakeholder.id: stakeholder for stakeholder in stakeholders}
    if set(payload.stakeholder_ids) != set(stakeholder_by_id):
        raise json_error(422, "VALIDATION_ERROR", "Stakeholder order is incomplete.")
    now = jst_iso()
    for index, stakeholder_id in enumerate(payload.stakeholder_ids):
        stakeholder = stakeholder_by_id[stakeholder_id]
        stakeholder.sort_order = index
        stakeholder.updated_at = now
        stakeholder.version += 1
    session.commit()
    return {"ok": True, "data": {"items": stakeholder_items(session, case_id)}}


@router.delete("/{case_id}/stakeholders/{stakeholder_id}")
def delete_case_stakeholder(
    case_id: str,
    stakeholder_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    stakeholder = session.get(CaseStakeholder, stakeholder_id)
    if stakeholder is None or stakeholder.case_id != case_id:
        raise json_error(404, "NOT_FOUND", "Case stakeholder not found.")
    session.delete(stakeholder)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.get("/{case_id}/tool-links")
def list_case_tool_links(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    return {"ok": True, "data": {"items": tool_link_items(session, case_id)}}


@router.post("/{case_id}/tool-links")
def create_case_tool_link(
    case_id: str,
    payload: CaseToolLinkCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    url = payload.url.strip()
    if url == "":
        raise json_error(422, "VALIDATION_ERROR", "URL is required.")
    next_order = (
        session.scalar(
            select(CaseToolLink.sort_order)
            .where(CaseToolLink.case_id == case_id)
            .order_by(CaseToolLink.sort_order.desc())
            .limit(1)
        )
        or 0
    ) + 1
    now = jst_iso()
    icon_label = normalize_case_tool_icon_label(payload.icon_label, url=url)
    tool_link = CaseToolLink(
        id=new_id("case_tool_link"),
        case_id=case_id,
        url=url,
        icon_label=icon_label or "TL",
        sort_order=next_order,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(tool_link)
    session.commit()
    return {"ok": True, "data": {"tool_link": case_tool_link_data(session, tool_link)}}


@router.post("/{case_id}/tool-links/reorder")
def reorder_case_tool_links(
    case_id: str,
    payload: CaseToolLinkReorder,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    tool_links = session.scalars(
        select(CaseToolLink).where(CaseToolLink.case_id == case_id)
    ).all()
    tool_link_by_id = {tool_link.id: tool_link for tool_link in tool_links}
    if set(payload.tool_link_ids) != set(tool_link_by_id):
        raise json_error(422, "VALIDATION_ERROR", "Tool link order is incomplete.")
    now = jst_iso()
    for index, tool_link_id in enumerate(payload.tool_link_ids):
        tool_link = tool_link_by_id[tool_link_id]
        tool_link.sort_order = index
        tool_link.updated_at = now
        tool_link.version += 1
    session.commit()
    return {"ok": True, "data": {"items": tool_link_items(session, case_id)}}


@router.delete("/{case_id}/tool-links/{tool_link_id}")
def delete_case_tool_link(
    case_id: str,
    tool_link_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    tool_link = session.get(CaseToolLink, tool_link_id)
    if tool_link is None or tool_link.case_id != case_id:
        raise json_error(404, "NOT_FOUND", "Case tool link not found.")
    session.delete(tool_link)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.delete("/{case_id}")
def delete_case(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")
    if case.is_system_case:
        raise json_error(409, "SYSTEM_CASE_PROTECTED", "System Case cannot be deleted.")

    now = jst_iso()
    case_tasks = session.scalars(
        select(Task)
        .where(Task.case_id == case.id)
        .where(Task.deleted_at.is_(None))
    ).all()
    for task in case_tasks:
        task.deleted_at = now
        task.deleted_reason = "case_deleted"
        task.updated_at = now
        task.version += 1
        if task.storage_directory_id is not None:
            task_directory = session.get(StorageDirectory, task.storage_directory_id)
            if task_directory is not None:
                task_directory.status = "deleted"
                task_directory.updated_at = now
                task_directory.version += 1
    session.execute(delete(CaseToolLink).where(CaseToolLink.case_id == case.id))
    session.execute(delete(CaseStakeholder).where(CaseStakeholder.case_id == case.id))
    session.execute(delete(CaseMailLink).where(CaseMailLink.case_id == case.id))
    session.execute(delete(CaseEvent).where(CaseEvent.case_id == case.id))
    session.execute(
        update(FileLink)
        .where(FileLink.linked_type == "case")
        .where(FileLink.linked_id == case.id)
        .values(status="deleted", updated_at=now, version=FileLink.version + 1)
    )
    session.execute(update(AuditLog).where(AuditLog.case_id == case.id).values(case_id=None))
    session.execute(
        update(StorageDirectory)
        .where(StorageDirectory.case_id == case.id)
        .values(
            case_id=None,
            directory_kind="normal",
            updated_at=now,
            version=StorageDirectory.version + 1,
        )
    )
    session.delete(case)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.post("/{case_id}/complete")
def complete_case(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    if case.is_system_case:
        raise json_error(409, "SYSTEM_CASE_PROTECTED", "System Case cannot be completed.")
    open_task_id = session.scalar(
        select(Task.id)
        .where(Task.case_id == case.id)
        .where(Task.deleted_at.is_(None))
        .where(Task.status.not_in(("completed", "canceled")))
        .limit(1)
    )
    if open_task_id is not None:
        raise json_error(
            409,
            "OPEN_TASKS",
            "Case cannot be completed while open Tasks remain.",
        )
    now = jst_iso()
    if case.closed_at is None:
        previous_progress_status = case.progress_status
        previous_ball_status = case.ball_status
        case.closed_at = now
        case.progress_status = "completed"
        case.ball_status = "none"
        case.updated_at = now
        case.version += 1
        add_case_event(
            session,
            case,
            event_type="case_closed",
            title="Case closed",
            now=now,
            metadata={
                "previous_progress_status": previous_progress_status,
                "previous_ball_status": previous_ball_status,
            },
        )
        session.commit()
    return {"ok": True, "data": {"case": case_data(case, session)}}


@router.post("/{case_id}/reopen")
def reopen_case(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    now = jst_iso()
    if case.closed_at is not None or case.archived_at is not None:
        case.closed_at = None
        case.archived_at = None
        restore_case_open_state(session, case)
        case.updated_at = now
        case.version += 1
        add_case_event(
            session,
            case,
            event_type="case_reopened",
            title="Case reopened",
            now=now,
        )
        ensure_case_storage_directory(session, case, now=now)
        session.commit()
    return {"ok": True, "data": {"case": case_data(case, session)}}


@router.post("/{case_id}/archive")
def archive_case(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, case_id)
    if case.is_system_case:
        raise json_error(409, "SYSTEM_CASE_PROTECTED", "System Case cannot be archived.")
    now = jst_iso()
    if case.archived_at is None:
        previous_progress_status = case.progress_status
        previous_ball_status = case.ball_status
        case.archived_at = now
        case.updated_at = now
        case.version += 1
        add_case_event(
            session,
            case,
            event_type="case_archived",
            title="Case archived",
            now=now,
            metadata={
                "previous_progress_status": previous_progress_status,
                "previous_ball_status": previous_ball_status,
            },
        )
        ensure_case_storage_directory(session, case, now=now)
        session.commit()
    return {"ok": True, "data": {"case": case_data(case, session)}}


@router.patch("/{case_id}")
def update_case(
    case_id: str,
    payload: CaseUpdate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")

    if payload.name is not None:
        name = payload.name.strip()
        if name == "":
            raise json_error(422, "VALIDATION_ERROR", "Case name is required.")
        case.name = name
    case.description = normalized_optional_text(payload.description)
    case.open_when_date = normalized_optional_date(
        payload.open_when_date
        if payload.open_when_date is not None
        else payload.open_when_text
    )
    case.open_when_text = None
    case.closed_when_text = normalized_optional_text(payload.closed_when_text)
    if payload.genre_id is not None and session.get(CaseGenre, payload.genre_id) is None:
        raise json_error(422, "VALIDATION_ERROR", "Case genre not found.")
    case.genre_id = payload.genre_id
    if payload.tags is not None:
        case.tags_json = json.dumps(normalize_case_tags(payload.tags), ensure_ascii=False)
    case.updated_at = jst_iso()
    case.version += 1
    ensure_case_storage_directory(session, case)
    session.commit()
    return {"ok": True, "data": {"case": case_data(case, session)}}


@router.post("")
def create_case(
    payload: CaseCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    name = payload.name.strip()
    if name == "":
        raise json_error(422, "VALIDATION_ERROR", "Case name is required.")
    if payload.progress_status not in CASE_PROGRESS_STATUSES:
        raise json_error(422, "VALIDATION_ERROR", "Unsupported progress status.")
    if payload.genre_id is not None and session.get(CaseGenre, payload.genre_id) is None:
        raise json_error(422, "VALIDATION_ERROR", "Case genre not found.")

    now = jst_iso()
    case = Case(
        id=new_id("case"),
        genre_id=payload.genre_id,
        name=name,
        description=(
            payload.description.strip()
            if payload.description is not None and payload.description.strip() != ""
            else None
        ),
        open_when_date=normalized_optional_date(
            payload.open_when_date
            if payload.open_when_date is not None
            else payload.open_when_text
        ),
        open_when_text=None,
        closed_when_text=normalized_optional_text(payload.closed_when_text),
        tags_json=json.dumps(normalize_case_tags(payload.tags), ensure_ascii=False),
        progress_status=payload.progress_status,
        ball_status="none",
        closed_at=None,
        archived_at=None,
        is_system_case=0,
        system_case_key=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(case)
    ensure_case_storage_directory(session, case, now=now)
    session.add(
        CaseEvent(
            id=new_id("case_event"),
            case_id=case.id,
            event_type="case_created",
            title="Case created",
            summary=None,
            source_type="user",
            source_id=None,
            occurred_at=now,
            created_at=now,
            metadata_json=None,
        )
    )
    session.commit()
    return {"ok": True, "data": {"case": case_data(case, session)}}
