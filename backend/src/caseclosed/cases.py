from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import update
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import Case
from caseclosed.db.models import CaseEvent
from caseclosed.db.models import CaseGenre
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import CaseStakeholder
from caseclosed.db.models import CaseToolLink
from caseclosed.db.models import Contact
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailUserState
from caseclosed.db.runtime import case_storage_directory_id
from caseclosed.db.runtime import ensure_case_storage_directory
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/cases", tags=["cases"])

CASE_PROGRESS_STATUSES = {
    "not_started",
    "in_progress",
    "waiting",
    "blocked",
    "completed",
}
CASE_BALL_STATUSES = {"user", "other", "date_wait", "stalled", "none"}
CASE_STAKEHOLDER_ROLES = {"owner", "collaborator", "reviewer", "stakeholder"}


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
            select(func.count(CaseMailLink.id)).where(CaseMailLink.case_id == case.id)
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
    return [
        case_mail_link_data(link, message, user_state, auto_state, summary)
        for link, message, user_state, auto_state, summary in rows
    ]


def case_event_data(event: CaseEvent) -> dict[str, object]:
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
        "metadata": {},
    }


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
            "recent_events": [case_event_data(event) for event in events],
        },
    }


@router.get("/{case_id}/mail-links")
def list_case_mail_links(
    case_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    ensure_case_exists(session, case_id)
    return {"ok": True, "data": {"items": case_mail_link_items(session, case_id)}}


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
    if payload.role not in CASE_STAKEHOLDER_ROLES:
        raise json_error(422, "VALIDATION_ERROR", "Unsupported stakeholder role.")
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
        role=payload.role,
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
        if payload.role not in CASE_STAKEHOLDER_ROLES:
            raise json_error(422, "VALIDATION_ERROR", "Unsupported stakeholder role.")
        stakeholder.role = payload.role
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
