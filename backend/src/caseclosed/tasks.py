from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Case
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailThreadSummary
from caseclosed.db.models import StorageDirectory
from caseclosed.db.models import StorageObject
from caseclosed.db.models import Task
from caseclosed.db.models import TaskLink
from caseclosed.db.models import TaskProgressEntry
from caseclosed.db.runtime import ensure_task_storage_directory
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import task_storage_directory_id
from caseclosed.services.llm_provider import FUNCTION_TYPE_TASK_PREFILL_GENERATION
from caseclosed.services.llm_provider import FUNCTION_TYPE_HANDOVER_TASK_BATCH_GENERATION
from caseclosed.services.llm_provider import OpenAIProviderError
from caseclosed.services.llm_provider import build_handover_task_batch_provider
from caseclosed.services.llm_provider import build_task_prefill_provider
from caseclosed.services.mail_thread_summary import split_quoted_reply_sections

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

TASK_STATUSES = {"not_started", "in_progress", "frozen", "completed", "canceled"}
OPEN_TASK_STATUSES = {"not_started", "in_progress"}
UNFINISHED_TASK_STATUSES = {*OPEN_TASK_STATUSES, "frozen"}
PROGRESS_TASK_STATUSES = UNFINISHED_TASK_STATUSES
TASK_SOURCE_TYPES = {"manual", "mail", "llm", "recurring", "system"}
TASK_PRIORITIES = {"high", "middle", "low"}
TASK_RECURRENCE_RULE_TYPES = {"monthly", "weekly", "biweekly", "yearly"}


class TaskCreate(BaseModel):
    case_id: str
    parent_task_id: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    done_when_text: str | None = None
    progress_memo: str | None = None
    priority: str = "middle"
    start_at: str | None = None
    due_at: str | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    recurrence_rule_type: str | None = None
    recurrence_month_day: int | None = None
    recurrence_year_month: int | None = None
    recurrence_month_week: int | None = None
    recurrence_month_weekday: int | None = None
    recurrence_weekdays: list[int] | None = None
    recurrence_start_offset_days: int | None = None
    source_type: str = "manual"
    source_id: str | None = None


class TaskPatch(BaseModel):
    base_version: int | None = None
    case_id: str | None = None
    parent_task_id: str | None = None
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    done_when_text: str | None = None
    progress_memo: str | None = None
    status: str | None = None
    priority: str | None = None
    start_at: str | None = None
    due_at: str | None = None
    estimate_minutes: int | None = Field(default=None, ge=0)
    recurrence_rule_type: str | None = None
    recurrence_month_day: int | None = None
    recurrence_year_month: int | None = None
    recurrence_month_week: int | None = None
    recurrence_month_weekday: int | None = None
    recurrence_weekdays: list[int] | None = None
    recurrence_start_offset_days: int | None = None
    scheduled_minutes: int | None = Field(default=None, ge=0)
    worked_minutes: int | None = Field(default=None, ge=0)


class TaskCancelPayload(BaseModel):
    reason: str | None = None


class TaskDeletePayload(BaseModel):
    reason: str | None = None


class TaskPrefillPayload(BaseModel):
    prompt: str = Field(min_length=1)
    case_id: str | None = None
    current_fields: dict[str, object] | None = None


class TaskFromMailPayload(BaseModel):
    message_id: str = Field(min_length=1)
    case_id: str | None = None
    prompt: str | None = None


class HandoverTaskBatchPayload(BaseModel):
    case_id: str = Field(min_length=1)
    storage_object_ids: list[str] = Field(min_length=1)
    additional_prompt: str | None = None


class TaskProgressEntryCreate(BaseModel):
    body: str = Field(min_length=1)


class TaskProgressEntryPatch(BaseModel):
    body: str = Field(min_length=1)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def task_data(
    task: Task,
    session: DatabaseSession,
    *,
    include_links: bool = False,
    include_progress_entries: bool = False,
    include_subtasks: bool = False,
    case_cache: dict[str, Case] | None = None,
    directory_cache: dict[str, StorageDirectory] | None = None,
    ensure_storage: bool = True,
) -> dict[str, object]:
    case = (
        case_cache.get(task.case_id)
        if case_cache is not None
        else session.get(Case, task.case_id)
    )
    if ensure_storage and case is not None and task.deleted_at is None:
        directory = ensure_task_storage_directory(session, task)
    elif task.storage_directory_id is not None:
        directory = (
            directory_cache.get(task.storage_directory_id)
            if directory_cache is not None
            else session.get(StorageDirectory, task.storage_directory_id)
        )
    else:
        directory = None
    data: dict[str, object] = {
        "id": task.id,
        "case_id": task.case_id,
        "case_name": case.name if case is not None else None,
        "case_open_when_date": case.open_when_date if case is not None else None,
        "case_archived_at": case.archived_at if case is not None else None,
        "storage_directory_id": (
            directory.id
            if directory is not None
            else task.storage_directory_id
            or (
                task_storage_directory_id(task.id)
                if not ensure_storage and case is not None and task.deleted_at is None
                else None
            )
        ),
        "parent_task_id": task.parent_task_id,
        "title": task.title,
        "description": task.description,
        "done_when_text": task.done_when_text,
        "progress_memo": task.progress_memo,
        "status": task.status,
        "priority": task.priority,
        "start_at": task.start_at,
        "due_at": task.due_at,
        "estimate_minutes": task.estimate_minutes,
        "recurrence_rule_type": task.recurrence_rule_type,
        "recurrence_month_day": task.recurrence_month_day,
        "recurrence_year_month": task.recurrence_year_month,
        "recurrence_month_week": task.recurrence_month_week,
        "recurrence_month_weekday": task.recurrence_month_weekday,
        "recurrence_weekdays": json_int_list(task.recurrence_weekdays_json),
        "recurrence_start_offset_days": task.recurrence_start_offset_days,
        "recurrence_series_id": task.recurrence_series_id,
        "recurrence_sequence": task.recurrence_sequence,
        "scheduled_minutes": task.scheduled_minutes,
        "worked_minutes": task.worked_minutes,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "completed_at": task.completed_at,
        "canceled_at": task.canceled_at,
        "canceled_reason": task.canceled_reason,
        "deleted_at": task.deleted_at,
        "deleted_reason": task.deleted_reason,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "version": task.version,
    }
    if include_links:
        links = session.scalars(
            select(TaskLink)
            .where(TaskLink.task_id == task.id)
            .order_by(TaskLink.created_at.asc(), TaskLink.id.asc())
        ).all()
        data["links"] = [
            {
                "id": link.id,
                "task_id": link.task_id,
                "linked_type": link.linked_type,
                "linked_id": link.linked_id,
                "url": link.url,
                "label": link.label,
                "created_at": link.created_at,
            }
            for link in links
        ]
    if include_progress_entries:
        entries = session.scalars(
            select(TaskProgressEntry)
            .where(TaskProgressEntry.task_id == task.id)
            .order_by(TaskProgressEntry.created_at.asc(), TaskProgressEntry.id.asc())
        ).all()
        data["progress_entries"] = [
            {
                "id": entry.id,
                "task_id": entry.task_id,
                "body": entry.body,
                "created_at": entry.created_at,
            }
            for entry in entries
        ]
    if include_subtasks:
        subtasks = session.scalars(
            select(Task)
            .where(Task.parent_task_id == task.id)
            .where(Task.deleted_at.is_(None))
            .order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.updated_at.desc())
        ).all()
        data["subtasks"] = [
            task_data(subtask, session)
            for subtask in subtasks
        ]
    return data


def ensure_case_exists(session: DatabaseSession, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise json_error(404, "NOT_FOUND", "Case not found.")
    return case


def ensure_task_exists(
    session: DatabaseSession,
    task_id: str,
    *,
    include_deleted: bool = False,
) -> Task:
    task = session.get(Task, task_id)
    if task is None or (task.deleted_at is not None and not include_deleted):
        raise json_error(404, "NOT_FOUND", "Task not found.")
    return task


def validate_task_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise json_error(400, "INVALID_STATUS", "Invalid Task status.")


def validate_task_priority(priority: str) -> None:
    if priority not in TASK_PRIORITIES:
        raise json_error(400, "INVALID_PRIORITY", "Invalid Task priority.")


def normalize_recurrence_weekdays(values: list[int] | None) -> list[int]:
    if values is None:
        return []
    weekdays: list[int] = []
    seen: set[int] = set()
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 6:
            raise json_error(422, "VALIDATION_ERROR", "Invalid recurrence weekday.")
        if value not in seen:
            seen.add(value)
            weekdays.append(value)
    return weekdays


def validate_recurrence_settings(
    *,
    rule_type: str | None,
    month_day: int | None,
    year_month: int | None,
    month_week: int | None,
    month_weekday: int | None,
    weekdays: list[int] | None,
    start_offset_days: int | None,
) -> tuple[str | None, int | None, int | None, int | None, int | None, list[int], int | None]:
    if rule_type is None or rule_type == "":
        return None, None, None, None, None, [], None
    if rule_type not in TASK_RECURRENCE_RULE_TYPES:
        raise json_error(400, "INVALID_RECURRENCE", "Invalid recurrence rule.")
    normalized_weekdays = normalize_recurrence_weekdays(weekdays)
    offset = -7 if start_offset_days is None else start_offset_days
    if offset > 0:
        raise json_error(422, "VALIDATION_ERROR", "Start offset must be zero or negative.")
    if rule_type in {"monthly", "yearly"}:
        effective_year_month = None
        if rule_type == "yearly":
            effective_year_month = 1 if year_month is None else year_month
            if effective_year_month < 1 or effective_year_month > 12:
                raise json_error(422, "VALIDATION_ERROR", "Invalid yearly recurrence month.")
        if month_week is not None or month_weekday is not None:
            effective_month_week = -1 if month_week is None else month_week
            effective_month_weekday = 1 if month_weekday is None else month_weekday
            if effective_month_week not in {-1, 1, 2, 3, 4, 5}:
                raise json_error(422, "VALIDATION_ERROR", "Invalid recurrence month week.")
            if (
                not isinstance(effective_month_weekday, int)
                or isinstance(effective_month_weekday, bool)
                or effective_month_weekday < 0
                or effective_month_weekday > 6
            ):
                raise json_error(422, "VALIDATION_ERROR", "Invalid recurrence month weekday.")
            return (
                rule_type,
                None,
                effective_year_month,
                effective_month_week,
                effective_month_weekday,
                [],
                offset,
            )
        effective_month_day = 0 if month_day is None else month_day
        if effective_month_day > 31 or effective_month_day < -30:
            raise json_error(422, "VALIDATION_ERROR", "Invalid monthly recurrence day.")
        return rule_type, effective_month_day, effective_year_month, None, None, [], offset
    if len(normalized_weekdays) == 0:
        raise json_error(422, "VALIDATION_ERROR", "At least one weekday is required.")
    return rule_type, None, None, None, None, normalized_weekdays, offset


def parse_task_date(value: str | None) -> date:
    if value is None or value.strip() == "":
        return jst_now().date()
    return date.fromisoformat(value[:10])


def recurrence_day_in_month(year: int, month: int, month_day: int) -> date:
    last_day = monthrange(year, month)[1]
    if month_day > 0:
        day = min(month_day, last_day)
    else:
        day = max(1, last_day + month_day)
    return date(year, month, day)


def recurrence_nth_weekday_in_month(
    year: int,
    month: int,
    month_week: int,
    month_weekday: int,
) -> date:
    # UI weekdays use Sunday=0. Python date.weekday() uses Monday=0.
    python_weekday = (month_weekday + 6) % 7
    last_day = monthrange(year, month)[1]
    if month_week == -1:
        candidate = date(year, month, last_day)
        while candidate.weekday() != python_weekday:
            candidate -= timedelta(days=1)
        return candidate
    candidate = date(year, month, 1)
    while candidate.weekday() != python_weekday:
        candidate += timedelta(days=1)
    candidate += timedelta(days=(month_week - 1) * 7)
    if candidate.month == month:
        return candidate
    # A requested 5th weekday may not exist; use the last matching weekday instead.
    return recurrence_nth_weekday_in_month(year, month, -1, month_weekday)


def recurrence_month_candidate(
    year: int,
    month: int,
    *,
    month_day: int | None,
    month_week: int | None,
    month_weekday: int | None,
) -> date:
    if month_week is not None and month_weekday is not None:
        return recurrence_nth_weekday_in_month(year, month, month_week, month_weekday)
    return recurrence_day_in_month(year, month, 0 if month_day is None else month_day)


def monthly_due_date_after(
    base_date: date,
    *,
    month_day: int | None,
    month_week: int | None,
    month_weekday: int | None,
) -> date:
    year = base_date.year
    month = base_date.month
    while True:
        candidate = recurrence_month_candidate(
            year,
            month,
            month_day=month_day,
            month_week=month_week,
            month_weekday=month_weekday,
        )
        if candidate > base_date:
            return candidate
        month += 1
        if month > 12:
            year += 1
            month = 1


def yearly_due_date_after(
    base_date: date,
    *,
    year_month: int | None,
    month_day: int | None,
    month_week: int | None,
    month_weekday: int | None,
) -> date:
    target_month = 1 if year_month is None else year_month
    year = base_date.year
    while True:
        candidate = recurrence_month_candidate(
            year,
            target_month,
            month_day=month_day,
            month_week=month_week,
            month_weekday=month_weekday,
        )
        if candidate > base_date:
            return candidate
        year += 1


def weekly_due_date_after(base_date: date, weekdays: list[int], *, interval_weeks: int) -> date:
    # UI weekdays use Sunday=0. Python is Monday=0, so convert candidate dates back.
    allowed = set(weekdays)
    for delta in range(1, 370):
        candidate = base_date + timedelta(days=delta)
        sunday_based_weekday = (candidate.weekday() + 1) % 7
        if sunday_based_weekday not in allowed:
            continue
        if interval_weeks == 1:
            return candidate
        if delta >= 8:
            return candidate
    raise json_error(500, "RECURRENCE_ERROR", "Could not calculate next recurrence.")


def next_recurrence_due_date(task: Task) -> date | None:
    if task.recurrence_rule_type is None:
        return None
    base_date = parse_task_date(task.due_at)
    if task.recurrence_rule_type == "monthly":
        return monthly_due_date_after(
            base_date,
            month_day=task.recurrence_month_day,
            month_week=task.recurrence_month_week,
            month_weekday=task.recurrence_month_weekday,
        )
    if task.recurrence_rule_type == "yearly":
        return yearly_due_date_after(
            base_date,
            year_month=task.recurrence_year_month,
            month_day=task.recurrence_month_day,
            month_week=task.recurrence_month_week,
            month_weekday=task.recurrence_month_weekday,
        )
    weekdays = json_int_list(task.recurrence_weekdays_json)
    if task.recurrence_rule_type == "weekly":
        return weekly_due_date_after(base_date, weekdays, interval_weeks=1)
    if task.recurrence_rule_type == "biweekly":
        return weekly_due_date_after(base_date, weekdays, interval_weeks=2)
    return None


def first_recurrence_due_date_on_or_after(task: Task, base_date: date) -> date | None:
    if task.recurrence_rule_type is None:
        return None
    if task.recurrence_rule_type == "monthly":
        return monthly_due_date_after(
            base_date - timedelta(days=1),
            month_day=task.recurrence_month_day,
            month_week=task.recurrence_month_week,
            month_weekday=task.recurrence_month_weekday,
        )
    if task.recurrence_rule_type == "yearly":
        return yearly_due_date_after(
            base_date - timedelta(days=1),
            year_month=task.recurrence_year_month,
            month_day=task.recurrence_month_day,
            month_week=task.recurrence_month_week,
            month_weekday=task.recurrence_month_weekday,
        )
    weekdays = json_int_list(task.recurrence_weekdays_json)
    if task.recurrence_rule_type in {"weekly", "biweekly"}:
        return weekly_due_date_after(
            base_date - timedelta(days=1),
            weekdays,
            interval_weeks=1,
        )
    return None


def recurrence_start_date_for_due(task: Task, due_date: date) -> date:
    offset = task.recurrence_start_offset_days if task.recurrence_start_offset_days is not None else -7
    return due_date + timedelta(days=offset)


def fill_missing_recurrence_dates(task: Task, *, today: date | None = None) -> None:
    if task.recurrence_rule_type is None:
        return
    current_today = jst_now().date() if today is None else today
    if task.due_at is None or task.due_at.strip() == "":
        due_date = first_recurrence_due_date_on_or_after(task, current_today)
        if due_date is not None:
            task.due_at = due_date.isoformat()
    if task.start_at is None or task.start_at.strip() == "":
        due_date = parse_task_date(task.due_at)
        task.start_at = recurrence_start_date_for_due(task, due_date).isoformat()


def create_next_recurring_task(
    session: DatabaseSession,
    *,
    completed_task: Task,
    now: str,
) -> Task | None:
    next_due_date = next_recurrence_due_date(completed_task)
    if next_due_date is None:
        return None
    if completed_task.recurrence_series_id is None:
        completed_task.recurrence_series_id = completed_task.id
    next_start_date = recurrence_start_date_for_due(completed_task, next_due_date)
    next_task = Task(
        id=new_id("task"),
        case_id=completed_task.case_id,
        storage_directory_id=None,
        parent_task_id=None,
        title=completed_task.title,
        description=completed_task.description,
        done_when_text=completed_task.done_when_text,
        progress_memo=None,
        status="not_started",
        priority=completed_task.priority,
        start_at=next_start_date.isoformat(),
        due_at=next_due_date.isoformat(),
        estimate_minutes=completed_task.estimate_minutes,
        recurrence_rule_type=completed_task.recurrence_rule_type,
        recurrence_month_day=completed_task.recurrence_month_day,
        recurrence_year_month=completed_task.recurrence_year_month,
        recurrence_month_week=completed_task.recurrence_month_week,
        recurrence_month_weekday=completed_task.recurrence_month_weekday,
        recurrence_weekdays_json=completed_task.recurrence_weekdays_json,
        recurrence_start_offset_days=completed_task.recurrence_start_offset_days,
        recurrence_series_id=completed_task.recurrence_series_id,
        recurrence_sequence=completed_task.recurrence_sequence + 1,
        scheduled_minutes=0,
        worked_minutes=0,
        source_type="recurring",
        source_id=completed_task.id,
        completed_at=None,
        canceled_at=None,
        canceled_reason=None,
        deleted_at=None,
        deleted_reason=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    sync_open_task_status_from_start(session, next_task)
    ensure_task_storage_directory(session, next_task, now=now)
    session.add(next_task)
    return next_task


def validate_source_type(source_type: str) -> None:
    if source_type not in TASK_SOURCE_TYPES:
        raise json_error(400, "INVALID_SOURCE_TYPE", "Invalid Task source type.")


def ensure_task_mail_link(
    session: DatabaseSession,
    *,
    task: Task,
    message_id: str | None,
    now: str,
) -> None:
    normalized_message_id = normalize_optional_text(message_id)
    if normalized_message_id is None:
        return
    if session.get(GmailMessage, normalized_message_id) is None:
        raise json_error(404, "NOT_FOUND", "Source mail not found.")
    existing = session.scalar(
        select(TaskLink.id)
        .where(TaskLink.task_id == task.id)
        .where(TaskLink.linked_type == "mail")
        .where(TaskLink.linked_id == normalized_message_id)
        .limit(1)
    )
    if existing is not None:
        return
    session.add(
        TaskLink(
            id=new_id("task_link"),
            task_id=task.id,
            linked_type="mail",
            linked_id=normalized_message_id,
            url=None,
            label=None,
            created_at=now,
        )
    )


def validate_parent_task(
    session: DatabaseSession,
    *,
    parent_task_id: str | None,
    case_id: str,
    task_id: str | None = None,
) -> None:
    if parent_task_id is None:
        return
    if parent_task_id == task_id:
        raise json_error(400, "INVALID_PARENT_TASK", "Task cannot be its own parent.")
    parent_task = ensure_task_exists(session, parent_task_id)
    if parent_task.case_id != case_id:
        raise json_error(400, "INVALID_PARENT_TASK", "Parent Task must belong to the same Case.")


def normalize_task_prefill_output(output: dict[str, object]) -> dict[str, object]:
    priority = str(output.get("priority") or "middle").strip().lower()
    if priority not in TASK_PRIORITIES:
        priority = "middle"
    due_at = normalize_optional_text(
        str(output.get("due_at")) if output.get("due_at") is not None else None
    )
    if due_at is not None:
        due_at = due_at[:10]
    estimate_value = output.get("estimate_minutes")
    estimate_minutes: int | None = None
    if isinstance(estimate_value, int) and estimate_value >= 0:
        estimate_minutes = estimate_value
    return {
        "title": normalize_optional_text(str(output.get("title") or "")),
        "description": normalize_optional_text(str(output.get("description") or "")),
        "done_when_text": normalize_optional_text(str(output.get("done_when_text") or "")),
        "priority": priority,
        "due_at": due_at,
        "estimate_minutes": estimate_minutes,
        "reasoning_summary": normalize_optional_text(
            str(output.get("reasoning_summary") or "")
        ),
        "warnings": output.get("warnings") if isinstance(output.get("warnings"), list) else [],
    }


def json_list(value: str | None) -> list[str]:
    if value is None:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if isinstance(item, str)]


def json_int_list(value: str | None) -> list[int]:
    if value is None:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    result: list[int] = []
    for item in decoded:
        if isinstance(item, int) and not isinstance(item, bool):
            result.append(item)
    return result


def run_task_prefill(
    session: DatabaseSession,
    input_payload: dict[str, object],
) -> tuple[dict[str, object], str]:
    provider = build_task_prefill_provider()
    now = jst_iso()
    try:
        provider_response = provider.complete_json(
            function_type=FUNCTION_TYPE_TASK_PREFILL_GENERATION,
            input_payload=input_payload,
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
        function_type=FUNCTION_TYPE_TASK_PREFILL_GENERATION,
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps(input_payload, ensure_ascii=False),
        input_diagnostic_json=None,
        applied_instruction_rule_ids_json=None,
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
        raise json_error(502, "LLM_PREFILL_FAILED", error_message or "Task prefill failed.")
    return normalize_task_prefill_output(output), llm_run.id


def truncate_text(value: object, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def normalize_handover_task_suggestions(output: dict[str, object]) -> list[dict[str, object]]:
    suggestions_payload = output.get("suggestions")
    if not isinstance(suggestions_payload, list):
        return []
    suggestions: list[dict[str, object]] = []
    for item in suggestions_payload[:30]:
        if not isinstance(item, dict):
            continue
        title = normalize_optional_text(str(item.get("title") or ""))
        if title is None:
            continue
        priority = str(item.get("priority") or "middle")
        if priority not in TASK_PRIORITIES:
            priority = "middle"
        estimate_minutes = item.get("estimate_minutes")
        warnings_payload = item.get("warnings")
        warnings = [
            str(warning)
            for warning in warnings_payload
            if isinstance(warning, str)
        ] if isinstance(warnings_payload, list) else []
        suggestions.append(
            {
                "title": title,
                "description": normalize_optional_text(str(item.get("description") or "")),
                "done_when_text": normalize_optional_text(str(item.get("done_when_text") or "")),
                "priority": priority,
                "due_at": normalize_optional_text(str(item.get("due_at") or "")),
                "estimate_minutes": estimate_minutes if isinstance(estimate_minutes, int) else None,
                "reasoning_summary": normalize_optional_text(
                    str(item.get("reasoning_summary") or "")
                ),
                "warnings": warnings,
            }
        )
    return suggestions


def run_handover_task_batch_generation(
    session: DatabaseSession,
    input_payload: dict[str, object],
) -> tuple[list[dict[str, object]], str]:
    provider = build_handover_task_batch_provider()
    now = jst_iso()
    try:
        provider_response = provider.complete_json(
            function_type=FUNCTION_TYPE_HANDOVER_TASK_BATCH_GENERATION,
            input_payload=input_payload,
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
        function_type=FUNCTION_TYPE_HANDOVER_TASK_BATCH_GENERATION,
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        prompt_version_id=None,
        input_hash=None,
        input_source_json=json.dumps(input_payload, ensure_ascii=False),
        input_diagnostic_json=None,
        applied_instruction_rule_ids_json=None,
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
        raise json_error(502, "LLM_PREFILL_FAILED", error_message or "Task batch generation failed.")
    return normalize_handover_task_suggestions(output), llm_run.id


def default_task_case(session: DatabaseSession) -> Case:
    case = session.scalar(select(Case).where(Case.system_case_key == "inbox"))
    if case is None:
        raise json_error(500, "DATA_INTEGRITY_ERROR", "Default Task Case is missing.")
    return case


def thread_case_for_task(
    session: DatabaseSession,
    *,
    message: GmailMessage,
    preferred_case_id: str | None,
) -> Case:
    if preferred_case_id is not None:
        case = ensure_case_exists(session, preferred_case_id)
        if case.archived_at is not None:
            raise json_error(409, "CASE_ARCHIVED", "Cannot create Task in archived Case.")
        return case
    thread_message_ids = session.scalars(
        select(GmailMessage.id)
        .where(GmailMessage.thread_id == message.thread_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    case = session.scalars(
        select(Case)
        .join(CaseMailLink, CaseMailLink.case_id == Case.id)
        .where(CaseMailLink.message_id.in_(thread_message_ids))
        .where(Case.archived_at.is_(None))
        .group_by(Case.id)
        .order_by(Case.is_system_case.asc(), Case.updated_at.desc(), Case.name.asc())
        .limit(1)
    ).first()
    return case if case is not None else default_task_case(session)


def ensure_mail_thread_linked_to_case(
    session: DatabaseSession,
    *,
    message: GmailMessage,
    case: Case,
    now: str,
) -> None:
    if case.system_case_key == "inbox":
        return
    thread_messages = session.scalars(
        select(GmailMessage)
        .where(GmailMessage.thread_id == message.thread_id)
        .order_by(GmailMessage.received_at.asc(), GmailMessage.id.asc())
    ).all()
    message_ids = [thread_message.id for thread_message in thread_messages]
    existing_message_ids = set(
        session.scalars(
            select(CaseMailLink.message_id)
            .where(CaseMailLink.case_id == case.id)
            .where(CaseMailLink.message_id.in_(message_ids))
        ).all()
    )
    for thread_message in thread_messages:
        if thread_message.id in existing_message_ids:
            continue
        session.add(
            CaseMailLink(
                id=new_id("case_mail_link"),
                case_id=case.id,
                message_id=thread_message.id,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )


def task_prompt_from_mail(
    session: DatabaseSession,
    *,
    message: GmailMessage,
    extra_prompt: str | None,
) -> str:
    current_body_text, quoted_reply_context = split_quoted_reply_sections(
        message.body_text or ""
    )
    thread_summary = session.scalar(
        select(MailThreadSummary).where(MailThreadSummary.thread_id == message.thread_id)
    )
    mail_summary = session.scalar(
        select(MailSummary).where(MailSummary.message_id == message.id)
    )
    thread_summaries = session.scalars(
        select(MailSummary)
        .join(GmailMessage, GmailMessage.id == MailSummary.message_id)
        .where(GmailMessage.thread_id == message.thread_id)
        .order_by(GmailMessage.received_at.asc(), GmailMessage.id.asc())
    ).all()
    summary_lines = [
        f"- {summary.summary_text}"
        for summary in thread_summaries
        if summary.summary_text.strip() != ""
    ]
    return "\n".join(
        [
            "Create one practical Task from the selected source mail.",
            "Write all generated Task fields in Japanese, even when the selected mail is written in English.",
            "Use the source mail only as information; do not copy English wording into the Task unless it is a proper noun, title, identifier, URL, or quoted exact term.",
            "Use the current/new message body as the primary source.",
            "Treat quoted reply history only as context; do not create a task solely from quoted history.",
            "If the mail does not clearly request action, create a review/triage task instead of inventing a commitment.",
            "",
            f"User instruction: {extra_prompt.strip() if extra_prompt else ''}",
            "",
            "Selected mail:",
            f"- Message ID: {message.id}",
            f"- Gmail thread ID: {message.gmail_thread_id}",
            f"- Received at: {message.received_at}",
            f"- Subject: {message.subject or ''}",
            f"- From: {message.from_name or ''} <{message.from_address}>",
            f"- To: {json_list(message.to_addresses_json)}",
            f"- Cc: {json_list(message.cc_addresses_json)}",
            f"- Snippet: {message.snippet or ''}",
            "",
            f"Stored mail summary: {mail_summary.summary_text if mail_summary else ''}",
            f"Stored thread summary: {thread_summary.summary_text if thread_summary else ''}",
            "Stored summaries in this thread:",
            "\n".join(summary_lines) if summary_lines else "(none)",
            "",
            "Current message body:",
            current_body_text or message.body_text or message.snippet or "",
            "",
            "Quoted reply context:",
            quoted_reply_context,
        ]
    )


def task_has_open_children(session: DatabaseSession, task_id: str) -> bool:
    child_id = session.scalar(
        select(Task.id)
        .where(Task.parent_task_id == task_id)
        .where(Task.deleted_at.is_(None))
        .where(Task.status.in_(UNFINISHED_TASK_STATUSES))
        .limit(1)
    )
    return child_id is not None


def ensure_task_progress_entry_exists(
    session: DatabaseSession,
    *,
    task_id: str,
    entry_id: str,
) -> TaskProgressEntry:
    entry = session.get(TaskProgressEntry, entry_id)
    if entry is None or entry.task_id != task_id:
        raise json_error(404, "NOT_FOUND", "Progress memo not found.")
    return entry


def latest_task_progress_memo(session: DatabaseSession, task_id: str) -> str | None:
    entry = session.scalars(
        select(TaskProgressEntry)
        .where(TaskProgressEntry.task_id == task_id)
        .order_by(TaskProgressEntry.created_at.desc(), TaskProgressEntry.id.desc())
        .limit(1)
    ).first()
    return entry.body if entry is not None else None


def task_has_progress_entries(session: DatabaseSession, task_id: str) -> bool:
    entry_id = session.scalar(
        select(TaskProgressEntry.id)
        .where(TaskProgressEntry.task_id == task_id)
        .limit(1)
    )
    return entry_id is not None


def case_has_opened(case: Case | None) -> bool:
    if case is None:
        return True
    if case.open_when_date is None or case.open_when_date.strip() == "":
        return True
    return case.open_when_date[:10] <= jst_now().date().isoformat()


def task_is_waiting_to_start(session: DatabaseSession, task: Task) -> bool:
    if not case_has_opened(session.get(Case, task.case_id)):
        return True
    if task.start_at is None:
        return False
    return task.start_at[:10] > jst_now().date().isoformat()


def sync_open_task_status_from_start(session: DatabaseSession, task: Task) -> None:
    if task.status not in OPEN_TASK_STATUSES:
        return
    task.status = "not_started" if task_is_waiting_to_start(session, task) else "in_progress"
    task.completed_at = None
    task.canceled_at = None
    task.canceled_reason = None


def activate_started_tasks(session: DatabaseSession) -> None:
    tasks = session.scalars(
        select(Task)
        .where(Task.deleted_at.is_(None))
        .where(Task.status == "not_started")
    ).all()
    case_ids = {task.case_id for task in tasks}
    cases_by_id = (
        {
            case.id: case
            for case in session.scalars(
                select(Case).where(Case.id.in_(case_ids))
            ).all()
        }
        if case_ids
        else {}
    )
    today = jst_now().date().isoformat()
    now: str | None = None
    for task in tasks:
        case = cases_by_id.get(task.case_id)
        if not case_has_opened(case):
            continue
        if task.start_at is not None and task.start_at[:10] > today:
            continue
        if now is None:
            now = jst_iso()
        task.status = "in_progress"
        task.updated_at = now
        task.version += 1


@router.post("/prefill")
def prefill_task(
    payload: TaskPrefillPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case: Case | None = None
    if payload.case_id is not None:
        case = ensure_case_exists(session, payload.case_id)
    input_payload: dict[str, object] = {
        "prompt": payload.prompt.strip(),
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "open_when_date": case.open_when_date,
            "closed_when_text": case.closed_when_text,
        }
        if case is not None
        else None,
        "current_fields": payload.current_fields or {},
    }
    prefill, llm_run_id = run_task_prefill(session, input_payload)
    session.commit()
    return {
        "ok": True,
        "data": {
            "prefill": prefill,
            "llm_run_id": llm_run_id,
        },
    }


@router.post("/handover-prefill")
def prefill_tasks_from_handover(
    payload: HandoverTaskBatchPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, payload.case_id)
    from caseclosed.storage import storage_summary_source

    files: list[dict[str, object]] = []
    seen_object_ids: set[str] = set()
    for storage_object_id in payload.storage_object_ids:
        object_id = storage_object_id.strip()
        if object_id == "" or object_id in seen_object_ids:
            continue
        seen_object_ids.add(object_id)
        storage_object = session.get(StorageObject, object_id)
        if (
            storage_object is None
            or storage_object.status != "active"
            or storage_object.scope != "managed"
        ):
            raise json_error(404, "NOT_FOUND", "Storage object not found.")
        if not bool(storage_object.llm_input_allowed):
            raise json_error(
                403,
                "LLM_INPUT_NOT_ALLOWED",
                "Selected file is not allowed as LLM input.",
            )
        source = storage_summary_source(storage_object, None, session)
        files.append(
            {
                "storage_object_id": storage_object.id,
                "filename": storage_object.original_filename,
                "content_type": storage_object.content_type,
                "byte_size": storage_object.byte_size,
                "source_kind": source.get("source_kind"),
                "read_scope": source.get("read_scope"),
                "truncated": source.get("truncated"),
                "limitations": source.get("limitations"),
                "source_text": truncate_text(source.get("source_text"), 16000),
            }
        )
    if not files:
        raise json_error(400, "NO_FILES", "No usable handover files were selected.")

    input_payload: dict[str, object] = {
        "prompt": normalize_optional_text(payload.additional_prompt) or "",
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "open_when_date": case.open_when_date,
            "closed_when_text": case.closed_when_text,
        },
        "files": files,
    }
    suggestions, llm_run_id = run_handover_task_batch_generation(session, input_payload)
    session.commit()
    return {
        "ok": True,
        "data": {
            "suggestions": suggestions,
            "llm_run_id": llm_run_id,
        },
    }


@router.post("/from-mail")
def create_task_from_mail(
    payload: TaskFromMailPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    message = session.get(GmailMessage, payload.message_id)
    if message is None:
        raise json_error(404, "NOT_FOUND", "Mail not found.")
    auto_state = session.scalar(
        select(MailAutoState).where(MailAutoState.message_id == message.id)
    )
    if auto_state is not None and bool(auto_state.llm_blocked):
        raise json_error(409, "LLM_BLOCKED", "This mail is blocked from LLM processing.")

    case = thread_case_for_task(
        session,
        message=message,
        preferred_case_id=payload.case_id,
    )
    input_payload: dict[str, object] = {
        "prompt": task_prompt_from_mail(
            session,
            message=message,
            extra_prompt=payload.prompt,
        ),
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "open_when_date": case.open_when_date,
            "closed_when_text": case.closed_when_text,
        },
        "current_fields": {},
    }
    prefill, llm_run_id = run_task_prefill(session, input_payload)
    now = jst_iso()
    ensure_mail_thread_linked_to_case(session, message=message, case=case, now=now)
    title = normalize_optional_text(str(prefill.get("title") or ""))
    if title is None:
        title = normalize_optional_text(message.subject) or "Review mail"
    priority = str(prefill.get("priority") or "middle")
    validate_task_priority(priority)
    estimate_minutes = prefill.get("estimate_minutes")
    task = Task(
        id=new_id("task"),
        case_id=case.id,
        storage_directory_id=None,
        parent_task_id=None,
        title=title,
        description=normalize_optional_text(str(prefill.get("description") or "")),
        done_when_text=normalize_optional_text(str(prefill.get("done_when_text") or "")),
        progress_memo=None,
        status="not_started",
        priority=priority,
        start_at=now[:10],
        due_at=normalize_optional_text(str(prefill.get("due_at") or "")),
        estimate_minutes=estimate_minutes if isinstance(estimate_minutes, int) else None,
        scheduled_minutes=0,
        worked_minutes=0,
        source_type="mail",
        source_id=message.id,
        completed_at=None,
        canceled_at=None,
        canceled_reason=None,
        deleted_at=None,
        deleted_reason=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    fill_missing_recurrence_dates(task)
    sync_open_task_status_from_start(session, task)
    ensure_task_storage_directory(session, task, now=now)
    case.updated_at = now
    case.version += 1
    session.add(task)
    ensure_task_mail_link(session, task=task, message_id=message.id, now=now)
    session.commit()
    return {
        "ok": True,
        "data": {
            "task": task_data(task, session, include_links=True),
            "prefill": prefill,
            "llm_run_id": llm_run_id,
        },
    }


@router.get("")
def list_tasks(
    case_id: str | None = None,
    status: str = "open",
    due: str = "all",
    include_deleted: int = 0,
    limit: int = 50,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    activate_started_tasks(session)
    safe_limit = max(1, min(limit, 500))
    statement = select(Task)
    if case_id is not None:
        statement = statement.where(Task.case_id == case_id)
    if not include_deleted:
        statement = statement.where(Task.deleted_at.is_(None))
    if status == "open":
        statement = statement.where(Task.status.in_(OPEN_TASK_STATUSES))
    elif status != "all":
        validate_task_status(status)
        statement = statement.where(Task.status == status)
    now = jst_now()
    today_prefix = now.date().isoformat()
    if due == "overdue":
        statement = statement.where(Task.due_at.is_not(None)).where(Task.due_at < now.isoformat())
    elif due == "today":
        statement = statement.where(Task.due_at.is_not(None)).where(Task.due_at.like(f"{today_prefix}%"))
    elif due == "none":
        statement = statement.where(Task.due_at.is_(None))
    elif due not in {"all", "week"}:
        raise json_error(400, "INVALID_DUE_FILTER", "Invalid due filter.")
    elif due == "week":
        week_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        week_end = week_end.fromordinal(now.toordinal() + 7).replace(tzinfo=now.tzinfo)
        statement = statement.where(Task.due_at.is_not(None)).where(Task.due_at <= week_end.isoformat())
    statement = statement.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.updated_at.desc())
    tasks = session.scalars(statement.limit(safe_limit)).all()
    case_ids = {task.case_id for task in tasks}
    cases_by_id = {
        case.id: case
        for case in session.scalars(
            select(Case).where(Case.id.in_(case_ids))
        ).all()
    } if case_ids else {}
    directory_ids = {
        task.storage_directory_id
        for task in tasks
        if task.storage_directory_id is not None
    }
    directories_by_id = {
        directory.id: directory
        for directory in session.scalars(
            select(StorageDirectory).where(StorageDirectory.id.in_(directory_ids))
        ).all()
    } if directory_ids else {}
    items = [
        task_data(
            task,
            session,
            case_cache=cases_by_id,
            directory_cache=directories_by_id,
            ensure_storage=False,
        )
        for task in tasks
    ]
    session.commit()
    return {
        "ok": True,
        "data": {"items": items},
    }


@router.get("/{task_id}")
def get_task(
    task_id: str,
    include_deleted: int = 0,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    activate_started_tasks(session)
    task = ensure_task_exists(session, task_id, include_deleted=bool(include_deleted))
    data = task_data(
        task,
        session,
        include_links=True,
        include_progress_entries=True,
        include_subtasks=True,
    )
    session.commit()
    return {"ok": True, "data": {"task": data}}


@router.post("")
def create_task(
    payload: TaskCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    case = ensure_case_exists(session, payload.case_id)
    if case.archived_at is not None:
        raise json_error(409, "CASE_ARCHIVED", "Cannot create Task in archived Case.")
    validate_source_type(payload.source_type)
    validate_task_priority(payload.priority)
    (
        recurrence_rule_type,
        recurrence_month_day,
        recurrence_year_month,
        recurrence_month_week,
        recurrence_month_weekday,
        recurrence_weekdays,
        recurrence_start_offset_days,
    ) = validate_recurrence_settings(
        rule_type=payload.recurrence_rule_type,
        month_day=payload.recurrence_month_day,
        year_month=payload.recurrence_year_month,
        month_week=payload.recurrence_month_week,
        month_weekday=payload.recurrence_month_weekday,
        weekdays=payload.recurrence_weekdays,
        start_offset_days=payload.recurrence_start_offset_days,
    )
    validate_parent_task(
        session,
        parent_task_id=payload.parent_task_id,
        case_id=case.id,
    )
    now = jst_iso()
    task_id = new_id("task")
    task = Task(
        id=task_id,
        case_id=case.id,
        storage_directory_id=None,
        parent_task_id=payload.parent_task_id,
        title=payload.title.strip(),
        description=normalize_optional_text(payload.description),
        done_when_text=normalize_optional_text(payload.done_when_text),
        progress_memo=normalize_optional_text(payload.progress_memo),
        status="not_started",
        priority=payload.priority,
        start_at=normalize_optional_text(payload.start_at),
        due_at=normalize_optional_text(payload.due_at),
        estimate_minutes=payload.estimate_minutes,
        recurrence_rule_type=recurrence_rule_type,
        recurrence_month_day=recurrence_month_day,
        recurrence_year_month=recurrence_year_month,
        recurrence_month_week=recurrence_month_week,
        recurrence_month_weekday=recurrence_month_weekday,
        recurrence_weekdays_json=json.dumps(recurrence_weekdays) if recurrence_weekdays else None,
        recurrence_start_offset_days=recurrence_start_offset_days,
        recurrence_series_id=None,
        recurrence_sequence=0,
        scheduled_minutes=0,
        worked_minutes=0,
        source_type=payload.source_type,
        source_id=normalize_optional_text(payload.source_id),
        completed_at=None,
        canceled_at=None,
        canceled_reason=None,
        deleted_at=None,
        deleted_reason=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    fill_missing_recurrence_dates(task)
    sync_open_task_status_from_start(session, task)
    ensure_task_storage_directory(session, task, now=now)
    case.updated_at = now
    case.version += 1
    session.add(task)
    if task.source_type == "mail":
        ensure_task_mail_link(session, task=task, message_id=task.source_id, now=now)
    session.commit()
    return {"ok": True, "data": {"task": task_data(task, session, include_links=True)}}


@router.post("/{task_id}/progress-entries")
def create_task_progress_entry(
    task_id: str,
    payload: TaskProgressEntryCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    if task.status not in PROGRESS_TASK_STATUSES:
        raise json_error(409, "TASK_CLOSED", "Cannot append progress memo to closed Task.")
    body = payload.body.strip()
    if body == "":
        raise json_error(422, "VALIDATION_ERROR", "Progress memo cannot be empty.")
    now = jst_iso()
    entry = TaskProgressEntry(
        id=new_id("task_progress"),
        task_id=task.id,
        body=body,
        created_at=now,
    )
    session.add(entry)
    task.progress_memo = body
    if task.status == "not_started":
        task.status = "in_progress"
        task.completed_at = None
        task.canceled_at = None
        task.canceled_reason = None
    task.updated_at = now
    task.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "entry": {
                "id": entry.id,
                "task_id": entry.task_id,
                "body": entry.body,
                "created_at": entry.created_at,
            },
            "task": task_data(task, session, include_links=True, include_progress_entries=True),
        },
    }


@router.patch("/{task_id}/progress-entries/{entry_id}")
def update_task_progress_entry(
    task_id: str,
    entry_id: str,
    payload: TaskProgressEntryPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    entry = ensure_task_progress_entry_exists(session, task_id=task.id, entry_id=entry_id)
    body = payload.body.strip()
    if body == "":
        raise json_error(422, "VALIDATION_ERROR", "Progress memo cannot be empty.")
    now = jst_iso()
    entry.body = body
    if task.status in PROGRESS_TASK_STATUSES:
        task.progress_memo = latest_task_progress_memo(session, task.id)
    task.updated_at = now
    task.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "entry": {
                "id": entry.id,
                "task_id": entry.task_id,
                "body": entry.body,
                "created_at": entry.created_at,
            },
            "task": task_data(task, session, include_links=True, include_progress_entries=True),
        },
    }


@router.delete("/{task_id}/progress-entries/{entry_id}")
def delete_task_progress_entry(
    task_id: str,
    entry_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    entry = ensure_task_progress_entry_exists(session, task_id=task.id, entry_id=entry_id)
    now = jst_iso()
    session.delete(entry)
    session.flush()
    if task.status in PROGRESS_TASK_STATUSES:
        task.progress_memo = latest_task_progress_memo(session, task.id)
    task.updated_at = now
    task.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "deleted": True,
            "task": task_data(task, session, include_links=True, include_progress_entries=True),
        },
    }


@router.patch("/{task_id}")
def update_task(
    task_id: str,
    payload: TaskPatch,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    if payload.base_version is not None and payload.base_version != task.version:
        raise json_error(409, "VERSION_CONFLICT", "Task has been updated.")
    next_case_id = payload.case_id if payload.case_id is not None else task.case_id
    ensure_case_exists(session, next_case_id)
    next_parent_task_id = (
        payload.parent_task_id if "parent_task_id" in payload.model_fields_set else task.parent_task_id
    )
    validate_parent_task(
        session,
        parent_task_id=next_parent_task_id,
        case_id=next_case_id,
        task_id=task.id,
    )
    if payload.status is not None:
        validate_task_status(payload.status)
        if payload.status in {"completed", "canceled", "frozen"}:
            raise json_error(
                400,
                "USE_STATE_ENDPOINT",
                "Use the complete, cancel, freeze, or unfreeze endpoint for Task state changes.",
            )
    if payload.priority is not None:
        validate_task_priority(payload.priority)
    recurrence_fields = {
        "recurrence_rule_type",
        "recurrence_month_day",
        "recurrence_year_month",
        "recurrence_month_week",
        "recurrence_month_weekday",
        "recurrence_weekdays",
        "recurrence_start_offset_days",
    }
    next_recurrence: tuple[
        str | None,
        int | None,
        int | None,
        int | None,
        int | None,
        list[int],
        int | None,
    ] | None = None
    if recurrence_fields.intersection(payload.model_fields_set):
        current_weekdays = json_int_list(task.recurrence_weekdays_json)
        next_recurrence = validate_recurrence_settings(
            rule_type=(
                payload.recurrence_rule_type
                if "recurrence_rule_type" in payload.model_fields_set
                else task.recurrence_rule_type
            ),
            month_day=(
                payload.recurrence_month_day
                if "recurrence_month_day" in payload.model_fields_set
                else task.recurrence_month_day
            ),
            year_month=(
                payload.recurrence_year_month
                if "recurrence_year_month" in payload.model_fields_set
                else task.recurrence_year_month
            ),
            month_week=(
                payload.recurrence_month_week
                if "recurrence_month_week" in payload.model_fields_set
                else task.recurrence_month_week
            ),
            month_weekday=(
                payload.recurrence_month_weekday
                if "recurrence_month_weekday" in payload.model_fields_set
                else task.recurrence_month_weekday
            ),
            weekdays=(
                payload.recurrence_weekdays
                if "recurrence_weekdays" in payload.model_fields_set
                else current_weekdays
            ),
            start_offset_days=(
                payload.recurrence_start_offset_days
                if "recurrence_start_offset_days" in payload.model_fields_set
                else task.recurrence_start_offset_days
            ),
        )
    now = jst_iso()
    task.case_id = next_case_id
    task.parent_task_id = next_parent_task_id
    if payload.title is not None:
        task.title = payload.title.strip()
    if "description" in payload.model_fields_set:
        task.description = normalize_optional_text(payload.description)
    if "done_when_text" in payload.model_fields_set:
        task.done_when_text = normalize_optional_text(payload.done_when_text)
    if "progress_memo" in payload.model_fields_set:
        task.progress_memo = normalize_optional_text(payload.progress_memo)
        if task.progress_memo is not None and task.status == "not_started":
            task.status = "in_progress"
            task.completed_at = None
            task.canceled_at = None
            task.canceled_reason = None
    if payload.status is not None:
        task.status = payload.status
        task.completed_at = None
        task.canceled_at = None
        task.canceled_reason = None
    if payload.priority is not None:
        task.priority = payload.priority
    should_sync_status_from_start = (
        "start_at" in payload.model_fields_set
        or "case_id" in payload.model_fields_set
        or payload.status is not None
    )
    if "start_at" in payload.model_fields_set:
        task.start_at = normalize_optional_text(payload.start_at)
    if "due_at" in payload.model_fields_set:
        task.due_at = normalize_optional_text(payload.due_at)
    if "estimate_minutes" in payload.model_fields_set:
        task.estimate_minutes = payload.estimate_minutes
    if next_recurrence is not None:
        (
            task.recurrence_rule_type,
            task.recurrence_month_day,
            task.recurrence_year_month,
            task.recurrence_month_week,
            task.recurrence_month_weekday,
            recurrence_weekdays,
            task.recurrence_start_offset_days,
        ) = next_recurrence
        task.recurrence_weekdays_json = (
            json.dumps(recurrence_weekdays) if recurrence_weekdays else None
        )
        if task.recurrence_rule_type is None:
            task.recurrence_series_id = None
            task.recurrence_sequence = 0
    fill_missing_recurrence_dates(task)
    if should_sync_status_from_start:
        sync_open_task_status_from_start(session, task)
    if payload.scheduled_minutes is not None:
        task.scheduled_minutes = payload.scheduled_minutes
    if payload.worked_minutes is not None:
        task.worked_minutes = payload.worked_minutes
    ensure_task_storage_directory(session, task, now=now)
    task.updated_at = now
    task.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {"task": task_data(task, session, include_links=True, include_progress_entries=True)},
    }


@router.post("/{task_id}/freeze")
def freeze_task(
    task_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    if task.status in {"completed", "canceled"}:
        raise json_error(409, "TASK_CLOSED", "Closed Task cannot be frozen.")
    if task.status != "frozen":
        now = jst_iso()
        task.status = "frozen"
        task.completed_at = None
        task.canceled_at = None
        task.canceled_reason = None
        task.updated_at = now
        task.version += 1
        session.commit()
    return {
        "ok": True,
        "data": {
            "task": task_data(task, session, include_links=True, include_progress_entries=True),
            "optimistic_state": {"status": "frozen"},
        },
    }


@router.post("/{task_id}/unfreeze")
def unfreeze_task(
    task_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    if task.status != "frozen":
        raise json_error(409, "TASK_NOT_FROZEN", "Task is not frozen.")
    now = jst_iso()
    task.status = "not_started" if task_is_waiting_to_start(session, task) else "in_progress"
    task.completed_at = None
    task.canceled_at = None
    task.canceled_reason = None
    task.updated_at = now
    task.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "task": task_data(task, session, include_links=True, include_progress_entries=True),
            "optimistic_state": {"status": task.status},
        },
    }


@router.post("/{task_id}/complete")
def complete_task(
    task_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    if task.status == "frozen":
        raise json_error(409, "TASK_FROZEN", "Unfreeze Task before completing it.")
    if task_has_open_children(session, task.id):
        raise json_error(409, "OPEN_CHILD_TASKS", "Cannot complete Task with open child Tasks.")
    now = jst_iso()
    task.status = "completed"
    task.completed_at = now
    task.canceled_at = None
    task.canceled_reason = None
    if task_has_progress_entries(session, task.id):
        task.progress_memo = None
    next_recurring_task = create_next_recurring_task(session, completed_task=task, now=now)
    ensure_task_storage_directory(session, task, now=now)
    task.updated_at = now
    task.version += 1
    data = task_data(task, session, include_links=True, include_progress_entries=True)
    session.commit()
    return {
        "ok": True,
        "data": {
            "task": data,
            "next_recurring_task": task_data(next_recurring_task, session)
            if next_recurring_task is not None
            else None,
            "optimistic_state": {"status": "completed", "completed_at": now},
        },
    }


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    payload: TaskCancelPayload | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    now = jst_iso()
    task.status = "canceled"
    task.canceled_at = now
    task.canceled_reason = normalize_optional_text(payload.reason if payload is not None else None)
    task.completed_at = None
    task.updated_at = now
    task.version += 1
    data = task_data(task, session, include_links=True, include_progress_entries=True)
    session.commit()
    return {
        "ok": True,
        "data": {
            "task": data,
            "optimistic_state": {"status": "canceled", "canceled_at": now},
        },
    }


@router.post("/{task_id}/delete")
def delete_task(
    task_id: str,
    payload: TaskDeletePayload | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id)
    now = jst_iso()
    task.deleted_at = now
    task.deleted_reason = normalize_optional_text(payload.reason if payload is not None else None)
    if task.storage_directory_id is not None:
        directory = session.get(StorageDirectory, task.storage_directory_id)
        if directory is not None and directory.status == "active":
            directory.status = "deleted"
            directory.updated_at = now
            directory.version += 1
    task.updated_at = now
    task.version += 1
    data = task_data(task, session)
    session.commit()
    return {"ok": True, "data": {"deleted": True, "task": data}}


@router.post("/{task_id}/restore")
def restore_task(
    task_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    task = ensure_task_exists(session, task_id, include_deleted=True)
    now = jst_iso()
    task.deleted_at = None
    task.deleted_reason = None
    task.updated_at = now
    task.version += 1
    data = task_data(task, session)
    session.commit()
    return {"ok": True, "data": {"task": data}}
