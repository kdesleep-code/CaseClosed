from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
from datetime import datetime
import hashlib
import json
import re
import secrets
import uuid
from datetime import timedelta
from email.utils import getaddresses
from email.utils import parseaddr
from urllib.parse import urlencode
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import unquote_plus
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import AppSetting
from caseclosed.db.models import Case
from caseclosed.db.models import CalendarEvent
from caseclosed.db.models import CalendarEventLink
from caseclosed.db.models import ExternalOperation
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSummary
from caseclosed.db.models import MailThreadSummary
from caseclosed.db.models import Task
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import JST
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import parse_iso_datetime
from caseclosed.services.background_worker import kick_job_drain
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MailAttachmentInput
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.services.llm_provider import FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION
from caseclosed.services.llm_provider import OpenAIProviderError
from caseclosed.services.llm_provider import llm_applied_instruction_rule_ids
from caseclosed.services.llm_provider import with_llm_personalization
from caseclosed.services.llm_provider import build_calendar_event_prefill_provider
from caseclosed.services.mail_thread_summary import split_quoted_reply_sections
from caseclosed.services.mail_attachment_visibility import (
    is_probable_generated_inline_image,
)
from caseclosed.settings import get_google_gmail_scopes
from caseclosed.settings import get_google_oauth_client_id
from caseclosed.settings import get_google_oauth_client_secret
from caseclosed.settings import get_google_oauth_redirect_uri

router = APIRouter(prefix="/api/v1/google/gmail", tags=["google-gmail"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"
GMAIL_CONNECTION_KEY = "google_gmail_oauth_connection"
GMAIL_OAUTH_STATE_KEY = "google_gmail_oauth_state"
GMAIL_AUTO_IMPORT_SETTINGS_KEY = "google_gmail_auto_import_settings"
CALENDAR_AUTO_SYNC_SETTINGS_KEY = "google_calendar_auto_sync_settings"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GMAIL_IMPORT_BY_DATE_MAX_RESULTS = 500
GMAIL_AUTO_IMPORT_DEFAULT_INTERVAL_MINUTES = 10
GMAIL_AUTO_IMPORT_MAX_MESSAGES_PER_RUN = 100
GMAIL_AUTO_IMPORT_SCAN_MAX_MESSAGES = 300
GMAIL_AUTO_IMPORT_LOOKBACK_DAYS = 3
GMAIL_EXCLUDED_IMPORT_QUERY = "-in:drafts"
CALENDAR_AUTO_SYNC_DEFAULT_INTERVAL_MINUTES = 60
CALENDAR_AUTO_SYNC_DEFAULT_MONTH_COUNT = 3
CALENDAR_RRULE_WEEKDAY_INDEX = {
    "SU": 0,
    "MO": 1,
    "TU": 2,
    "WE": 3,
    "TH": 4,
    "FR": 5,
    "SA": 6,
}


class GmailImportByDatePayload(BaseModel):
    date: str


class GmailSpecialImportPayload(BaseModel):
    source: str = Field(min_length=1)


@dataclass(frozen=True)
class GmailAutoImportPlan:
    import_message_ids: list[str]
    unloaded_dates: list[str]
    reached_loaded_message: bool
    checked_count: int
    stop_reason: str
    stopped_gmail_message_id: str | None = None
    stopped_received_at: str | None = None


class GmailAutoImportSettingsPayload(BaseModel):
    enabled: bool
    interval_minutes: int
    max_messages_per_run: int | None = None


class CalendarAutoSyncSettingsPayload(BaseModel):
    enabled: bool
    interval_minutes: int
    calendar_ids: list[str] | None = None
    month_count: int | None = None


class GoogleOAuthConnectUrlPayload(BaseModel):
    frontend_origin: str | None = None


class GoogleCalendarEventCreatePayload(BaseModel):
    summary: str = Field(min_length=1)
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    calendar_id: str = "primary"
    description: str | None = None
    location: str | None = None
    recurrence_rule: str | None = None
    time_zone: str = "Asia/Tokyo"
    linked_mail_message_id: str | None = None
    linked_case_id: str | None = None
    academic_series_id: str | None = None
    attendance_requirement: str | None = None


class CalendarEventMovePayload(BaseModel):
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    time_zone: str = "Asia/Tokyo"


class CalendarEventUpdatePayload(BaseModel):
    summary: str | None = None
    calendar_id: str | None = None
    location: str | None = None
    attendance_requirement: str | None = None
    moving: bool | None = None


class CalendarEventTitleFitPayload(BaseModel):
    title: str = Field(min_length=1)
    font_size_px: float = Field(gt=0)
    line_height: float = Field(gt=0)
    line_clamp: int = Field(ge=1)
    measured_width: float = Field(ge=0)
    measured_height: float = Field(ge=0)


CALENDAR_WEEK_TITLE_FIT_VERSION = 2
CALENDAR_MOVING_TAG = "calendar:moving"


def calendar_event_tags(event: CalendarEvent) -> list[str]:
    if event.tags_json is None or event.tags_json.strip() == "":
        return []
    try:
        parsed = json.loads(event.tags_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    tags: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        tag = item.strip()
        if tag != "" and tag not in tags:
            tags.append(tag)
    return tags


def set_calendar_event_tag(event: CalendarEvent, tag: str, enabled: bool) -> bool:
    tags = calendar_event_tags(event)
    next_tags = [existing for existing in tags if existing != tag]
    if enabled:
        next_tags.append(tag)
    if next_tags == tags:
        return False
    event.tags_json = json.dumps(next_tags, ensure_ascii=False) if next_tags else None
    return True


def calendar_event_is_moving(event: CalendarEvent) -> bool:
    return CALENDAR_MOVING_TAG in calendar_event_tags(event)


def set_calendar_event_moving(event: CalendarEvent, enabled: bool) -> bool:
    return set_calendar_event_tag(event, CALENDAR_MOVING_TAG, enabled)


def clear_calendar_event_moving_after_time_change(event: CalendarEvent) -> bool:
    changed = set_calendar_event_moving(event, False)
    if event.attendance_requirement != "required":
        event.attendance_requirement = "required"
        changed = True
    return changed


class CalendarEventFromMailPrefillPayload(BaseModel):
    message_id: str = Field(min_length=1)
    case_id: str | None = None
    prompt: str | None = None


class GoogleCalendarSyncPayload(BaseModel):
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])
    base_date: str | None = None
    month_count: int = 3


class CalendarEventLinkPayload(BaseModel):
    linked_type: str = Field(min_length=1)
    linked_id: str = Field(min_length=1)
    role: str = "related"


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


def google_gmail_status_data(session: DatabaseSession) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    auto_import_settings = google_gmail_auto_import_settings_data(session)
    calendar_auto_sync_settings = google_calendar_auto_sync_settings_data(session)
    scopes = get_google_gmail_scopes()
    has_refresh_token = bool(connection.get("refresh_token"))
    connected = has_refresh_token or bool(connection.get("access_token"))
    connected_scopes = connection_scopes(connection) or scopes
    return {
        "configured": get_google_oauth_client_id() is not None
        and get_google_oauth_client_secret() is not None,
        "connected": connected,
        "connected_at": connection.get("connected_at"),
        "last_error": connection.get("last_error"),
        "scopes": connected_scopes,
        "send_enabled": GMAIL_SEND_SCOPE in connected_scopes,
        "calendar_read_enabled": CALENDAR_READ_SCOPE in connected_scopes
        or CALENDAR_EVENTS_SCOPE in connected_scopes,
        "calendar_write_enabled": CALENDAR_EVENTS_SCOPE in connected_scopes,
        "redirect_uri": get_google_oauth_redirect_uri(),
        "has_refresh_token": has_refresh_token,
        "token_expires_at": connection.get("token_expires_at"),
        "mail_loading_enabled": connected and bool(auto_import_settings["enabled"]),
        "auto_import": auto_import_settings,
        "calendar_auto_sync": calendar_auto_sync_settings,
    }


def google_gmail_auto_import_settings_data(
    session: DatabaseSession,
) -> dict[str, object]:
    settings = read_setting_json(session, GMAIL_AUTO_IMPORT_SETTINGS_KEY) or {}
    interval_minutes = normalized_auto_import_interval_minutes(
        settings.get("interval_minutes")
    )
    return {
        "enabled": bool(settings.get("enabled", True)),
        "interval_minutes": interval_minutes,
        "max_messages_per_run": normalized_auto_import_max_messages(
            settings.get("max_messages_per_run")
        ),
        "last_run_at": optional_string(settings.get("last_run_at")),
        "last_success_at": optional_string(settings.get("last_success_at")),
        "last_error": optional_string(settings.get("last_error")),
        "last_imported_count": int(settings.get("last_imported_count") or 0),
        "last_checked_count": int(settings.get("last_checked_count") or 0),
        "last_stop_reason": optional_string(settings.get("last_stop_reason")),
        "last_stopped_gmail_message_id": optional_string(
            settings.get("last_stopped_gmail_message_id")
        ),
        "last_stopped_received_at": optional_string(
            settings.get("last_stopped_received_at")
        ),
        "last_reached_loaded_message": bool(
            settings.get("last_reached_loaded_message", False)
        ),
        "unloaded_dates": normalized_date_list(settings.get("unloaded_dates")),
        "updated_at": optional_string(settings.get("updated_at")),
    }


def normalized_auto_import_interval_minutes(value: object) -> int:
    try:
        interval_minutes = int(value)
    except (TypeError, ValueError):
        interval_minutes = GMAIL_AUTO_IMPORT_DEFAULT_INTERVAL_MINUTES
    return max(1, min(interval_minutes, 24 * 60))


def normalized_auto_import_max_messages(value: object) -> int:
    try:
        max_messages = int(value)
    except (TypeError, ValueError):
        max_messages = GMAIL_AUTO_IMPORT_MAX_MESSAGES_PER_RUN
    return max(1, min(max_messages, GMAIL_AUTO_IMPORT_MAX_MESSAGES_PER_RUN))


def optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() != "" else None


def normalized_date_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    dates = []
    for item in value:
        if isinstance(item, str) and len(item) == 10:
            try:
                datetime.strptime(item, "%Y-%m-%d")
            except ValueError:
                continue
            dates.append(item)
    return sorted(set(dates), reverse=True)


def write_google_gmail_auto_import_settings(
    session: DatabaseSession,
    *,
    enabled: bool,
    interval_minutes: int,
    max_messages_per_run: int | None = None,
) -> dict[str, object]:
    now = jst_iso()
    current = google_gmail_auto_import_settings_data(session)
    next_settings = {
        **current,
        "enabled": enabled,
        "interval_minutes": normalized_auto_import_interval_minutes(interval_minutes),
        "max_messages_per_run": normalized_auto_import_max_messages(
            max_messages_per_run
            if max_messages_per_run is not None
            else current.get("max_messages_per_run")
        ),
        "updated_at": now,
    }
    write_setting_json(session, GMAIL_AUTO_IMPORT_SETTINGS_KEY, next_settings, now)
    session.commit()
    return google_gmail_auto_import_settings_data(session)


def google_calendar_auto_sync_settings_data(
    session: DatabaseSession,
) -> dict[str, object]:
    settings = read_setting_json(session, CALENDAR_AUTO_SYNC_SETTINGS_KEY) or {}
    return {
        "enabled": bool(settings.get("enabled", True)),
        "interval_minutes": normalized_calendar_auto_sync_interval_minutes(
            settings.get("interval_minutes")
        ),
        "calendar_ids": normalized_calendar_ids(settings.get("calendar_ids"))
        or ["primary"],
        "month_count": normalized_calendar_auto_sync_month_count(
            settings.get("month_count")
        ),
        "last_run_at": optional_string(settings.get("last_run_at")),
        "last_success_at": optional_string(settings.get("last_success_at")),
        "last_error": optional_string(settings.get("last_error")),
        "last_imported_count": int(settings.get("last_imported_count") or 0),
        "last_updated_count": int(settings.get("last_updated_count") or 0),
        "last_cancelled_count": int(settings.get("last_cancelled_count") or 0),
        "last_missing_count": int(settings.get("last_missing_count") or 0),
        "last_time_min": optional_string(settings.get("last_time_min")),
        "last_time_max": optional_string(settings.get("last_time_max")),
        "last_stop_reason": optional_string(settings.get("last_stop_reason")),
        "updated_at": optional_string(settings.get("updated_at")),
    }


def normalized_calendar_auto_sync_interval_minutes(value: object) -> int:
    try:
        interval_minutes = int(value)
    except (TypeError, ValueError):
        interval_minutes = CALENDAR_AUTO_SYNC_DEFAULT_INTERVAL_MINUTES
    return max(5, min(interval_minutes, 24 * 60))


def normalized_calendar_auto_sync_month_count(value: object) -> int:
    try:
        month_count = int(value)
    except (TypeError, ValueError):
        month_count = CALENDAR_AUTO_SYNC_DEFAULT_MONTH_COUNT
    return max(1, min(month_count, 12))


def write_google_calendar_auto_sync_settings(
    session: DatabaseSession,
    *,
    enabled: bool,
    interval_minutes: int,
    calendar_ids: list[str] | None = None,
    month_count: int | None = None,
) -> dict[str, object]:
    now = jst_iso()
    current = google_calendar_auto_sync_settings_data(session)
    next_settings = {
        **current,
        "enabled": enabled,
        "interval_minutes": normalized_calendar_auto_sync_interval_minutes(
            interval_minutes
        ),
        "calendar_ids": normalized_calendar_ids(calendar_ids)
        or normalized_calendar_ids(current.get("calendar_ids"))
        or ["primary"],
        "month_count": normalized_calendar_auto_sync_month_count(
            month_count if month_count is not None else current.get("month_count")
        ),
        "updated_at": now,
    }
    write_setting_json(session, CALENDAR_AUTO_SYNC_SETTINGS_KEY, next_settings, now)
    session.commit()
    return google_calendar_auto_sync_settings_data(session)


def google_oauth_redirect_uri(frontend_origin: str | None) -> str:
    fallback = get_google_oauth_redirect_uri()
    if frontend_origin is None or frontend_origin.strip() == "":
        return fallback
    parsed = urlparse(frontend_origin.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
        raise json_error(422, "VALIDATION_ERROR", "frontend_origin must be an http(s) origin.")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise json_error(422, "VALIDATION_ERROR", "frontend_origin must not include a path, query, or fragment.")
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/google/gmail/oauth/callback"


def create_calendar_external_operation(
    session: DatabaseSession,
    *,
    operation_type: str,
    payload: dict[str, object],
) -> ExternalOperation:
    now = jst_iso()
    payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    operation = ExternalOperation(
        id=f"external_operation_{uuid.uuid4().hex}",
        operation_type=operation_type,
        status="pending",
        idempotency_key=f"{operation_type}:{uuid.uuid4().hex}",
        request_payload_hash=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        request_payload_json=payload_json,
        external_service="google_calendar",
        external_id=None,
        attempt_count=1,
        last_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(operation)
    session.flush()
    return operation


def mark_calendar_external_operation_succeeded(
    operation: ExternalOperation,
    *,
    external_id: str | None,
) -> None:
    now = jst_iso()
    operation.status = "succeeded"
    operation.external_id = external_id
    operation.succeeded_at = now
    operation.updated_at = now


def mark_calendar_external_operation_failed(
    operation: ExternalOperation,
    *,
    error: Exception,
) -> None:
    now = jst_iso()
    operation.status = "failed"
    operation.failed_at = now
    operation.updated_at = now
    operation.unknown_reason = str(error)


def mark_calendar_external_operation_unknown(
    operation: ExternalOperation,
    *,
    error: Exception,
) -> None:
    now = jst_iso()
    operation.status = "unknown"
    operation.unknown_at = now
    operation.unknown_reason = str(error)
    operation.manual_resolution_required = 1
    operation.updated_at = now


def mark_calendar_external_operation_error(
    session: DatabaseSession,
    operation: ExternalOperation,
    error: Exception,
) -> None:
    if isinstance(error, HTTPException) and error.status_code < 500:
        mark_calendar_external_operation_failed(operation, error=error)
    else:
        mark_calendar_external_operation_unknown(operation, error=error)
    session.commit()


def connection_scopes(connection: dict[str, object]) -> list[str]:
    scopes = connection.get("scopes")
    if isinstance(scopes, list):
        return [scope for scope in scopes if isinstance(scope, str)]
    scope_text = connection.get("scope")
    if isinstance(scope_text, str):
        return [scope for scope in scope_text.split() if scope.strip() != ""]
    return []


def gmail_connection_send_state(
    session: DatabaseSession,
) -> tuple[bool, bool]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected = bool(connection.get("refresh_token")) or bool(connection.get("access_token"))
    if not connected:
        return False, False
    return True, GMAIL_SEND_SCOPE in connection_scopes(connection)


def calendar_connection_state(
    session: DatabaseSession,
) -> tuple[bool, bool, bool]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected = bool(connection.get("refresh_token")) or bool(connection.get("access_token"))
    if not connected:
        return False, False, False
    scopes = connection_scopes(connection)
    can_read = CALENDAR_READ_SCOPE in scopes or CALENDAR_EVENTS_SCOPE in scopes
    can_write = CALENDAR_EVENTS_SCOPE in scopes
    return True, can_read, can_write


def mail_ingestion_result_data(result: MailIngestionResult) -> dict[str, object]:
    return {
        "message_id": result.message_id,
        "gmail_message_id": result.gmail_message_id,
        "pending": result.pending,
        "pending_address": result.pending_address,
        "pending_reason": result.pending_reason,
        "queued_job_id": result.queued_job_id,
        "queued_contact_ai_memo_job_id": result.queued_contact_ai_memo_job_id,
    }


@router.get("/status")
def google_gmail_status(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {"ok": True, "data": google_gmail_status_data(session)}


@router.patch("/auto-import-settings")
def update_google_gmail_auto_import_settings(
    payload: GmailAutoImportSettingsPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    settings = write_google_gmail_auto_import_settings(
        session,
        enabled=payload.enabled,
        interval_minutes=payload.interval_minutes,
        max_messages_per_run=payload.max_messages_per_run,
    )
    return {"ok": True, "data": settings}


@router.patch("/calendar/auto-sync-settings")
def update_google_calendar_auto_sync_settings(
    payload: CalendarAutoSyncSettingsPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    settings = write_google_calendar_auto_sync_settings(
        session,
        enabled=payload.enabled,
        interval_minutes=payload.interval_minutes,
        calendar_ids=payload.calendar_ids,
        month_count=payload.month_count,
    )
    return {"ok": True, "data": settings}


@router.post("/connect-url")
def google_gmail_connect_url(
    payload: GoogleOAuthConnectUrlPayload | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    client_id = get_google_oauth_client_id()
    client_secret = get_google_oauth_client_secret()
    if client_id is None or client_secret is None:
        raise json_error(
            409,
            "GOOGLE_OAUTH_NOT_CONFIGURED",
            "Google OAuth client id and secret are not configured.",
        )

    now = jst_iso()
    state = secrets.token_urlsafe(32)
    redirect_uri = google_oauth_redirect_uri(
        payload.frontend_origin if payload is not None else None
    )
    write_setting_json(
        session,
        GMAIL_OAUTH_STATE_KEY,
        {"state": state, "redirect_uri": redirect_uri, "created_at": now},
        now,
    )
    session.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(get_google_gmail_scopes()),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return {
        "ok": True,
        "data": {
            "authorization_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
            "mail_loading_enabled": False,
        },
    }


@router.get("/oauth/callback")
def google_gmail_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> RedirectResponse:
    now = jst_iso()
    if error is not None:
        write_setting_json(
            session,
            GMAIL_CONNECTION_KEY,
            {"last_error": error, "updated_at": now},
            now,
        )
        session.commit()
        return RedirectResponse("/settings?google_gmail=error")

    stored_state = read_setting_json(session, GMAIL_OAUTH_STATE_KEY)
    if (
        code is None
        or state is None
        or stored_state is None
        or stored_state.get("state") != state
    ):
        write_setting_json(
            session,
            GMAIL_CONNECTION_KEY,
            {"last_error": "Invalid OAuth callback state.", "updated_at": now},
            now,
        )
        session.commit()
        return RedirectResponse("/settings?google_gmail=error")

    redirect_uri = str(stored_state.get("redirect_uri") or get_google_oauth_redirect_uri())
    token_data = exchange_authorization_code(code, redirect_uri=redirect_uri)
    expires_in = int(token_data.get("expires_in", 0) or 0)
    token_expires_at = (
        jst_now() + timedelta(seconds=expires_in)
    ).isoformat() if expires_in > 0 else None
    write_setting_json(
        session,
        GMAIL_CONNECTION_KEY,
        {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "scope": token_data.get("scope"),
            "scopes": get_google_gmail_scopes(),
            "token_type": token_data.get("token_type"),
            "token_expires_at": token_expires_at,
            "connected_at": now,
            "updated_at": now,
            "last_error": None,
            "mail_loading_enabled": False,
        },
        now,
    )
    write_setting_json(session, GMAIL_OAUTH_STATE_KEY, {}, now)
    session.commit()
    return RedirectResponse("/settings?google_gmail=connected")


@router.post("/disconnect")
def google_gmail_disconnect(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    write_setting_json(
        session,
        GMAIL_CONNECTION_KEY,
        {
            "connected_at": None,
            "updated_at": now,
            "last_error": None,
            "mail_loading_enabled": False,
        },
        now,
    )
    session.commit()
    return {"ok": True, "data": google_gmail_status_data(session)}


@router.get("/calendar/status")
def google_calendar_status(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    status = google_gmail_status_data(session)
    return {
        "ok": True,
        "data": {
            "configured": status["configured"],
            "connected": status["connected"],
            "calendar_read_enabled": status["calendar_read_enabled"],
            "calendar_write_enabled": status["calendar_write_enabled"],
            "scopes": status["scopes"],
            "last_error": status["last_error"],
            "calendar_auto_sync": status["calendar_auto_sync"],
        },
    }


@router.get("/calendar/events")
def google_calendar_events(
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected, can_read, _can_write = calendar_connection_state(session)
    if not connected:
        raise json_error(409, "GOOGLE_CALENDAR_NOT_CONNECTED", "Google Calendar is not connected.")
    if not can_read:
        raise json_error(
            403,
            "GOOGLE_CALENDAR_SCOPE_MISSING",
            "Google Calendar read scope is not granted. Reconnect Google.",
        )
    access_token = google_gmail_access_token(session, connection)
    params: dict[str, object] = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max(1, min(max_results, 100)),
    }
    if time_min is not None and time_min.strip() != "":
        params["timeMin"] = time_min
    else:
        params["timeMin"] = jst_now().isoformat()
    if time_max is not None and time_max.strip() != "":
        params["timeMax"] = time_max
    data = calendar_api_get_json(
        encoded_calendar_path(calendar_id, "/events"),
        access_token,
        params,
    )
    items = data.get("items")
    return {
        "ok": True,
        "data": {
            "items": calendar_event_items(items if isinstance(items, list) else []),
            "calendar_id": calendar_id,
        },
    }


@router.get("/calendar/db-events")
def calendar_db_events(
    calendar_id: list[str] | None = Query(default=None),
    time_min: str | None = None,
    time_max: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    calendar_ids = normalized_calendar_ids(calendar_id)
    statement = select(CalendarEvent).where(CalendarEvent.sync_status != "missing_from_google")
    statement = statement.where(CalendarEvent.sync_status != "cancelled")
    statement = statement.where(
        (CalendarEvent.google_status.is_(None))
        | (CalendarEvent.google_status != "cancelled")
    )
    if calendar_ids:
        statement = statement.where(CalendarEvent.external_calendar_id.in_(calendar_ids))
    if time_min is not None and time_min.strip() != "":
        statement = statement.where(CalendarEvent.end_at > time_min.strip())
    if time_max is not None and time_max.strip() != "":
        statement = statement.where(CalendarEvent.start_at < time_max.strip())
    events = session.scalars(
        statement.order_by(CalendarEvent.start_at.asc(), CalendarEvent.summary.asc())
    ).all()
    events = deduplicated_calendar_events(events)
    return {
        "ok": True,
        "data": {
            "items": [calendar_db_event_item(event) for event in events],
            "calendar_ids": calendar_ids,
        },
    }


def calendar_conflict_item(event: CalendarEvent) -> dict[str, object]:
    return calendar_db_event_item(event)


def calendar_conflict_group_item(
    segment_start: datetime,
    segment_end: datetime,
    events: list[CalendarEvent],
) -> dict[str, object]:
    return {
        "conflict_start": jst_iso(segment_start),
        "conflict_end": jst_iso(segment_end),
        "event_count": len(events),
        "events": [calendar_conflict_item(event) for event in events],
    }


def calendar_conflict_groups(
    events: list[CalendarEvent],
) -> list[tuple[datetime, datetime, list[CalendarEvent]]]:
    boundaries = sorted(
        {
            parse_iso_datetime(event.start_at)
            for event in events
        }
        | {
            parse_iso_datetime(event.end_at)
            for event in events
        }
    )
    groups: list[tuple[datetime, datetime, list[CalendarEvent]]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for index, segment_start in enumerate(boundaries[:-1]):
        segment_end = boundaries[index + 1]
        if segment_end <= segment_start:
            continue
        active = [
            event
            for event in events
            if parse_iso_datetime(event.start_at) < segment_end
            and parse_iso_datetime(event.end_at) > segment_start
        ]
        if len(active) < 2:
            continue
        active = sorted(active, key=lambda event: (event.start_at, event.end_at, event.id))
        key = tuple(event.id for event in active)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        groups.append((segment_start, segment_end, active))
    return groups


@router.get("/calendar/conflicts")
def calendar_conflicts(
    time_min: str | None = None,
    time_max: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    range_start = parse_iso_datetime(time_min) if time_min is not None and time_min.strip() != "" else jst_now()
    range_end = (
        parse_iso_datetime(time_max)
        if time_max is not None and time_max.strip() != ""
        else range_start + timedelta(days=31)
    )
    if range_end <= range_start:
        raise json_error(422, "VALIDATION_ERROR", "time_max must be after time_min.")

    events = session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.sync_status != "missing_from_google")
        .where(CalendarEvent.sync_status != "cancelled")
        .where(
            (CalendarEvent.google_status.is_(None))
            | (CalendarEvent.google_status != "cancelled")
        )
        .where(
            (CalendarEvent.attendance_requirement.is_(None))
            | (~CalendarEvent.attendance_requirement.in_({"optional", "not_required", "unnecessary", "no_attendance"}))
        )
        .where(CalendarEvent.all_day == 0)
        .where(
            (CalendarEvent.tags_json.is_(None))
            | (~CalendarEvent.tags_json.contains(CALENDAR_MOVING_TAG))
        )
        .where(CalendarEvent.end_at > jst_iso(range_start))
        .where(CalendarEvent.start_at < jst_iso(range_end))
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.end_at.asc(), CalendarEvent.summary.asc())
    ).all()
    events = deduplicated_calendar_events(events)
    groups = calendar_conflict_groups(events)
    return {
        "ok": True,
        "data": {
            "time_min": jst_iso(range_start),
            "time_max": jst_iso(range_end),
            "items": [
                calendar_conflict_group_item(segment_start, segment_end, group)
                for segment_start, segment_end, group in groups
            ],
        },
    }


def deduplicated_calendar_events(events: list[CalendarEvent]) -> list[CalendarEvent]:
    selected: dict[tuple[str, str, str], CalendarEvent] = {}
    passthrough: list[CalendarEvent] = []
    for event in events:
        if event.external_event_id is None:
            passthrough.append(event)
            continue
        key = (event.external_event_id, event.start_at, event.end_at)
        current = selected.get(key)
        if current is None or calendar_event_dedup_rank(event) < calendar_event_dedup_rank(current):
            selected[key] = event
    combined = [*passthrough, *selected.values()]
    return sorted(combined, key=lambda event: (event.start_at, event.summary, event.id))


def calendar_event_dedup_rank(event: CalendarEvent) -> tuple[int, str]:
    primary_alias_rank = 1 if event.external_calendar_id == "primary" else 0
    return (primary_alias_rank, event.id)


@router.get("/calendar/db-events/{event_id}")
def calendar_db_event_detail(
    event_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")
    inherit_calendar_event_links_from_recurring_master(session, event=event, now=jst_iso())
    session.commit()
    links = session.scalars(
        select(CalendarEventLink)
        .where(CalendarEventLink.calendar_event_id == event.id)
        .order_by(CalendarEventLink.linked_type.asc(), CalendarEventLink.created_at.asc())
    ).all()
    return {
        "ok": True,
        "data": {
            "event": calendar_db_event_item(event),
            "links": [calendar_event_link_item(session, link) for link in links],
            "mail_summaries": calendar_event_mail_summaries(session, links),
        },
    }


@router.patch("/calendar/db-events/{event_id}")
def update_calendar_db_event(
    event_id: str,
    payload: CalendarEventUpdatePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")

    summary = payload.summary.strip() if payload.summary is not None else None
    if payload.summary is not None and (summary is None or summary == ""):
        raise json_error(422, "VALIDATION_ERROR", "Event title is required.")
    location_was_provided = "location" in payload.model_fields_set
    location = payload.location.strip() if payload.location is not None else None
    if location == "":
        location = None
    attendance_requirement_was_provided = "attendance_requirement" in payload.model_fields_set
    attendance_requirement = (
        payload.attendance_requirement.strip()
        if payload.attendance_requirement is not None
        else None
    )
    if attendance_requirement not in {None, "required", "optional", "not_required"}:
        raise json_error(422, "VALIDATION_ERROR", "Attendance value is invalid.")
    if attendance_requirement == "optional":
        attendance_requirement = "not_required"
    target_calendar_id = payload.calendar_id.strip() if payload.calendar_id is not None else None
    if target_calendar_id == "":
        target_calendar_id = None

    now = jst_iso()
    if event.source == "google":
        connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
        connected, _can_read, can_write = calendar_connection_state(session)
        if not connected:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_NOT_CONNECTED",
                "Google Calendar is not connected.",
            )
        if not can_write:
            raise json_error(
                403,
                "GOOGLE_CALENDAR_SCOPE_MISSING",
                "Google Calendar event scope is not granted. Reconnect Google.",
            )
        if event.external_calendar_id is None or event.external_event_id is None:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_EVENT_NOT_LINKED",
                "Calendar event is not linked to a Google event.",
            )
        access_token = google_gmail_access_token(session, connection)
        calendar_id = event.external_calendar_id
        google_event_id = event.external_event_id
        google_data: dict[str, object] | None = None
        if summary is not None or location_was_provided:
            patch_payload: dict[str, object] = {}
            if summary is not None:
                patch_payload["summary"] = summary
            if location_was_provided:
                patch_payload["location"] = location or ""
            operation = create_calendar_external_operation(
                session,
                operation_type="google_calendar_event_update",
                payload={
                    "calendar_id": calendar_id,
                    "event_id": google_event_id,
                    "payload": patch_payload,
                },
            )
            try:
                google_data = calendar_api_patch_json(
                    encoded_calendar_path(calendar_id, f"/events/{quote(google_event_id, safe='')}"),
                    access_token,
                    patch_payload,
                )
            except Exception as error:
                mark_calendar_external_operation_error(session, operation, error)
                raise
            mark_calendar_external_operation_succeeded(
                operation,
                external_id=google_event_id,
            )
        if target_calendar_id is not None and target_calendar_id != calendar_id:
            move_path = encoded_calendar_path(
                calendar_id,
                f"/events/{quote(google_event_id, safe='')}/move?destination={quote(target_calendar_id, safe='')}",
            )
            operation = create_calendar_external_operation(
                session,
                operation_type="google_calendar_event_calendar_move",
                payload={
                    "calendar_id": calendar_id,
                    "event_id": google_event_id,
                    "target_calendar_id": target_calendar_id,
                },
            )
            try:
                google_data = calendar_api_post_json(
                    move_path,
                    access_token,
                    {},
                )
            except Exception as error:
                mark_calendar_external_operation_error(session, operation, error)
                raise
            mark_calendar_external_operation_succeeded(
                operation,
                external_id=google_event_id,
            )
            calendar_id = target_calendar_id
        if google_data is None:
            google_data = calendar_api_get_json(
                encoded_calendar_path(calendar_id, f"/events/{quote(google_event_id, safe='')}"),
                access_token,
                {},
            )
        db_event = upsert_calendar_event_from_google_response(
            session,
            calendar_id=calendar_id,
            item=google_data,
            now=now,
        )
        if attendance_requirement_was_provided:
            db_event.attendance_requirement = attendance_requirement or "unknown"
            db_event.updated_at = now
            db_event.version += 1
        if payload.moving is not None and set_calendar_event_moving(db_event, payload.moving):
            db_event.updated_at = now
            db_event.version += 1
        session.commit()
        return {
            "ok": True,
            "data": {
                "event": calendar_db_event_item(db_event),
                "google_event": calendar_event_item(google_data),
            },
        }

    if summary is not None:
        event.summary = summary
    if location_was_provided:
        event.location = location
    if target_calendar_id is not None:
        event.external_calendar_id = target_calendar_id
    if attendance_requirement_was_provided:
        event.attendance_requirement = attendance_requirement or "unknown"
    if payload.moving is not None:
        set_calendar_event_moving(event, payload.moving)
    event.updated_at = now
    event.version += 1
    session.commit()
    return {"ok": True, "data": {"event": calendar_db_event_item(event), "google_event": None}}


@router.patch("/calendar/db-events/{event_id}/move")
def move_calendar_db_event(
    event_id: str,
    payload: CalendarEventMovePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")
    if event.all_day:
        raise json_error(
            422,
            "ALL_DAY_EVENT_MOVE_UNSUPPORTED",
            "All-day events cannot be moved from the week grid.",
        )
    if payload.end <= payload.start:
        raise json_error(422, "VALIDATION_ERROR", "Event end must be after start.")

    now = jst_iso()
    if event.source == "google":
        connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
        connected, _can_read, can_write = calendar_connection_state(session)
        if not connected:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_NOT_CONNECTED",
                "Google Calendar is not connected.",
            )
        if not can_write:
            raise json_error(
                403,
                "GOOGLE_CALENDAR_SCOPE_MISSING",
                "Google Calendar event scope is not granted. Reconnect Google.",
            )
        if event.external_calendar_id is None or event.external_event_id is None:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_EVENT_NOT_LINKED",
                "Calendar event is not linked to a Google event.",
            )
        access_token = google_gmail_access_token(session, connection)
        patch_payload = {
            "start": calendar_event_time(payload.start, payload.time_zone),
            "end": calendar_event_time(payload.end, payload.time_zone),
        }
        operation = create_calendar_external_operation(
            session,
            operation_type="google_calendar_event_time_move",
            payload={
                "calendar_id": event.external_calendar_id,
                "event_id": event.external_event_id,
                "payload": patch_payload,
            },
        )
        try:
            data = calendar_api_patch_json(
                encoded_calendar_path(
                    event.external_calendar_id,
                    f"/events/{quote(event.external_event_id, safe='')}",
                ),
                access_token,
                patch_payload,
            )
        except Exception as error:
            mark_calendar_external_operation_error(session, operation, error)
            raise
        mark_calendar_external_operation_succeeded(
            operation,
            external_id=event.external_event_id,
        )
        db_event = upsert_calendar_event_from_google_response(
            session,
            calendar_id=event.external_calendar_id,
            item=data,
            now=now,
        )
        if clear_calendar_event_moving_after_time_change(db_event):
            db_event.updated_at = now
            db_event.version += 1
        session.commit()
        return {
            "ok": True,
            "data": {
                "event": calendar_db_event_item(db_event),
                "google_event": calendar_event_item(data),
            },
        }

    event.start_at = calendar_event_time(payload.start, payload.time_zone)["dateTime"]  # type: ignore[index]
    event.end_at = calendar_event_time(payload.end, payload.time_zone)["dateTime"]  # type: ignore[index]
    event.time_zone = payload.time_zone
    clear_calendar_event_moving_after_time_change(event)
    event.updated_at = now
    event.last_synced_at = now
    event.version += 1
    session.commit()
    return {"ok": True, "data": {"event": calendar_db_event_item(event), "google_event": None}}


@router.delete("/calendar/db-events/{event_id}")
def delete_calendar_db_event(
    event_id: str,
    scope: str = Query("event"),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")
    if scope not in {"event", "series"}:
        raise json_error(422, "INVALID_DELETE_SCOPE", "Delete scope must be event or series.")
    if scope == "series" and not calendar_event_has_series(event):
        raise json_error(409, "CALENDAR_EVENT_SERIES_NOT_FOUND", "Calendar event has no series.")

    now = jst_iso()
    target_events = calendar_event_delete_targets(session, event=event, scope=scope)
    google_delete_targets = calendar_event_google_delete_targets(
        target_events,
        requested_event=event,
        scope=scope,
    )
    if google_delete_targets:
        connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
        connected, _can_read, can_write = calendar_connection_state(session)
        if not connected:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_NOT_CONNECTED",
                "Google Calendar is not connected.",
            )
        if not can_write:
            raise json_error(
                403,
                "GOOGLE_CALENDAR_SCOPE_MISSING",
                "Google Calendar event scope is not granted. Reconnect Google.",
            )
        access_token = google_gmail_access_token(session, connection)
    else:
        access_token = None
    for calendar_id, external_event_id in google_delete_targets:
        operation = create_calendar_external_operation(
            session,
            operation_type="google_calendar_event_delete",
            payload={
                "calendar_id": calendar_id,
                "event_id": external_event_id,
                "scope": scope,
                "requested_event_id": event.id,
            },
        )
        try:
            calendar_api_delete(
                encoded_calendar_path(
                    calendar_id,
                    f"/events/{quote(external_event_id, safe='')}",
                ),
                access_token or "",
            )
        except Exception as error:
            mark_calendar_external_operation_error(session, operation, error)
            raise
        mark_calendar_external_operation_succeeded(
            operation,
            external_id=external_event_id,
        )

    for target_event in target_events:
        target_event.sync_status = "cancelled"
        target_event.google_status = "cancelled"
        target_event.last_synced_at = now
        target_event.updated_at = now
        target_event.version += 1
    session.commit()
    return {
        "ok": True,
        "data": {
            "deleted": True,
            "deleted_count": len(target_events),
            "scope": scope,
            "event": calendar_db_event_item(event),
        },
    }


@router.patch("/calendar/db-events/{event_id}/title-fit")
def update_calendar_db_event_title_fit(
    event_id: str,
    payload: CalendarEventTitleFitPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")
    metadata: dict[str, object] = {}
    if event.metadata_json is not None and event.metadata_json.strip() != "":
        try:
            loaded = json.loads(event.metadata_json)
            if isinstance(loaded, dict):
                metadata = loaded
        except json.JSONDecodeError:
            metadata = {}
    metadata["calendar_week_title_fit"] = {
        "fit_version": CALENDAR_WEEK_TITLE_FIT_VERSION,
        "title": payload.title,
        "font_size_px": payload.font_size_px,
        "line_height": payload.line_height,
        "line_clamp": payload.line_clamp,
        "measured_width": payload.measured_width,
        "measured_height": payload.measured_height,
        "measured_at": jst_iso(),
    }
    event.metadata_json = json.dumps(metadata, ensure_ascii=True, sort_keys=True)
    event.updated_at = jst_iso()
    event.version += 1
    session.commit()
    return {"ok": True, "data": {"event": calendar_db_event_item(event)}}


@router.post("/calendar/db-events/{event_id}/links")
def create_calendar_db_event_link(
    event_id: str,
    payload: CalendarEventLinkPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    event = session.get(CalendarEvent, event_id)
    if (
        event is None
        or event.sync_status in {"missing_from_google", "cancelled"}
        or event.google_status == "cancelled"
    ):
        raise json_error(404, "CALENDAR_EVENT_NOT_FOUND", "Calendar event was not found.")
    linked_type = payload.linked_type.strip().lower()
    linked_id = payload.linked_id.strip()
    role = payload.role.strip() or "related"
    validate_calendar_event_link_target(session, linked_type, linked_id)
    existing = session.scalar(
        select(CalendarEventLink)
        .where(CalendarEventLink.calendar_event_id == event.id)
        .where(CalendarEventLink.linked_type == linked_type)
        .where(CalendarEventLink.linked_id == linked_id)
        .where(CalendarEventLink.role == role)
    )
    if existing is not None:
        return {"ok": True, "data": {"link": calendar_event_link_item(session, existing)}}
    now = jst_iso()
    link = CalendarEventLink(
        id=f"calendar_event_link_{uuid.uuid4().hex}",
        calendar_event_id=event.id,
        linked_type=linked_type,
        linked_id=linked_id,
        role=role,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(link)
    event.updated_at = now
    event.version += 1
    propagate_calendar_event_links_to_recurring_instances(session, master_event=event, now=now)
    session.commit()
    return {"ok": True, "data": {"link": calendar_event_link_item(session, link)}}


@router.delete("/calendar/db-events/{event_id}/links/{link_id}")
def delete_calendar_db_event_link(
    event_id: str,
    link_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    link = session.get(CalendarEventLink, link_id)
    if link is None or link.calendar_event_id != event_id:
        raise json_error(404, "CALENDAR_EVENT_LINK_NOT_FOUND", "Calendar event link was not found.")
    event = session.get(CalendarEvent, event_id)
    session.delete(link)
    if event is not None:
        event.updated_at = jst_iso()
        event.version += 1
    session.commit()
    return {"ok": True, "data": {"deleted": True}}


@router.post("/calendar/sync")
def sync_google_calendar_events(
    payload: GoogleCalendarSyncPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {"ok": True, "data": perform_google_calendar_sync(session, payload)}


def perform_google_calendar_sync(
    session: DatabaseSession,
    payload: GoogleCalendarSyncPayload,
) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected, can_read, _can_write = calendar_connection_state(session)
    if not connected:
        raise json_error(409, "GOOGLE_CALENDAR_NOT_CONNECTED", "Google Calendar is not connected.")
    if not can_read:
        raise json_error(
            403,
            "GOOGLE_CALENDAR_SCOPE_MISSING",
            "Google Calendar read scope is not granted. Reconnect Google.",
        )
    calendar_ids = normalized_calendar_ids(payload.calendar_ids)
    if not calendar_ids:
        calendar_ids = ["primary"]
    start_at, end_at = calendar_sync_range(payload.base_date, payload.month_count)
    access_token = google_gmail_access_token(session, connection)
    now = jst_iso()
    imported_count = 0
    updated_count = 0
    cancelled_count = 0
    seen_keys: set[tuple[str, str]] = set()
    storage_calendar_ids: list[str] = []
    for calendar_id in calendar_ids:
        storage_calendar_id = storage_calendar_id_for_created_event(calendar_id, access_token)
        if storage_calendar_id not in storage_calendar_ids:
            storage_calendar_ids.append(storage_calendar_id)
        google_items = fetch_google_calendar_events(
            calendar_id,
            access_token,
            time_min=start_at,
            time_max=end_at,
            show_deleted=True,
        )
        for item in google_items:
            external_event_id = item.get("id") if isinstance(item.get("id"), str) else None
            if external_event_id is None or external_event_id.strip() == "":
                continue
            seen_keys.add((storage_calendar_id, external_event_id))
            status = item.get("status") if isinstance(item.get("status"), str) else None
            existing = session.scalar(
                select(CalendarEvent)
                .where(CalendarEvent.source == "google")
                .where(CalendarEvent.external_calendar_id == storage_calendar_id)
                .where(CalendarEvent.external_event_id == external_event_id)
            )
            if status == "cancelled":
                if existing is not None:
                    existing.google_status = "cancelled"
                    existing.sync_status = "cancelled"
                    existing.last_synced_at = now
                    existing.updated_at = now
                    existing.version += 1
                    cancelled_count += 1
                continue
            normalized_event = normalized_google_calendar_event(item)
            if normalized_event is None:
                continue
            if existing is None:
                event_for_links = CalendarEvent(
                    id=f"calendar_event_{uuid.uuid4().hex}",
                    source="google",
                    external_calendar_id=storage_calendar_id,
                    external_event_id=external_event_id,
                    external_etag=normalized_event["external_etag"],
                    external_ical_uid=normalized_event["external_ical_uid"],
                    external_html_link=normalized_event["external_html_link"],
                    external_updated_at=normalized_event["external_updated_at"],
                    google_status=normalized_event["google_status"],
                    summary=normalized_event["summary"],
                    description=normalized_event["description"],
                    location=normalized_event["location"],
                    start_at=normalized_event["start_at"],
                    end_at=normalized_event["end_at"],
                    all_day=normalized_event["all_day"],
                    time_zone=normalized_event["time_zone"],
                    recurring_event_id=normalized_event["recurring_event_id"],
                    academic_series_id=None,
                    attendance_requirement="unknown",
                    tags_json=None,
                    metadata_json=None,
                    sync_status="synced",
                    last_synced_at=now,
                    local_note=None,
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
                session.add(event_for_links)
                session.flush()
                imported_count += 1
            else:
                apply_google_calendar_event_update(existing, normalized_event, now)
                event_for_links = existing
                updated_count += 1
            inherit_calendar_event_links_from_recurring_master(
                session,
                event=event_for_links,
                now=now,
            )
            mark_primary_alias_calendar_event_missing(
                session,
                storage_calendar_id=storage_calendar_id,
                external_event_id=external_event_id,
                now=now,
            )

    missing_count = mark_missing_calendar_events(
        session,
        calendar_ids=storage_calendar_ids or calendar_ids,
        seen_keys=seen_keys,
        time_min=start_at,
        time_max=end_at,
        now=now,
    )
    session.commit()
    return {
        "calendar_ids": calendar_ids,
        "time_min": start_at,
        "time_max": end_at,
        "imported_count": imported_count,
        "updated_count": updated_count,
        "cancelled_count": cancelled_count,
        "missing_count": missing_count,
    }


@router.get("/calendar/calendars")
def google_calendar_list(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected, can_read, _can_write = calendar_connection_state(session)
    if not connected:
        raise json_error(409, "GOOGLE_CALENDAR_NOT_CONNECTED", "Google Calendar is not connected.")
    if not can_read:
        raise json_error(
            403,
            "GOOGLE_CALENDAR_SCOPE_MISSING",
            "Google Calendar read scope is not granted. Reconnect Google.",
        )
    access_token = google_gmail_access_token(session, connection)
    data = calendar_api_get_json("/users/me/calendarList", access_token, {})
    items = data.get("items")
    return {
        "ok": True,
        "data": {
            "items": calendar_list_items(items if isinstance(items, list) else []),
        },
    }


@router.post("/calendar/events/prefill-from-mail")
def prefill_calendar_event_from_mail(
    payload: CalendarEventFromMailPrefillPayload,
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
    case = calendar_case_for_mail(
        session,
        message=message,
        preferred_case_id=payload.case_id,
    )
    input_payload = calendar_event_prefill_input_from_mail(
        session,
        message=message,
        case=case,
        prompt=payload.prompt,
    )
    prefill, llm_run_id = run_calendar_event_prefill(session, input_payload)
    session.commit()
    return {
        "ok": True,
        "data": {
            "prefill": prefill,
            "llm_run_id": llm_run_id,
            "linked_mail_message_id": message.id,
            "linked_case_id": case.id if case is not None else None,
            "linked_case_name": case.name if case is not None else None,
        },
    }


@router.post("/calendar/events")
def create_google_calendar_event(
    payload: GoogleCalendarEventCreatePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    connected, _can_read, can_write = calendar_connection_state(session)
    if not connected:
        raise json_error(409, "GOOGLE_CALENDAR_NOT_CONNECTED", "Google Calendar is not connected.")
    if not can_write:
        raise json_error(
            403,
            "GOOGLE_CALENDAR_SCOPE_MISSING",
            "Google Calendar event scope is not granted. Reconnect Google.",
        )
    access_token = google_gmail_access_token(session, connection)
    recurrence_rule = None
    if payload.recurrence_rule is not None and payload.recurrence_rule.strip() != "":
        recurrence_rule = calendar_recurrence_rule(payload.recurrence_rule)
    start_time, end_time = calendar_event_times_aligned_to_recurrence(
        calendar_event_time(payload.start, payload.time_zone),
        calendar_event_time(payload.end, payload.time_zone),
        recurrence_rule,
    )
    event_payload: dict[str, object] = {
        "summary": payload.summary.strip(),
        "start": start_time,
        "end": end_time,
    }
    if payload.description is not None and payload.description.strip() != "":
        event_payload["description"] = payload.description.strip()
    if payload.location is not None and payload.location.strip() != "":
        event_payload["location"] = payload.location.strip()
    if recurrence_rule is not None:
        event_payload["recurrence"] = [recurrence_rule]
    operation = create_calendar_external_operation(
        session,
        operation_type="google_calendar_event_create",
        payload={
            "calendar_id": payload.calendar_id,
            "payload": event_payload,
            "linked_mail_message_id": payload.linked_mail_message_id,
            "linked_case_id": payload.linked_case_id,
        },
    )
    try:
        data = calendar_api_post_json(
            encoded_calendar_path(payload.calendar_id, "/events"),
            access_token,
            event_payload,
        )
    except Exception as error:
        mark_calendar_external_operation_error(session, operation, error)
        raise
    external_event_id = data.get("id") if isinstance(data.get("id"), str) else None
    mark_calendar_external_operation_succeeded(
        operation,
        external_id=external_event_id,
    )
    now = jst_iso()
    storage_calendar_id = storage_calendar_id_for_created_event(
        payload.calendar_id,
        access_token,
    )
    db_event = upsert_calendar_event_from_google_response(
        session,
        calendar_id=storage_calendar_id,
        item=data,
        now=now,
    )
    if payload.academic_series_id is not None and payload.academic_series_id.strip() != "":
        db_event.academic_series_id = payload.academic_series_id.strip()
        db_event.updated_at = now
        db_event.version += 1
    attendance_requirement = normalized_attendance_requirement(payload.attendance_requirement)
    if attendance_requirement is not None:
        db_event.attendance_requirement = attendance_requirement
        db_event.updated_at = now
        db_event.version += 1
    links = []
    mail_link = ensure_calendar_event_link(
        session,
        event=db_event,
        linked_type="mail",
        linked_id=payload.linked_mail_message_id,
        now=now,
    )
    if mail_link is not None:
        links.append(mail_link)
    case_link = ensure_calendar_event_link(
        session,
        event=db_event,
        linked_type="case",
        linked_id=payload.linked_case_id,
        now=now,
    )
    if case_link is not None:
        links.append(case_link)
    propagate_calendar_event_links_to_recurring_instances(session, master_event=db_event, now=now)
    session.commit()
    return {
        "ok": True,
        "data": {
            "event": calendar_event_item(data),
            "db_event": calendar_db_event_item(db_event),
            "links": [calendar_event_link_item(session, link) for link in links],
        },
    }


@router.post("/import-latest-unloaded")
def import_latest_unloaded_google_gmail(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    access_token = google_gmail_access_token(session, connection)
    gmail_message_id = latest_unloaded_gmail_message_id(session, access_token)
    if gmail_message_id is None:
        return {
            "ok": True,
            "data": {
                "imported": False,
                "reason": "no_unloaded_message",
                "mail": None,
            },
        }

    gmail_message = gmail_api_get_json(
        f"/users/me/messages/{gmail_message_id}",
        access_token,
        {"format": "full"},
    )
    if gmail_message_is_draft(gmail_message):
        return {
            "ok": True,
            "data": {
                "imported": False,
                "reason": "draft_message",
                "mail": None,
            },
        }
    mail_input = gmail_message_to_mail_input(gmail_message)
    result = ingest_mock_mail(session, mail_input)
    kick_job_drain(reason="google_gmail_import_latest_unloaded")
    return {
        "ok": True,
        "data": {
            "imported": True,
            "mail": mail_ingestion_result_data(result),
            "subject": mail_input.subject,
            "from_address": mail_input.from_address,
            "received_at": mail_input.received_at,
        },
    }


@router.post("/import-unloaded-by-date")
def import_unloaded_google_gmail_by_date(
    payload: GmailImportByDatePayload,
    background_tasks: BackgroundTasks,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    target_date = parse_import_date(payload.date)
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    access_token = google_gmail_access_token(session, connection)
    gmail_message_ids = unloaded_gmail_message_ids_for_date(
        session,
        access_token,
        target_date,
    )
    imported: list[dict[str, object]] = []
    skipped_out_of_date = 0
    for gmail_message_id in gmail_message_ids:
        gmail_message = gmail_api_get_json(
            f"/users/me/messages/{gmail_message_id}",
            access_token,
            {"format": "full"},
        )
        if gmail_message_is_draft(gmail_message):
            continue
        mail_input = gmail_message_to_mail_input(gmail_message)
        if mail_input.received_at[:10] != target_date.isoformat():
            skipped_out_of_date += 1
            continue
        result = ingest_mock_mail(session, mail_input)
        imported.append(
            {
                "mail": mail_ingestion_result_data(result),
                "subject": mail_input.subject,
                "from_address": mail_input.from_address,
                "received_at": mail_input.received_at,
            }
        )
    if imported:
        clear_auto_import_unloaded_date(session, target_date.isoformat())
        background_tasks.add_task(
            kick_job_drain,
            reason="google_gmail_import_unloaded_by_date",
        )
    return {
        "ok": True,
        "data": {
            "date": target_date.isoformat(),
            "imported_count": len(imported),
            "candidate_count": len(gmail_message_ids),
            "skipped_out_of_date": skipped_out_of_date,
            "items": imported,
        },
    }


@router.post("/import-special-thread")
def import_special_google_gmail_thread(
    payload: GmailSpecialImportPayload,
    background_tasks: BackgroundTasks,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    gmail_source_id = gmail_source_identifier(payload.source)
    gmail_search_query = gmail_search_query_from_source(payload.source)
    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    access_token = google_gmail_access_token(session, connection)
    gmail_messages = gmail_messages_for_special_import(
        access_token,
        gmail_source_id,
        gmail_search_query,
    )
    imported: list[dict[str, object]] = []
    skipped_drafts = 0
    for gmail_message in gmail_messages:
        if gmail_message_is_draft(gmail_message):
            skipped_drafts += 1
            continue
        mail_input = gmail_message_to_mail_input(gmail_message)
        result = ingest_mock_mail(session, mail_input, force_skip=True)
        imported.append(
            {
                "mail": mail_ingestion_result_data(result),
                "subject": mail_input.subject,
                "from_address": mail_input.from_address,
                "received_at": mail_input.received_at,
            }
        )
    if imported:
        background_tasks.add_task(
            kick_job_drain,
            reason="google_gmail_special_import",
        )
    return {
        "ok": True,
        "data": {
            "source_id": gmail_source_id,
            "imported_count": len(imported),
            "candidate_count": len(gmail_messages),
            "skipped_drafts": skipped_drafts,
            "items": imported,
        },
    }


def run_google_gmail_auto_import_once(
    session: DatabaseSession,
    *,
    max_messages: int | None = None,
) -> dict[str, object]:
    settings = google_gmail_auto_import_settings_data(session)
    max_messages_to_import = normalized_auto_import_max_messages(
        max_messages if max_messages is not None else settings.get("max_messages_per_run")
    )
    now = jst_iso()
    if not bool(settings["enabled"]):
        return {
            "enabled": False,
            "imported_count": 0,
            "reason": "disabled",
        }

    connection = read_setting_json(session, GMAIL_CONNECTION_KEY) or {}
    if not (connection.get("refresh_token") or connection.get("access_token")):
        next_settings = {
            **settings,
            "last_run_at": now,
            "last_imported_count": 0,
            "last_checked_count": 0,
            "last_stop_reason": "not_connected",
            "last_stopped_gmail_message_id": None,
            "last_stopped_received_at": None,
            "last_reached_loaded_message": False,
            "last_error": None,
        }
        write_setting_json(session, GMAIL_AUTO_IMPORT_SETTINGS_KEY, next_settings, now)
        session.commit()
        return {
            "enabled": True,
            "imported_count": 0,
            "reason": "not_connected",
        }

    imported_count = 0
    imported_items: list[dict[str, object]] = []
    try:
        write_setting_json(
            session,
            GMAIL_AUTO_IMPORT_SETTINGS_KEY,
            {
                **settings,
                "last_run_at": now,
                "last_error": None,
                "last_stop_reason": "running",
            },
            now,
        )
        session.commit()
        access_token = google_gmail_access_token(session, connection)
        plan = latest_gmail_auto_import_plan_until_loaded(
            session,
            access_token,
            max_messages=max_messages_to_import,
            run_at=jst_now(),
        )
        for gmail_message_id in plan.import_message_ids:
            gmail_message = gmail_api_get_json(
                f"/users/me/messages/{gmail_message_id}",
                access_token,
                {"format": "full"},
            )
            if gmail_message_is_draft(gmail_message):
                continue
            mail_input = gmail_message_to_mail_input(gmail_message)
            result = ingest_mock_mail(session, mail_input)
            imported_count += 1
            imported_items.append(
                {
                    "mail": mail_ingestion_result_data(result),
                    "subject": mail_input.subject,
                    "from_address": mail_input.from_address,
                    "received_at": mail_input.received_at,
                }
            )
        next_settings = {
            **google_gmail_auto_import_settings_data(session),
            "last_run_at": now,
            "last_success_at": now,
            "last_error": None,
            "last_imported_count": imported_count,
            "last_checked_count": plan.checked_count,
            "last_stop_reason": plan.stop_reason,
            "last_stopped_gmail_message_id": plan.stopped_gmail_message_id,
            "last_stopped_received_at": plan.stopped_received_at,
            "last_reached_loaded_message": plan.reached_loaded_message,
            "unloaded_dates": plan.unloaded_dates,
        }
        write_setting_json(session, GMAIL_AUTO_IMPORT_SETTINGS_KEY, next_settings, now)
        session.commit()
    except Exception as error:
        next_settings = {
            **google_gmail_auto_import_settings_data(session),
            "last_run_at": now,
            "last_error": str(error),
            "last_imported_count": imported_count,
            "last_stop_reason": "failed",
            "unloaded_dates": settings.get("unloaded_dates", []),
        }
        write_setting_json(session, GMAIL_AUTO_IMPORT_SETTINGS_KEY, next_settings, now)
        session.commit()
        raise

    if imported_count > 0:
        kick_job_drain(reason="google_gmail_auto_import")
    return {
        "enabled": True,
        "imported_count": imported_count,
        "items": imported_items,
        "checked_count": plan.checked_count,
        "stop_reason": plan.stop_reason,
        "stopped_gmail_message_id": plan.stopped_gmail_message_id,
        "stopped_received_at": plan.stopped_received_at,
        "reached_loaded_message": plan.reached_loaded_message,
    }


def run_google_calendar_auto_sync_once(
    session: DatabaseSession,
) -> dict[str, object]:
    settings = google_calendar_auto_sync_settings_data(session)
    now = jst_iso()
    if not bool(settings["enabled"]):
        return {
            "enabled": False,
            "synced": False,
            "reason": "disabled",
        }

    connected, can_read, _can_write = calendar_connection_state(session)
    if not connected or not can_read:
        reason = "not_connected" if not connected else "calendar_scope_missing"
        next_settings = {
            **settings,
            "last_run_at": now,
            "last_error": None,
            "last_stop_reason": reason,
            "last_imported_count": 0,
            "last_updated_count": 0,
            "last_cancelled_count": 0,
            "last_missing_count": 0,
        }
        write_setting_json(session, CALENDAR_AUTO_SYNC_SETTINGS_KEY, next_settings, now)
        session.commit()
        return {
            "enabled": True,
            "synced": False,
            "reason": reason,
        }

    try:
        write_setting_json(
            session,
            CALENDAR_AUTO_SYNC_SETTINGS_KEY,
            {
                **settings,
                "last_run_at": now,
                "last_error": None,
                "last_stop_reason": "running",
            },
            now,
        )
        session.commit()
        result = perform_google_calendar_sync(
            session,
            GoogleCalendarSyncPayload(
                calendar_ids=normalized_calendar_ids(settings.get("calendar_ids"))
                or ["primary"],
                month_count=normalized_calendar_auto_sync_month_count(
                    settings.get("month_count")
                ),
            ),
        )
        latest_settings = google_calendar_auto_sync_settings_data(session)
        next_settings = {
            **latest_settings,
            "last_run_at": now,
            "last_success_at": now,
            "last_error": None,
            "last_imported_count": result["imported_count"],
            "last_updated_count": result["updated_count"],
            "last_cancelled_count": result["cancelled_count"],
            "last_missing_count": result["missing_count"],
            "last_time_min": result["time_min"],
            "last_time_max": result["time_max"],
            "last_stop_reason": "synced",
        }
        write_setting_json(session, CALENDAR_AUTO_SYNC_SETTINGS_KEY, next_settings, now)
        session.commit()
    except Exception as error:
        next_settings = {
            **google_calendar_auto_sync_settings_data(session),
            "last_run_at": now,
            "last_error": str(error),
            "last_stop_reason": "failed",
        }
        write_setting_json(session, CALENDAR_AUTO_SYNC_SETTINGS_KEY, next_settings, now)
        session.commit()
        raise

    return {
        "enabled": True,
        "synced": True,
        **result,
    }


def clear_auto_import_unloaded_date(
    session: DatabaseSession,
    target_date: str,
) -> None:
    settings = google_gmail_auto_import_settings_data(session)
    next_dates = [date_text for date_text in settings["unloaded_dates"] if date_text != target_date]
    if next_dates == settings["unloaded_dates"]:
        return
    now = jst_iso()
    write_setting_json(
        session,
        GMAIL_AUTO_IMPORT_SETTINGS_KEY,
        {**settings, "unloaded_dates": next_dates, "updated_at": now},
        now,
    )
    session.commit()


def parse_import_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Date must be formatted as YYYY-MM-DD.",
        ) from error


def gmail_source_identifier(value: str) -> str:
    source = value.strip()
    if source == "":
        raise json_error(422, "VALIDATION_ERROR", "Gmail URL or ID is required.")
    decoded = unquote(source)
    for pattern in (r"[?&#]th=([^&#/?\])\)]+)", r"[?&#]msg=([^&#/?\])\)]+)"):
        match = re.search(pattern, decoded)
        if match is not None:
            source = match.group(1)
            break
    else:
        source = gmail_url_tail_identifier(decoded)
    source = clean_gmail_identifier(source)
    if source == "":
        raise json_error(422, "VALIDATION_ERROR", "Gmail URL or ID is required.")
    return source


def gmail_search_query_from_source(value: str) -> str | None:
    source = value.strip()
    if "#search/" not in source:
        return None
    search_tail = source.rsplit("#search/", 1)[-1]
    query_part = search_tail.split("/", 1)[0].strip()
    if query_part == "":
        return None
    query = unquote_plus(query_part).strip()
    return query if query != "" else None


def gmail_url_tail_identifier(value: str) -> str:
    candidates: list[str] = []
    if "#" in value:
        candidates.extend(value.rsplit("#", 1)[1].split("/"))
    candidates.extend(re.split(r"[/#]", value))
    for candidate in reversed(candidates):
        identifier = clean_gmail_identifier(candidate)
        if gmail_identifier_like(identifier):
            return identifier
    return value


def clean_gmail_identifier(value: str) -> str:
    return value.strip().strip("<>[](){}'\".,;")


def gmail_identifier_like(value: str) -> bool:
    if len(value) < 8:
        return False
    return re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None


def gmail_messages_for_special_import(
    access_token: str,
    gmail_source_id: str,
    search_query: str | None = None,
) -> list[dict[str, object]]:
    thread_data = gmail_api_try_get_json(
        f"/users/me/threads/{quote(gmail_source_id, safe='')}",
        access_token,
        {"format": "full"},
    )
    if thread_data is not None:
        messages = thread_data.get("messages")
        if isinstance(messages, list):
            return [message for message in messages if isinstance(message, dict)]
        return []

    message_data = gmail_api_try_get_json(
        f"/users/me/messages/{quote(gmail_source_id, safe='')}",
        access_token,
        {"format": "full"},
    )
    if message_data is not None:
        thread_id = message_data.get("threadId")
        if isinstance(thread_id, str) and thread_id.strip() != "":
            thread_data = gmail_api_try_get_json(
                f"/users/me/threads/{quote(thread_id, safe='')}",
                access_token,
                {"format": "full"},
            )
            if thread_data is not None:
                messages = thread_data.get("messages")
                if isinstance(messages, list):
                    return [message for message in messages if isinstance(message, dict)]
        return [message_data]

    if search_query is not None:
        thread_list_data = gmail_api_try_get_json(
            "/users/me/threads",
            access_token,
            {"q": search_query, "maxResults": 1},
        )
        if thread_list_data is not None:
            thread_refs = thread_list_data.get("threads")
            if isinstance(thread_refs, list) and thread_refs:
                thread_ref = thread_refs[0]
                if isinstance(thread_ref, dict):
                    thread_id = thread_ref.get("id")
                    if isinstance(thread_id, str) and thread_id.strip() != "":
                        thread_data = gmail_api_try_get_json(
                            f"/users/me/threads/{quote(thread_id, safe='')}",
                            access_token,
                            {"format": "full"},
                        )
                        if thread_data is not None:
                            messages = thread_data.get("messages")
                            if isinstance(messages, list):
                                return [message for message in messages if isinstance(message, dict)]
    raise json_error(
        404,
        "GOOGLE_GMAIL_NOT_FOUND",
        "Gmail thread or message was not found.",
    )


def exchange_authorization_code(code: str, *, redirect_uri: str | None = None) -> dict[str, object]:
    client_id = get_google_oauth_client_id()
    client_secret = get_google_oauth_client_secret()
    if client_id is None or client_secret is None:
        raise json_error(
            409,
            "GOOGLE_OAUTH_NOT_CONFIGURED",
            "Google OAuth client id and secret are not configured.",
        )
    payload = urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri or get_google_oauth_redirect_uri(),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_OAUTH_TOKEN_ERROR", "Invalid Google token response.")
    return data


def google_gmail_access_token(
    session: DatabaseSession,
    connection: dict[str, object],
) -> str:
    access_token = connection.get("access_token")
    token_expires_at = connection.get("token_expires_at")
    if isinstance(access_token, str) and access_token.strip() != "":
        if not isinstance(token_expires_at, str) or token_expires_at.strip() == "":
            return access_token
        if parse_iso_datetime(token_expires_at) > jst_now() + timedelta(seconds=60):
            return access_token

    refresh_token = connection.get("refresh_token")
    if not isinstance(refresh_token, str) or refresh_token.strip() == "":
        raise json_error(
            409,
            "GOOGLE_GMAIL_NOT_CONNECTED",
            "Google Gmail is not connected.",
        )

    token_data = refresh_google_access_token(refresh_token)
    next_access_token = token_data.get("access_token")
    if not isinstance(next_access_token, str) or next_access_token.strip() == "":
        raise json_error(
            502,
            "GOOGLE_OAUTH_TOKEN_ERROR",
            "Google did not return an access token.",
        )

    now = jst_iso()
    expires_in = int(token_data.get("expires_in", 0) or 0)
    connection.update(
        {
            "access_token": next_access_token,
            "token_type": token_data.get("token_type", connection.get("token_type")),
            "token_expires_at": (
                jst_now() + timedelta(seconds=expires_in)
            ).isoformat()
            if expires_in > 0
            else None,
            "updated_at": now,
            "last_error": None,
        }
    )
    write_setting_json(session, GMAIL_CONNECTION_KEY, connection, now)
    session.commit()
    return next_access_token


def refresh_google_access_token(refresh_token: str) -> dict[str, object]:
    client_id = get_google_oauth_client_id()
    client_secret = get_google_oauth_client_secret()
    if client_id is None or client_secret is None:
        raise json_error(
            409,
            "GOOGLE_OAUTH_NOT_CONFIGURED",
            "Google OAuth client id and secret are not configured.",
        )
    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_OAUTH_TOKEN_ERROR", "Invalid Google token response.")
    return data


def gmail_api_get_json(
    path: str,
    access_token: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    query = "" if not params else f"?{urlencode(params)}"
    request = Request(
        f"{GMAIL_API_BASE_URL}{path}{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_GMAIL_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_GMAIL_API_ERROR",
            details or f"Gmail API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            f"Gmail API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", "Invalid Gmail API response.")
    return data


def gmail_api_try_get_json(
    path: str,
    access_token: str,
    params: dict[str, object] | None = None,
) -> dict[str, object] | None:
    query = "" if not params else f"?{urlencode(params)}"
    request = Request(
        f"{GMAIL_API_BASE_URL}{path}{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        if exc.code == 404 or (
            exc.code == 400
            and isinstance(details, str)
            and "Invalid id value" in details
        ):
            return None
        raise json_error(
            exc.code,
            "GOOGLE_GMAIL_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_GMAIL_API_ERROR",
            details or f"Gmail API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            f"Gmail API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", "Invalid Gmail API response.")
    return data


def gmail_api_post_json(
    path: str,
    access_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    request = Request(
        f"{GMAIL_API_BASE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_GMAIL_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_GMAIL_API_ERROR",
            details or f"Gmail API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_GMAIL_API_ERROR",
            f"Gmail API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", "Invalid Gmail API response.")
    return data


def calendar_api_get_json(
    path: str,
    access_token: str,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    query = "" if not params else f"?{urlencode(params)}"
    request = Request(
        f"{GOOGLE_CALENDAR_API_BASE_URL}{path}{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_CALENDAR_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_CALENDAR_API_ERROR",
            details or f"Google Calendar API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_CALENDAR_API_ERROR",
            f"Google Calendar API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_CALENDAR_API_ERROR", "Invalid Calendar API response.")
    return data


def calendar_api_post_json(
    path: str,
    access_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    request = Request(
        f"{GOOGLE_CALENDAR_API_BASE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_CALENDAR_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_CALENDAR_API_ERROR",
            details or f"Google Calendar API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_CALENDAR_API_ERROR",
            f"Google Calendar API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_CALENDAR_API_ERROR", "Invalid Calendar API response.")
    return data


def calendar_api_patch_json(
    path: str,
    access_token: str,
    payload: dict[str, object],
) -> dict[str, object]:
    request = Request(
        f"{GOOGLE_CALENDAR_API_BASE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_CALENDAR_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_CALENDAR_API_ERROR",
            details or f"Google Calendar API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_CALENDAR_API_ERROR",
            f"Google Calendar API request failed: {exc.reason}",
        ) from exc
    if not isinstance(data, dict):
        raise json_error(502, "GOOGLE_CALENDAR_API_ERROR", "Invalid Calendar API response.")
    return data


def calendar_api_delete(
    path: str,
    access_token: str,
) -> None:
    request = Request(
        f"{GOOGLE_CALENDAR_API_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        details = read_google_error_details(exc)
        raise json_error(
            exc.code,
            "GOOGLE_CALENDAR_API_FORBIDDEN"
            if exc.code == 403
            else "GOOGLE_CALENDAR_API_ERROR",
            details or f"Google Calendar API request failed with HTTP {exc.code}.",
        ) from exc
    except URLError as exc:
        raise json_error(
            502,
            "GOOGLE_CALENDAR_API_ERROR",
            f"Google Calendar API request failed: {exc.reason}",
        ) from exc


def encoded_calendar_path(calendar_id: str, suffix: str = "") -> str:
    return f"/calendars/{quote(calendar_id, safe='')}{suffix}"


def storage_calendar_id_for_created_event(
    calendar_id: str,
    access_token: str,
) -> str:
    if calendar_id != "primary":
        return calendar_id
    try:
        data = calendar_api_get_json(encoded_calendar_path("primary"), access_token, {})
    except Exception:
        return calendar_id
    primary_id = data.get("id") if isinstance(data.get("id"), str) else None
    return primary_id.strip() if primary_id is not None and primary_id.strip() != "" else calendar_id


def calendar_event_time(value: str, time_zone: str) -> dict[str, object]:
    stripped = value.strip()
    date_match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", stripped)
    if date_match is not None:
        year, month, day = date_match.groups()
        return {"date": f"{year}-{int(month):02d}-{int(day):02d}"}

    try:
        target_zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as error:
        raise json_error(
            400,
            "INVALID_CALENDAR_TIME_ZONE",
            f"Invalid calendar time zone: {time_zone}",
        ) from error

    normalized_input = stripped.replace("/", "-")
    if normalized_input.endswith("Z"):
        normalized_input = f"{normalized_input[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized_input)
    except ValueError as error:
        raise json_error(
            400,
            "INVALID_CALENDAR_EVENT_TIME",
            f"Invalid calendar event time: {value}",
        ) from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=target_zone)
    else:
        parsed = parsed.astimezone(target_zone)
    normalized = parsed.isoformat(timespec="seconds")
    return {"dateTime": normalized, "timeZone": time_zone}


def calendar_recurrence_rule(value: str) -> str:
    stripped = value.strip().upper()
    rule = stripped if stripped.startswith("RRULE:") else f"RRULE:{stripped}"
    if not re.fullmatch(r"RRULE:[A-Z0-9_=;,\-]+", rule):
        raise json_error(
            400,
            "INVALID_CALENDAR_RECURRENCE_RULE",
            f"Invalid calendar recurrence rule: {value}",
        )
    if "FREQ=" not in rule:
        raise json_error(
            400,
            "INVALID_CALENDAR_RECURRENCE_RULE",
            "Calendar recurrence rule must include FREQ.",
        )
    return rule


def calendar_recurrence_parts(rule: str) -> dict[str, str]:
    body = rule[6:] if rule.startswith("RRULE:") else rule
    parts: dict[str, str] = {}
    for item in body.split(";"):
        key, separator, value = item.partition("=")
        if separator == "" or key == "":
            continue
        parts[key] = value
    return parts


def calendar_rrule_weekday(value: str) -> int | None:
    match = re.fullmatch(r"[+-]?\d*([A-Z]{2})", value.strip())
    if match is None:
        return None
    return CALENDAR_RRULE_WEEKDAY_INDEX.get(match.group(1))


def calendar_time_date(value: dict[str, object]) -> date | None:
    raw_date_time = value.get("dateTime")
    if isinstance(raw_date_time, str):
        try:
            return datetime.fromisoformat(raw_date_time.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    raw_date = value.get("date")
    if isinstance(raw_date, str):
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            return None
    return None


def calendar_time_plus_days(value: dict[str, object], days: int) -> dict[str, object]:
    if days == 0:
        return dict(value)
    updated = dict(value)
    raw_date_time = updated.get("dateTime")
    if isinstance(raw_date_time, str):
        parsed = datetime.fromisoformat(raw_date_time.replace("Z", "+00:00"))
        updated["dateTime"] = (parsed + timedelta(days=days)).isoformat(timespec="seconds")
        return updated
    raw_date = updated.get("date")
    if isinstance(raw_date, str):
        updated["date"] = (date.fromisoformat(raw_date) + timedelta(days=days)).isoformat()
    return updated


def calendar_int_values(value: str | None) -> list[int]:
    if value is None:
        return []
    values: list[int] = []
    for item in value.split(","):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def calendar_days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - timedelta(days=1)).day
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def calendar_monthday_date(year: int, month: int, month_day: int) -> date | None:
    days_in_month = calendar_days_in_month(year, month)
    day = month_day if month_day > 0 else days_in_month + month_day + 1
    if day < 1 or day > days_in_month:
        return None
    return date(year, month, day)


def calendar_nth_weekday_date(year: int, month: int, weekday: int, position: int) -> date | None:
    days_in_month = calendar_days_in_month(year, month)
    if position > 0:
        first_weekday = (date(year, month, 1).weekday() + 1) % 7
        day = 1 + ((weekday - first_weekday) % 7) + (position - 1) * 7
    else:
        last_weekday = (date(year, month, days_in_month).weekday() + 1) % 7
        day = days_in_month - ((last_weekday - weekday) % 7) + (position + 1) * 7
    if day < 1 or day > days_in_month:
        return None
    return date(year, month, day)


def calendar_monthly_candidate_dates(parts: dict[str, str], year: int, month: int) -> list[date]:
    month_days = calendar_int_values(parts.get("BYMONTHDAY"))
    if len(month_days) > 0:
        return sorted(
            candidate
            for month_day in month_days
            if (candidate := calendar_monthday_date(year, month, month_day)) is not None
        )
    weekdays = [
        weekday
        for value in parts.get("BYDAY", "").split(",")
        if (weekday := calendar_rrule_weekday(value)) is not None
    ]
    if len(weekdays) == 0:
        return []
    positions = calendar_int_values(parts.get("BYSETPOS"))
    if len(positions) == 0:
        positions = [1]
    return sorted(
        candidate
        for weekday in weekdays
        for position in positions
        if (candidate := calendar_nth_weekday_date(year, month, weekday, position)) is not None
    )


def calendar_next_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month_index = (year * 12 + (month - 1)) + offset
    return month_index // 12, month_index % 12 + 1


def calendar_first_recurrence_date_on_or_after(
    parts: dict[str, str],
    start_date: date,
) -> date | None:
    frequency = parts.get("FREQ")
    if frequency == "WEEKLY" and "BYDAY" in parts:
        selected_weekdays = [
            weekday
            for value in parts["BYDAY"].split(",")
            if (weekday := calendar_rrule_weekday(value)) is not None
        ]
        if len(selected_weekdays) == 0:
            return None
        current_weekday = (start_date.weekday() + 1) % 7
        return start_date + timedelta(
            days=min((weekday - current_weekday) % 7 for weekday in selected_weekdays)
        )
    if frequency == "MONTHLY":
        for month_offset in range(0, 240):
            year, month = calendar_next_month(start_date.year, start_date.month, month_offset)
            candidates = [
                candidate
                for candidate in calendar_monthly_candidate_dates(parts, year, month)
                if candidate >= start_date
            ]
            if len(candidates) > 0:
                return min(candidates)
        return None
    if frequency == "YEARLY":
        months = calendar_int_values(parts.get("BYMONTH")) or [start_date.month]
        months = [month for month in months if 1 <= month <= 12]
        if len(months) == 0:
            return None
        for year_offset in range(0, 50):
            year = start_date.year + year_offset
            candidates = [
                candidate
                for month in months
                for candidate in calendar_monthly_candidate_dates(parts, year, month)
                if candidate >= start_date
            ]
            if len(candidates) > 0:
                return min(candidates)
        return None
    return None


def calendar_event_times_aligned_to_recurrence(
    start_time: dict[str, object],
    end_time: dict[str, object],
    recurrence_rule: str | None,
) -> tuple[dict[str, object], dict[str, object]]:
    if recurrence_rule is None:
        return start_time, end_time
    start_date = calendar_time_date(start_time)
    if start_date is None:
        return start_time, end_time
    occurrence_date = calendar_first_recurrence_date_on_or_after(
        calendar_recurrence_parts(recurrence_rule),
        start_date,
    )
    if occurrence_date is None:
        return start_time, end_time
    day_offset = (occurrence_date - start_date).days
    if day_offset == 0:
        return start_time, end_time
    return (
        calendar_time_plus_days(start_time, day_offset),
        calendar_time_plus_days(end_time, day_offset),
    )


def calendar_event_items(items: list[object]) -> list[dict[str, object]]:
    return [calendar_event_item(item) for item in items if isinstance(item, dict)]


def normalized_attendance_requirement(value: str | None) -> str | None:
    attendance_requirement = value.strip() if value is not None else None
    if attendance_requirement not in {None, "required", "optional", "not_required"}:
        raise json_error(422, "VALIDATION_ERROR", "Invalid attendance requirement.")
    if attendance_requirement == "optional":
        return "not_required"
    return attendance_requirement


def normalized_calendar_ids(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    calendar_ids = []
    for value in values:
        stripped = value.strip()
        if stripped != "" and stripped not in calendar_ids:
            calendar_ids.append(stripped)
    return calendar_ids


def calendar_sync_range(base_date: str | None, month_count: int) -> tuple[str, str]:
    if base_date is not None and base_date.strip() != "":
        try:
            base = datetime.strptime(base_date.strip()[:10], "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError:
            base = jst_now().replace(day=1)
    else:
        base = jst_now().replace(day=1)
    start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    safe_month_count = max(1, min(month_count, 12))
    month_index = start.month - 1 + safe_month_count
    end = start.replace(
        year=start.year + month_index // 12,
        month=month_index % 12 + 1,
    )
    return start.isoformat(), end.isoformat()


def fetch_google_calendar_events(
    calendar_id: str,
    access_token: str,
    *,
    time_min: str,
    time_max: str,
    show_deleted: bool,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    page_token: str | None = None
    while True:
        params: dict[str, object] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 2500,
            "timeMin": time_min,
            "timeMax": time_max,
            "showDeleted": "true" if show_deleted else "false",
        }
        if page_token is not None:
            params["pageToken"] = page_token
        data = calendar_api_get_json(
            encoded_calendar_path(calendar_id, "/events"),
            access_token,
            params,
        )
        raw_items = data.get("items")
        if isinstance(raw_items, list):
            items.extend(item for item in raw_items if isinstance(item, dict))
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or next_page_token.strip() == "":
            return items
        page_token = next_page_token


def calendar_google_time_value(value: object) -> tuple[str, int, str | None] | None:
    if not isinstance(value, dict):
        return None
    date_time = value.get("dateTime")
    if isinstance(date_time, str) and date_time.strip() != "":
        time_zone = value.get("timeZone") if isinstance(value.get("timeZone"), str) else None
        return date_time.strip(), 0, time_zone
    date_value = value.get("date")
    if isinstance(date_value, str) and len(date_value.strip()) == 10:
        return f"{date_value.strip()}T00:00:00+09:00", 1, None
    return None


def normalized_google_calendar_event(
    item: dict[str, object],
) -> dict[str, object] | None:
    start = calendar_google_time_value(item.get("start"))
    end = calendar_google_time_value(item.get("end"))
    if start is None:
        return None
    if end is None:
        end = start
    start_at, all_day, start_time_zone = start
    end_at, _end_all_day, end_time_zone = end
    return {
        "external_etag": item.get("etag") if isinstance(item.get("etag"), str) else None,
        "external_ical_uid": item.get("iCalUID")
        if isinstance(item.get("iCalUID"), str)
        else None,
        "external_html_link": item.get("htmlLink")
        if isinstance(item.get("htmlLink"), str)
        else None,
        "meeting_url": google_calendar_meeting_url(item),
        "external_updated_at": item.get("updated")
        if isinstance(item.get("updated"), str)
        else None,
        "google_status": item.get("status") if isinstance(item.get("status"), str) else None,
        "summary": item.get("summary") if isinstance(item.get("summary"), str) else "",
        "description": item.get("description")
        if isinstance(item.get("description"), str)
        else None,
        "location": item.get("location").strip()
        if isinstance(item.get("location"), str) and item.get("location").strip() != ""
        else None,
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
        "time_zone": start_time_zone or end_time_zone,
        "recurring_event_id": item.get("recurringEventId")
        if isinstance(item.get("recurringEventId"), str)
        else None,
    }


def google_calendar_meeting_url(item: dict[str, object]) -> str | None:
    hangout_link = item.get("hangoutLink")
    if isinstance(hangout_link, str) and hangout_link.strip() != "":
        return hangout_link.strip()
    conference_data = item.get("conferenceData")
    if not isinstance(conference_data, dict):
        return None
    entry_points = conference_data.get("entryPoints")
    if not isinstance(entry_points, list):
        return None
    fallback_uri: str | None = None
    for entry in entry_points:
        if not isinstance(entry, dict):
            continue
        uri = entry.get("uri")
        if not isinstance(uri, str) or uri.strip() == "":
            continue
        normalized_uri = uri.strip()
        if entry.get("entryPointType") == "video":
            return normalized_uri
        if fallback_uri is None:
            fallback_uri = normalized_uri
    return fallback_uri


def apply_google_calendar_event_update(
    event: CalendarEvent,
    values: dict[str, object],
    now: str,
) -> None:
    event.external_etag = values["external_etag"]  # type: ignore[assignment]
    event.external_ical_uid = values["external_ical_uid"]  # type: ignore[assignment]
    event.external_html_link = values["external_html_link"]  # type: ignore[assignment]
    event.meeting_url = values["meeting_url"]  # type: ignore[assignment]
    event.external_updated_at = values["external_updated_at"]  # type: ignore[assignment]
    event.google_status = values["google_status"]  # type: ignore[assignment]
    event.summary = str(values["summary"])
    event.description = values["description"]  # type: ignore[assignment]
    event.location = values["location"]  # type: ignore[assignment]
    event.start_at = str(values["start_at"])
    event.end_at = str(values["end_at"])
    event.all_day = int(values["all_day"])
    event.time_zone = values["time_zone"]  # type: ignore[assignment]
    event.recurring_event_id = values["recurring_event_id"]  # type: ignore[assignment]
    event.sync_status = "synced"
    event.last_synced_at = now
    event.updated_at = now
    event.version += 1


def mark_missing_calendar_events(
    session: DatabaseSession,
    *,
    calendar_ids: list[str],
    seen_keys: set[tuple[str, str]],
    time_min: str,
    time_max: str,
    now: str,
) -> int:
    existing_events = session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.source == "google")
        .where(CalendarEvent.external_calendar_id.in_(calendar_ids))
        .where(CalendarEvent.start_at < time_max)
        .where(CalendarEvent.end_at > time_min)
        .where(CalendarEvent.sync_status != "missing_from_google")
    ).all()
    missing_count = 0
    for event in existing_events:
        if event.external_calendar_id is None or event.external_event_id is None:
            continue
        if (event.external_calendar_id, event.external_event_id) in seen_keys:
            continue
        event.sync_status = "missing_from_google"
        event.last_synced_at = now
        event.updated_at = now
        event.version += 1
        missing_count += 1
    return missing_count


def mark_primary_alias_calendar_event_missing(
    session: DatabaseSession,
    *,
    storage_calendar_id: str,
    external_event_id: str,
    now: str,
) -> None:
    if storage_calendar_id == "primary":
        return
    alias = session.scalar(
        select(CalendarEvent)
        .where(CalendarEvent.source == "google")
        .where(CalendarEvent.external_calendar_id == "primary")
        .where(CalendarEvent.external_event_id == external_event_id)
        .where(CalendarEvent.sync_status != "missing_from_google")
    )
    if alias is None:
        return
    alias.sync_status = "missing_from_google"
    alias.last_synced_at = now
    alias.updated_at = now
    alias.version += 1


def calendar_event_is_active(event: CalendarEvent) -> bool:
    return (
        event.sync_status not in {"missing_from_google", "cancelled"}
        and event.google_status != "cancelled"
    )


def calendar_event_has_series(event: CalendarEvent) -> bool:
    return (
        event.academic_series_id is not None
        and event.academic_series_id.strip() != ""
    ) or (
        event.recurring_event_id is not None
        and event.recurring_event_id.strip() != ""
    )


def calendar_event_delete_targets(
    session: DatabaseSession,
    *,
    event: CalendarEvent,
    scope: str,
) -> list[CalendarEvent]:
    if scope == "event":
        return [event]
    if event.academic_series_id is not None and event.academic_series_id.strip() != "":
        candidates = session.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.academic_series_id == event.academic_series_id)
            .order_by(CalendarEvent.start_at.asc(), CalendarEvent.id.asc())
        ).all()
        return unique_active_calendar_events(candidates, fallback=event)
    if event.recurring_event_id is not None and event.recurring_event_id.strip() != "":
        master_external_event_id = event.recurring_event_id
        candidates = session.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.source == event.source)
            .where(CalendarEvent.external_calendar_id == event.external_calendar_id)
            .where(
                (CalendarEvent.external_event_id == master_external_event_id)
                | (CalendarEvent.recurring_event_id == master_external_event_id)
            )
            .order_by(CalendarEvent.start_at.asc(), CalendarEvent.id.asc())
        ).all()
        return unique_active_calendar_events(candidates, fallback=event)
    return [event]


def calendar_event_google_delete_targets(
    events: list[CalendarEvent],
    *,
    requested_event: CalendarEvent,
    scope: str,
) -> list[tuple[str, str]]:
    if requested_event.source != "google":
        return []
    if requested_event.external_calendar_id is None:
        raise json_error(
            409,
            "GOOGLE_CALENDAR_EVENT_NOT_LINKED",
            "Calendar event is not linked to a Google event.",
        )
    if (
        scope == "series"
        and requested_event.recurring_event_id is not None
        and requested_event.recurring_event_id.strip() != ""
    ):
        return [(requested_event.external_calendar_id, requested_event.recurring_event_id)]

    targets: dict[tuple[str, str], tuple[str, str]] = {}
    for event in events:
        if event.source != "google":
            continue
        if event.external_calendar_id is None or event.external_event_id is None:
            raise json_error(
                409,
                "GOOGLE_CALENDAR_EVENT_NOT_LINKED",
                "Calendar event is not linked to a Google event.",
            )
        key = (event.external_calendar_id, event.external_event_id)
        targets[key] = key
    return list(targets.values())


def unique_active_calendar_events(
    events: list[CalendarEvent],
    *,
    fallback: CalendarEvent,
) -> list[CalendarEvent]:
    selected: dict[str, CalendarEvent] = {}
    for event in [*events, fallback]:
        if not calendar_event_is_active(event):
            continue
        selected[event.id] = event
    return list(selected.values())


def calendar_db_event_item(event: CalendarEvent) -> dict[str, object]:
    if event.all_day:
        start: dict[str, object] = {"date": event.start_at[:10]}
        end: dict[str, object] = {"date": event.end_at[:10]}
    else:
        start = {"dateTime": event.start_at}
        end = {"dateTime": event.end_at}
        if event.time_zone is not None:
            start["timeZone"] = event.time_zone
            end["timeZone"] = event.time_zone
    return {
        "id": event.id,
        "google_event_id": event.external_event_id,
        "calendar_source_id": event.external_calendar_id,
        "summary": event.summary,
        "description": event.description,
        "location": event.location,
        "html_link": event.external_html_link,
        "meeting_url": event.meeting_url,
        "start": start,
        "end": end,
        "status": event.google_status,
        "created": event.created_at,
        "updated": event.external_updated_at or event.updated_at,
        "sync_status": event.sync_status,
        "recurring_event_id": event.recurring_event_id,
        "academic_series_id": event.academic_series_id,
        "attendance_requirement": event.attendance_requirement,
        "tags_json": event.tags_json,
        "metadata_json": event.metadata_json,
        "local_note": event.local_note,
    }


def calendar_event_link_item(
    session: DatabaseSession,
    link: CalendarEventLink,
) -> dict[str, object]:
    title = link.linked_id
    href: str | None = None
    metadata: dict[str, object] = {}
    if link.linked_type == "case":
        case = session.get(Case, link.linked_id)
        if case is not None:
            title = case.name
            href = f"/cases/{case.id}"
            metadata = {"status": case.progress_status, "ball": case.ball_status}
    elif link.linked_type == "task":
        task = session.get(Task, link.linked_id)
        if task is not None:
            title = task.title
            href = f"/tasks/{task.id}"
            metadata = {
                "status": task.status,
                "priority": task.priority,
                "due_at": task.due_at,
            }
    elif link.linked_type in {"mail", "gmail_message"}:
        message = session.get(GmailMessage, link.linked_id)
        if message is not None:
            title = message.subject or "(no subject)"
            href = f"/mail/{message.id}"
            metadata = {
                "from": message.from_name or message.from_address,
                "received_at": message.received_at,
            }
    return {
        "id": link.id,
        "calendar_event_id": link.calendar_event_id,
        "linked_type": link.linked_type,
        "linked_id": link.linked_id,
        "role": link.role,
        "title": title,
        "href": href,
        "metadata": metadata,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "version": link.version,
    }


def calendar_event_mail_summaries(
    session: DatabaseSession,
    links: list[CalendarEventLink],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_message_ids: set[str] = set()
    for link in links:
        if link.linked_type not in {"mail", "gmail_message"}:
            continue
        message = session.get(GmailMessage, link.linked_id)
        if message is None or message.id in seen_message_ids:
            continue
        seen_message_ids.add(message.id)
        thread_summary = session.scalar(
            select(MailThreadSummary).where(MailThreadSummary.thread_id == message.thread_id)
        )
        mail_summary = session.scalar(
            select(MailSummary).where(MailSummary.message_id == message.id)
        )
        if thread_summary is not None:
            summary_text = thread_summary.summary_text
            next_action = thread_summary.next_action
            source = "thread_summary"
        elif mail_summary is not None:
            summary_text = mail_summary.summary_text
            next_action = mail_summary.next_action
            source = "mail_summary"
        else:
            summary_text = message.snippet or ""
            next_action = None
            source = "snippet"
        items.append(
            {
                "message_id": message.id,
                "thread_id": message.thread_id,
                "subject": message.subject,
                "from": message.from_name or message.from_address,
                "received_at": message.received_at,
                "summary": summary_text,
                "next_action": next_action,
                "source": source,
                "href": f"/mail/{message.id}",
            }
        )
    return items


def validate_calendar_event_link_target(
    session: DatabaseSession,
    linked_type: str,
    linked_id: str,
) -> None:
    if linked_type == "case":
        if session.get(Case, linked_id) is None:
            raise json_error(404, "CASE_NOT_FOUND", "Case was not found.")
        return
    if linked_type == "task":
        task = session.get(Task, linked_id)
        if task is None or task.deleted_at is not None:
            raise json_error(404, "TASK_NOT_FOUND", "Task was not found.")
        return
    if linked_type in {"mail", "gmail_message"}:
        if session.get(GmailMessage, linked_id) is None:
            raise json_error(404, "MAIL_NOT_FOUND", "Mail was not found.")
        return
    raise json_error(
        400,
        "UNSUPPORTED_CALENDAR_EVENT_LINK_TYPE",
        "Calendar event link type is not supported.",
    )


def calendar_list_items(items: list[object]) -> list[dict[str, object]]:
    return [calendar_list_item(item) for item in items if isinstance(item, dict)]


def calendar_list_item(item: dict[str, object]) -> dict[str, object]:
    access_role = item.get("accessRole") if isinstance(item.get("accessRole"), str) else ""
    return {
        "id": item.get("id") if isinstance(item.get("id"), str) else "",
        "summary": item.get("summary") if isinstance(item.get("summary"), str) else "",
        "description": item.get("description")
        if isinstance(item.get("description"), str)
        else None,
        "primary": bool(item.get("primary", False)),
        "access_role": access_role,
        "background_color": item.get("backgroundColor")
        if isinstance(item.get("backgroundColor"), str)
        else None,
        "foreground_color": item.get("foregroundColor")
        if isinstance(item.get("foregroundColor"), str)
        else None,
        "time_zone": item.get("timeZone") if isinstance(item.get("timeZone"), str) else None,
        "can_write": access_role in {"owner", "writer"},
    }


def calendar_event_item(item: dict[str, object]) -> dict[str, object]:
    start = item.get("start")
    end = item.get("end")
    return {
        "id": item.get("id") if isinstance(item.get("id"), str) else None,
        "summary": item.get("summary") if isinstance(item.get("summary"), str) else "",
        "description": item.get("description")
        if isinstance(item.get("description"), str)
        else None,
        "location": item.get("location") if isinstance(item.get("location"), str) else None,
        "html_link": item.get("htmlLink") if isinstance(item.get("htmlLink"), str) else None,
        "start": start if isinstance(start, dict) else {},
        "end": end if isinstance(end, dict) else {},
        "status": item.get("status") if isinstance(item.get("status"), str) else None,
        "created": item.get("created") if isinstance(item.get("created"), str) else None,
        "updated": item.get("updated") if isinstance(item.get("updated"), str) else None,
    }


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def calendar_prefill_default_start() -> tuple[str, str]:
    today = jst_now().date().isoformat()
    return f"{today}T10:00", f"{today}T11:00"


def normalize_calendar_event_prefill_output(output: dict[str, object]) -> dict[str, object]:
    summary = normalize_optional_text(output.get("summary")) or "メール由来の予定"
    description = normalize_optional_text(output.get("description"))
    location = normalize_optional_text(output.get("location"))
    start_at = normalize_optional_text(output.get("start_at"))
    end_at = normalize_optional_text(output.get("end_at"))
    if start_at is None or end_at is None:
        default_start, default_end = calendar_prefill_default_start()
        start_at = start_at or default_start
        end_at = end_at or default_end
    time_zone = normalize_optional_text(output.get("time_zone")) or "Asia/Tokyo"
    warnings = output.get("warnings")
    return {
        "summary": summary,
        "description": description,
        "location": location,
        "start_at": start_at,
        "end_at": end_at,
        "time_zone": time_zone,
        "reasoning_summary": normalize_optional_text(output.get("reasoning_summary")),
        "warnings": warnings if isinstance(warnings, list) else [],
    }


def run_calendar_event_prefill(
    session: DatabaseSession,
    input_payload: dict[str, object],
) -> tuple[dict[str, object], str]:
    provider = build_calendar_event_prefill_provider()
    provider_input_payload = with_llm_personalization(
        session, FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION, input_payload
    )
    now = jst_iso()
    try:
        provider_response = provider.complete_json(
            function_type=FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION,
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
        id=f"llm_run_{uuid.uuid4().hex}",
        function_type=FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION,
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
        raise json_error(
            502,
            "LLM_PREFILL_FAILED",
            error_message or "Calendar event prefill failed.",
        )
    return normalize_calendar_event_prefill_output(output), llm_run.id


def calendar_case_for_mail(
    session: DatabaseSession,
    *,
    message: GmailMessage,
    preferred_case_id: str | None,
) -> Case | None:
    if preferred_case_id is not None:
        return session.get(Case, preferred_case_id)
    thread_message_ids = session.scalars(
        select(GmailMessage.id)
        .where(GmailMessage.thread_id == message.thread_id)
        .order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc())
    ).all()
    return session.scalars(
        select(Case)
        .join(CaseMailLink, CaseMailLink.case_id == Case.id)
        .where(CaseMailLink.message_id.in_(thread_message_ids))
        .group_by(Case.id)
        .order_by(Case.archived_at.is_not(None), Case.updated_at.desc(), Case.name.asc())
        .limit(1)
    ).first()


def calendar_event_prefill_input_from_mail(
    session: DatabaseSession,
    *,
    message: GmailMessage,
    case: Case | None,
    prompt: str | None,
) -> dict[str, object]:
    current_body_text, quoted_reply_context = split_quoted_reply_sections(
        message.body_text or ""
    )
    mail_summary = session.scalar(
        select(MailSummary).where(MailSummary.message_id == message.id)
    )
    thread_summary = session.scalar(
        select(MailThreadSummary).where(MailThreadSummary.thread_id == message.thread_id)
    )
    return {
        "prompt": prompt or "",
        "current_date": jst_now().date().isoformat(),
        "case": {
            "id": case.id,
            "name": case.name,
            "description": case.description,
            "open_when_date": case.open_when_date,
            "closed_when_text": case.closed_when_text,
        }
        if case is not None
        else None,
        "mail": {
            "id": message.id,
            "gmail_thread_id": message.gmail_thread_id,
            "received_at": message.received_at,
            "subject": message.subject,
            "from": f"{message.from_name or ''} <{message.from_address}>",
            "to": message.to_addresses_json,
            "cc": message.cc_addresses_json,
            "snippet": message.snippet,
            "current_message_body": current_body_text or message.body_text or "",
            "quoted_reply_context": quoted_reply_context,
        },
        "summaries": {
            "mail_summary": mail_summary.summary_text if mail_summary is not None else "",
            "thread_summary": thread_summary.summary_text
            if thread_summary is not None
            else "",
        },
    }


def upsert_calendar_event_from_google_response(
    session: DatabaseSession,
    *,
    calendar_id: str,
    item: dict[str, object],
    now: str,
) -> CalendarEvent:
    external_event_id = item.get("id") if isinstance(item.get("id"), str) else None
    if external_event_id is None or external_event_id.strip() == "":
        raise json_error(502, "GOOGLE_CALENDAR_API_ERROR", "Calendar API did not return event id.")
    normalized_event = normalized_google_calendar_event(item)
    if normalized_event is None:
        raise json_error(502, "GOOGLE_CALENDAR_API_ERROR", "Calendar API returned invalid event.")
    event = session.scalar(
        select(CalendarEvent)
        .where(CalendarEvent.source == "google")
        .where(CalendarEvent.external_calendar_id == calendar_id)
        .where(CalendarEvent.external_event_id == external_event_id)
    )
    if event is None:
        event = CalendarEvent(
            id=f"calendar_event_{uuid.uuid4().hex}",
            source="google",
            external_calendar_id=calendar_id,
            external_event_id=external_event_id,
            external_etag=normalized_event["external_etag"],
            external_ical_uid=normalized_event["external_ical_uid"],
            external_html_link=normalized_event["external_html_link"],
            external_updated_at=normalized_event["external_updated_at"],
            google_status=normalized_event["google_status"],
            summary=str(normalized_event["summary"]),
            description=normalized_event["description"],  # type: ignore[arg-type]
            location=normalized_event["location"],  # type: ignore[arg-type]
            start_at=str(normalized_event["start_at"]),
            end_at=str(normalized_event["end_at"]),
            all_day=int(normalized_event["all_day"]),
            time_zone=normalized_event["time_zone"],  # type: ignore[arg-type]
            recurring_event_id=normalized_event["recurring_event_id"],  # type: ignore[arg-type]
            academic_series_id=None,
            attendance_requirement="required",
            tags_json=None,
            metadata_json=None,
            sync_status="synced",
            last_synced_at=now,
            local_note=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(event)
        session.flush()
        return event
    apply_google_calendar_event_update(event, normalized_event, now)
    return event


def ensure_calendar_event_link(
    session: DatabaseSession,
    *,
    event: CalendarEvent,
    linked_type: str,
    linked_id: str | None,
    now: str,
    role: str = "related",
) -> CalendarEventLink | None:
    if linked_id is None or linked_id.strip() == "":
        return None
    validate_calendar_event_link_target(session, linked_type, linked_id)
    existing = session.scalar(
        select(CalendarEventLink)
        .where(CalendarEventLink.calendar_event_id == event.id)
        .where(CalendarEventLink.linked_type == linked_type)
        .where(CalendarEventLink.linked_id == linked_id)
        .where(CalendarEventLink.role == role)
    )
    if existing is not None:
        return existing
    link = CalendarEventLink(
        id=f"calendar_event_link_{uuid.uuid4().hex}",
        calendar_event_id=event.id,
        linked_type=linked_type,
        linked_id=linked_id,
        role=role,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(link)
    session.flush()
    return link


def inherit_calendar_event_links_from_recurring_master(
    session: DatabaseSession,
    *,
    event: CalendarEvent,
    now: str,
) -> None:
    if event.recurring_event_id is None or event.recurring_event_id.strip() == "":
        return
    if event.external_calendar_id is None:
        return
    master_event = session.scalar(
        select(CalendarEvent)
        .where(CalendarEvent.source == event.source)
        .where(CalendarEvent.external_calendar_id == event.external_calendar_id)
        .where(CalendarEvent.external_event_id == event.recurring_event_id)
    )
    if master_event is None:
        return
    master_links = session.scalars(
        select(CalendarEventLink).where(CalendarEventLink.calendar_event_id == master_event.id)
    ).all()
    for link in master_links:
        ensure_calendar_event_link(
            session,
            event=event,
            linked_type=link.linked_type,
            linked_id=link.linked_id,
            role=link.role,
            now=now,
        )


def propagate_calendar_event_links_to_recurring_instances(
    session: DatabaseSession,
    *,
    master_event: CalendarEvent,
    now: str,
) -> None:
    if master_event.external_calendar_id is None or master_event.external_event_id is None:
        return
    child_events = session.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.source == master_event.source)
        .where(CalendarEvent.external_calendar_id == master_event.external_calendar_id)
        .where(CalendarEvent.recurring_event_id == master_event.external_event_id)
    ).all()
    for child_event in child_events:
        inherit_calendar_event_links_from_recurring_master(
            session,
            event=child_event,
            now=now,
        )


def gmail_api_send_raw_message(
    access_token: str,
    raw_message: bytes,
    *,
    thread_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "raw": base64.urlsafe_b64encode(raw_message).decode("ascii").rstrip("="),
    }
    if thread_id is not None and thread_id.strip() != "":
        payload["threadId"] = thread_id
    return gmail_api_post_json("/users/me/messages/send", access_token, payload)


def read_google_error_details(exc: HTTPError) -> str | None:
    try:
        raw_body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    if raw_body.strip() == "":
        return None
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError:
        return raw_body[:300]
    if not isinstance(data, dict):
        return raw_body[:300]
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return raw_body[:300]


def latest_unloaded_gmail_message_id(
    session: DatabaseSession,
    access_token: str,
) -> str | None:
    page_token = None
    checked = 0
    while checked < 100:
        params: dict[str, object] = {
            "maxResults": 20,
            "includeSpamTrash": "false",
            "q": GMAIL_EXCLUDED_IMPORT_QUERY,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        data = gmail_api_get_json("/users/me/messages", access_token, params)
        messages = data.get("messages")
        if not isinstance(messages, list) or len(messages) == 0:
            return None
        for item in messages:
            if not isinstance(item, dict):
                continue
            gmail_message_id = item.get("id")
            if not isinstance(gmail_message_id, str) or gmail_message_id.strip() == "":
                continue
            checked += 1
            exists = session.scalar(
                select(GmailMessage.id).where(
                    GmailMessage.gmail_message_id == gmail_message_id
                )
            )
            if exists is None and not gmail_message_id_is_draft(
                gmail_message_id,
                access_token,
            ):
                return gmail_message_id
            if checked >= 100:
                break
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or next_page_token.strip() == "":
            return None
        page_token = next_page_token
    return None


def latest_gmail_auto_import_plan_until_loaded(
    session: DatabaseSession,
    access_token: str,
    *,
    max_messages: int,
    run_at: datetime | None = None,
) -> GmailAutoImportPlan:
    page_token = None
    checked = 0
    max_checked = GMAIL_AUTO_IMPORT_SCAN_MAX_MESSAGES
    effective_run_at = run_at or jst_now()
    oldest_import_at = auto_import_oldest_allowed_at(effective_run_at)
    loaded_stop_at = auto_import_loaded_stop_at(effective_run_at)
    import_message_ids: list[str] = []
    unloaded_dates: set[str] = set()
    reached_loaded_message = False
    while True:
        params: dict[str, object] = {
            "maxResults": 100,
            "includeSpamTrash": "false",
            "q": gmail_auto_import_query(oldest_import_at),
        }
        if page_token is not None:
            params["pageToken"] = page_token
        data = gmail_api_get_json("/users/me/messages", access_token, params)
        messages = data.get("messages")
        if not isinstance(messages, list) or len(messages) == 0:
            return GmailAutoImportPlan(
                import_message_ids=import_message_ids,
                unloaded_dates=sorted(unloaded_dates, reverse=True),
                reached_loaded_message=reached_loaded_message,
                checked_count=checked,
                stop_reason="no_messages",
            )
        for item in messages:
            if not isinstance(item, dict):
                continue
            gmail_message_id = item.get("id")
            if not isinstance(gmail_message_id, str) or gmail_message_id.strip() == "":
                continue
            checked += 1
            gmail_metadata = gmail_api_get_json(
                f"/users/me/messages/{gmail_message_id}",
                access_token,
                {"format": "metadata"},
            )
            if gmail_message_is_future_dated(gmail_metadata):
                if checked >= max_checked:
                    return GmailAutoImportPlan(
                        import_message_ids=import_message_ids,
                        unloaded_dates=sorted(unloaded_dates, reverse=True),
                        reached_loaded_message=reached_loaded_message,
                        checked_count=checked,
                        stop_reason="scan_limit",
                        stopped_gmail_message_id=gmail_message_id,
                        stopped_received_at=gmail_received_at(gmail_metadata),
                    )
                continue
            received_at = gmail_message_received_datetime(gmail_metadata)
            if received_at is not None and received_at < oldest_import_at:
                return GmailAutoImportPlan(
                    import_message_ids=import_message_ids,
                    unloaded_dates=sorted(unloaded_dates, reverse=True),
                    reached_loaded_message=reached_loaded_message,
                    checked_count=checked,
                    stop_reason="lookback_limit",
                    stopped_gmail_message_id=gmail_message_id,
                    stopped_received_at=gmail_received_at(gmail_metadata),
                )
            exists = session.scalar(
                select(GmailMessage.id).where(
                    GmailMessage.gmail_message_id == gmail_message_id
                )
            )
            if exists is not None:
                reached_loaded_message = True
                if received_at is None or received_at <= loaded_stop_at:
                    return GmailAutoImportPlan(
                        import_message_ids=import_message_ids,
                        unloaded_dates=sorted(unloaded_dates, reverse=True),
                        reached_loaded_message=True,
                        checked_count=checked,
                        stop_reason="loaded_message",
                        stopped_gmail_message_id=gmail_message_id,
                        stopped_received_at=gmail_received_at(gmail_metadata),
                    )
                if checked >= max_checked:
                    return GmailAutoImportPlan(
                        import_message_ids=import_message_ids,
                        unloaded_dates=sorted(unloaded_dates, reverse=True),
                        reached_loaded_message=True,
                        checked_count=checked,
                        stop_reason="scan_limit",
                        stopped_gmail_message_id=gmail_message_id,
                        stopped_received_at=gmail_received_at(gmail_metadata),
                    )
                continue
            if gmail_message_is_draft(gmail_metadata):
                continue
            if len(import_message_ids) < max_messages:
                import_message_ids.append(gmail_message_id)
            else:
                unloaded_dates.add(gmail_received_at(gmail_metadata)[:10])
            if checked >= max_checked:
                return GmailAutoImportPlan(
                    import_message_ids=import_message_ids,
                    unloaded_dates=sorted(unloaded_dates, reverse=True),
                    reached_loaded_message=reached_loaded_message,
                    checked_count=checked,
                    stop_reason="scan_limit",
                    stopped_gmail_message_id=gmail_message_id,
                    stopped_received_at=gmail_received_at(gmail_metadata),
                )
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or next_page_token.strip() == "":
            return GmailAutoImportPlan(
                import_message_ids=import_message_ids,
                unloaded_dates=sorted(unloaded_dates, reverse=True),
                reached_loaded_message=reached_loaded_message,
                checked_count=checked,
                stop_reason="no_next_page",
            )
        page_token = next_page_token


def auto_import_oldest_allowed_at(run_at: datetime) -> datetime:
    jst_run_at = run_at.astimezone(JST)
    return (jst_run_at - timedelta(days=GMAIL_AUTO_IMPORT_LOOKBACK_DAYS)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def auto_import_loaded_stop_at(run_at: datetime) -> datetime:
    jst_run_at = run_at.astimezone(JST)
    return (jst_run_at - timedelta(days=1)).replace(
        hour=23,
        minute=0,
        second=0,
        microsecond=0,
    )


def gmail_auto_import_query(oldest_import_at: datetime) -> str:
    query_after_date = oldest_import_at.date() - timedelta(days=1)
    return (
        f"after:{query_after_date.strftime('%Y/%m/%d')} "
        f"{GMAIL_EXCLUDED_IMPORT_QUERY}"
    )


def unloaded_gmail_message_ids_for_date(
    session: DatabaseSession,
    access_token: str,
    target_date: date,
) -> list[str]:
    query_start = target_date - timedelta(days=1)
    query_end = target_date + timedelta(days=2)
    query = (
        f"after:{query_start.strftime('%Y/%m/%d')} "
        f"before:{query_end.strftime('%Y/%m/%d')} "
        f"{GMAIL_EXCLUDED_IMPORT_QUERY}"
    )
    page_token = None
    checked = 0
    message_ids: list[str] = []
    seen: set[str] = set()
    while checked < GMAIL_IMPORT_BY_DATE_MAX_RESULTS:
        params: dict[str, object] = {
            "maxResults": 100,
            "includeSpamTrash": "false",
            "q": query,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        data = gmail_api_get_json("/users/me/messages", access_token, params)
        messages = data.get("messages")
        if not isinstance(messages, list) or len(messages) == 0:
            return message_ids
        for item in messages:
            if not isinstance(item, dict):
                continue
            gmail_message_id = item.get("id")
            if not isinstance(gmail_message_id, str) or gmail_message_id.strip() == "":
                continue
            if gmail_message_id in seen:
                continue
            seen.add(gmail_message_id)
            checked += 1
            exists = session.scalar(
                select(GmailMessage.id).where(
                    GmailMessage.gmail_message_id == gmail_message_id
                )
            )
            if exists is None:
                message_ids.append(gmail_message_id)
            if checked >= GMAIL_IMPORT_BY_DATE_MAX_RESULTS:
                break
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or next_page_token.strip() == "":
            return message_ids
        page_token = next_page_token
    return message_ids


def gmail_message_to_mail_input(message: dict[str, object]) -> MockMailInput:
    if gmail_message_is_draft(message):
        raise json_error(
            400,
            "GOOGLE_GMAIL_DRAFT_SKIPPED",
            "Gmail drafts are not imported.",
        )
    gmail_message_id = required_string(message, "id")
    gmail_thread_id = required_string(message, "threadId")
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", "Gmail message payload is missing.")

    headers = gmail_headers(payload)
    from_name, from_address = parse_single_address(first_header(headers, "from"))
    if from_address == "":
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", "Gmail message From is missing.")
    _, sender_address = parse_single_address(first_header(headers, "sender"))
    _, reply_to_address = parse_single_address(first_header(headers, "reply-to"))

    body_parts = collect_message_bodies(payload)
    attachments = collect_message_attachments(payload)
    labels = string_list(message.get("labelIds"))
    return MockMailInput(
        gmail_message_id=gmail_message_id,
        gmail_thread_id=gmail_thread_id,
        from_address=from_address,
        received_at=gmail_received_at(message),
        subject=first_header(headers, "subject"),
        from_name=from_name or None,
        sender_address=sender_address or None,
        reply_to_address=reply_to_address or None,
        to_addresses=parse_address_list(first_header(headers, "to")),
        cc_addresses=parse_address_list(first_header(headers, "cc")),
        bcc_addresses=parse_address_list(first_header(headers, "bcc")),
        message_id_header=first_header(headers, "message-id"),
        in_reply_to_header=first_header(headers, "in-reply-to"),
        references_header=first_header(headers, "references"),
        list_id=first_header(headers, "list-id"),
        internal_date=str(message.get("internalDate"))
        if message.get("internalDate") is not None
        else None,
        snippet=message.get("snippet") if isinstance(message.get("snippet"), str) else None,
        body_text=body_parts["text"],
        body_html=body_parts["html"],
        gmail_link=f"https://mail.google.com/mail/u/0/#all/{gmail_message_id}",
        gmail_labels=labels,
        external_starred="STARRED" in labels,
        attachments=attachments,
    )


def required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", f"Gmail message {key} is missing.")
    return value


def gmail_received_at(message: dict[str, object]) -> str:
    received_at = gmail_message_received_datetime(message)
    if received_at is not None:
        now = jst_now()
        if received_at > now + timedelta(minutes=5):
            return jst_iso(now)
        return received_at.isoformat()
    return jst_iso()


def gmail_message_received_datetime(message: dict[str, object]) -> datetime | None:
    internal_date = message.get("internalDate")
    if isinstance(internal_date, str) and internal_date.isdigit():
        return datetime.fromtimestamp(int(internal_date) / 1000, JST)
    return None


def gmail_message_is_future_dated(message: dict[str, object]) -> bool:
    received_at = gmail_message_received_datetime(message)
    if received_at is None:
        return False
    return received_at > jst_now() + timedelta(minutes=5)


def gmail_headers(payload: dict[str, object]) -> dict[str, list[str]]:
    raw_headers = payload.get("headers")
    headers: dict[str, list[str]] = {}
    if not isinstance(raw_headers, list):
        return headers
    for item in raw_headers:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str):
            headers.setdefault(name.lower(), []).append(value)
    return headers


def first_header(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name)
    if not values:
        return None
    return values[0]


def parse_single_address(value: str | None) -> tuple[str, str]:
    if value is None:
        return "", ""
    name, address = parseaddr(value)
    return name, address.strip().lower()


def parse_address_list(value: str | None) -> list[str]:
    if value is None:
        return []
    return [address.strip().lower() for _, address in getaddresses([value]) if address]


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def gmail_message_id_is_draft(
    gmail_message_id: str,
    access_token: str,
) -> bool:
    gmail_message = gmail_api_get_json(
        f"/users/me/messages/{gmail_message_id}",
        access_token,
        {"format": "metadata"},
    )
    return gmail_message_is_draft(gmail_message)


def gmail_message_is_draft(message: dict[str, object]) -> bool:
    labels = string_list(message.get("labelIds"))
    return any(label.lower() == "draft" for label in labels)


def collect_message_bodies(payload: dict[str, object]) -> dict[str, str | None]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    def collect(part: dict[str, object]) -> None:
        mime_type = part.get("mimeType")
        body = part.get("body")
        if isinstance(body, dict):
            decoded = decode_gmail_body_data(body.get("data"))
            if decoded is not None:
                if mime_type == "text/plain":
                    text_parts.append(decoded)
                elif mime_type == "text/html":
                    html_parts.append(decoded)
        parts = part.get("parts")
        if isinstance(parts, list):
            for child in parts:
                if isinstance(child, dict):
                    collect(child)

    collect(payload)
    return {
        "text": "\n".join(text_parts).strip() or None,
        "html": "\n".join(html_parts).strip() or None,
    }


def collect_message_attachments(payload: dict[str, object]) -> list[MailAttachmentInput]:
    attachments: list[MailAttachmentInput] = []

    def collect(part: dict[str, object]) -> None:
        filename = part.get("filename")
        body = part.get("body")
        headers = gmail_headers(part)
        content_disposition = (
            first_header(headers, "content-disposition") or ""
        ).strip().lower()
        content_id = (first_header(headers, "content-id") or "").strip()
        mime_type = part.get("mimeType")
        if (
            isinstance(filename, str)
            and filename.strip() != ""
            and isinstance(body, dict)
        ):
            attachment_id = body.get("attachmentId")
            if isinstance(attachment_id, str) and attachment_id.strip() != "":
                size = body.get("size")
                byte_size = size if isinstance(size, int) else 0
                normalized_mime_type = mime_type if isinstance(mime_type, str) else None
                if not is_probable_generated_inline_image(
                    filename=filename,
                    mime_type=normalized_mime_type,
                    byte_size=byte_size,
                    content_disposition=content_disposition,
                    content_id=content_id,
                ):
                    attachments.append(
                        MailAttachmentInput(
                            gmail_attachment_id=attachment_id.strip(),
                            filename=filename.strip(),
                            mime_type=normalized_mime_type,
                            byte_size=byte_size,
                            part_id=part.get("partId") if isinstance(part.get("partId"), str) else None,
                        )
                    )
        parts = part.get("parts")
        if isinstance(parts, list):
            for child in parts:
                if isinstance(child, dict):
                    collect(child)

    collect(payload)
    return attachments


def decode_gmail_body_data(value: object) -> str | None:
    if not isinstance(value, str) or value == "":
        return None
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
        "utf-8",
        errors="replace",
    )
