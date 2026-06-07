from __future__ import annotations

import json
from uuid import uuid4

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
from caseclosed.db.models import CaseGenre
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import CaseStakeholder
from caseclosed.db.models import CaseToolLink
from caseclosed.db.models import Contact
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
from caseclosed.db.runtime import case_storage_directory_id
from caseclosed.db.runtime import ensure_case_storage_directory
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_email_address
from caseclosed.services.llm_provider import build_case_current_situation_provider
from caseclosed.storage import record_storage_operation
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
    progress_status: str = "not_started"
    ball_status: str = "none"
    genre_id: str | None = None


class CaseUpdate(BaseModel):
    description: str | None = None
    open_when_text: str | None = None
    closed_when_text: str | None = None
    tags: list[str] | None = None


class CaseGenreCreate(BaseModel):
    title: str
    color_hex: str = Field(default="#ffffff")


class CaseGenreUpdate(BaseModel):
    title: str | None = None
    color_hex: str | None = None


class CaseStakeholderCreate(BaseModel):
    contact_id: str
    role: str = "stakeholder"


class CaseAutoAssignRuleCreate(BaseModel):
    sender_email: str = Field(min_length=1)
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


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_stakeholder_role(role: str | None) -> str:
    normalized = (role or "").strip()
    return normalized or "stakeholder"


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


def genre_data(genre: CaseGenre) -> dict[str, object]:
    return {
        "id": genre.id,
        "title": genre.title,
        "color_hex": genre.color_hex,
        "created_at": genre.created_at,
        "updated_at": genre.updated_at,
        "version": genre.version,
    }


def case_data(case: Case, session: DatabaseSession | None = None) -> dict[str, object]:
    mail_count = 0
    if session is not None:
        mail_count = session.scalar(
            select(func.count(func.distinct(GmailMessage.thread_id)))
            .select_from(CaseMailLink)
            .join(GmailMessage, GmailMessage.id == CaseMailLink.message_id)
            .where(CaseMailLink.case_id == case.id)
        ) or 0
    return {
        "id": case.id,
        "genre_id": case.genre_id,
        "name": case.name,
        "description": case.description,
        "open_when_text": case.open_when_text,
        "closed_when_text": case.closed_when_text,
        "progress_status": case.progress_status,
        "ball_status": case.ball_status,
        "closed_at": case.closed_at,
        "archived_at": case.archived_at,
        "is_system_case": bool(case.is_system_case),
        "system_case_key": case.system_case_key,
        "tags": case_tags(case),
        "mail_count": mail_count,
        "open_task_count": 0,
        "overdue_task_count": 0,
        "file_count": 0,
        "storage_directory_id": case_storage_directory_id(case.id),
        "next_task": None,
        "next_calendar_event": None,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "version": case.version,
    }


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


def case_auto_assign_rule_data(rule: CaseAutoAssignRule) -> dict[str, object]:
    return {
        "id": rule.id,
        "case_id": rule.case_id,
        "rule_type": rule.rule_type,
        "rule_value": rule.rule_value,
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
    return [case_auto_assign_rule_data(rule) for rule in rules]


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


def case_stakeholder_data(stakeholder: CaseStakeholder, contact: Contact) -> dict[str, object]:
    return {
        "id": stakeholder.id,
        "case_id": stakeholder.case_id,
        "contact_id": stakeholder.contact_id,
        "contact_display_name": contact.display_name,
        "contact_avatar_url": contact.avatar_url,
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
    return [case_stakeholder_data(stakeholder, contact) for stakeholder, contact in rows]


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


def case_tool_link_data(tool_link: CaseToolLink) -> dict[str, object]:
    return {
        "id": tool_link.id,
        "case_id": tool_link.case_id,
        "url": tool_link.url,
        "icon_label": tool_link.icon_label,
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
    return [case_tool_link_data(tool_link) for tool_link in tool_links]


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
    if status == "user_ball":
        statement = (
            statement.where(Case.closed_at.is_(None))
            .where(Case.archived_at.is_(None))
            .where(Case.ball_status == "user")
        )
    elif status == "waiting":
        statement = (
            statement.where(Case.closed_at.is_(None))
            .where(Case.archived_at.is_(None))
            .where(Case.ball_status != "user")
        )
    elif status == "completed":
        statement = statement.where(
            (Case.closed_at.is_not(None)) | (Case.archived_at.is_not(None))
        )
    elif status == "open":
        statement = statement.where(Case.closed_at.is_(None)).where(
            Case.archived_at.is_(None)
        )
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
    return {"ok": True, "data": {"items": [case_data(case, session) for case in cases]}}


@router.get("/genres")
def list_case_genres(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    genres = session.scalars(
        select(CaseGenre).order_by(CaseGenre.title.asc(), CaseGenre.created_at.asc())
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
    genre = CaseGenre(
        id=new_id("case_genre"),
        title=title,
        color_hex=normalize_genre_color(payload.color_hex),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(genre)
    session.commit()
    return {"ok": True, "data": {"genre": genre_data(genre)}}


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

    genre.updated_at = jst_iso()
    genre.version += 1
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
    session.execute(update(Case).where(Case.genre_id == genre.id).values(genre_id=None))
    session.delete(genre)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


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
            "tasks": [],
            "calendar_events": [],
            "contacts": [],
            "files": [],
            "stakeholders": stakeholder_items(session, case.id),
            "tool_links": tool_link_items(session, case.id),
            "current_situation": case_context_version_data(
                latest_case_context_version(session, case.id)
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
    provider_response = provider.complete_json(
        function_type="case_current_situation_summary",
        input_payload=input_payload,
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
        applied_instruction_rule_ids_json=json.dumps([], ensure_ascii=True),
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
    sender_email = normalize_email_address(payload.sender_email)
    if sender_email == "" or "@" not in sender_email:
        raise json_error(422, "VALIDATION_ERROR", "Sender email is invalid.")
    existing = session.scalar(
        select(CaseAutoAssignRule)
        .where(CaseAutoAssignRule.case_id == case_id)
        .where(CaseAutoAssignRule.rule_type == "sender_email")
        .where(CaseAutoAssignRule.rule_value == sender_email)
        .limit(1)
    )
    if existing is not None:
        raise json_error(409, "CONFLICT", "Auto assign rule already exists.")
    now = jst_iso()
    rule = CaseAutoAssignRule(
        id=new_id("case_auto_assign_rule"),
        case_id=case_id,
        rule_type="sender_email",
        rule_value=sender_email,
        label=(payload.label.strip() if payload.label and payload.label.strip() else None),
        is_enabled=1,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(rule)
    session.commit()
    return {"ok": True, "data": {"rule": case_auto_assign_rule_data(rule)}}


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
    return {"ok": True, "data": {"stakeholder": case_stakeholder_data(stakeholder, contact)}}


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
    return {"ok": True, "data": {"stakeholder": case_stakeholder_data(stakeholder, contact)}}


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
    icon_label = (payload.icon_label or tool_icon_label_from_url(url)).strip().upper()[:4]
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
    return {"ok": True, "data": {"tool_link": case_tool_link_data(tool_link)}}


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

    case.description = normalized_optional_text(payload.description)
    case.open_when_text = normalized_optional_text(payload.open_when_text)
    case.closed_when_text = normalized_optional_text(payload.closed_when_text)
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
    if payload.ball_status not in CASE_BALL_STATUSES:
        raise json_error(422, "VALIDATION_ERROR", "Unsupported ball status.")
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
        open_when_text=None,
        closed_when_text=None,
        progress_status=payload.progress_status,
        ball_status=payload.ball_status,
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
