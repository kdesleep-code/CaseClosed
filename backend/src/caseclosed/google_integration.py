from __future__ import annotations

import base64
from datetime import date
from datetime import datetime
import json
import secrets
from datetime import timedelta
from email.utils import getaddresses
from email.utils import parseaddr
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import AppSetting
from caseclosed.db.models import GmailMessage
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import JST
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import parse_iso_datetime
from caseclosed.services.background_worker import kick_job_drain
from caseclosed.services.mail_ingestion import MailIngestionResult
from caseclosed.services.mail_ingestion import MockMailInput
from caseclosed.services.mail_ingestion import ingest_mock_mail
from caseclosed.settings import get_google_gmail_scopes
from caseclosed.settings import get_google_oauth_client_id
from caseclosed.settings import get_google_oauth_client_secret
from caseclosed.settings import get_google_oauth_redirect_uri

router = APIRouter(prefix="/api/v1/google/gmail", tags=["google-gmail"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GMAIL_CONNECTION_KEY = "google_gmail_oauth_connection"
GMAIL_OAUTH_STATE_KEY = "google_gmail_oauth_state"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_IMPORT_BY_DATE_MAX_RESULTS = 500


class GmailImportByDatePayload(BaseModel):
    date: str


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
    scopes = get_google_gmail_scopes()
    has_refresh_token = bool(connection.get("refresh_token"))
    connected_scopes = connection_scopes(connection) or scopes
    return {
        "configured": get_google_oauth_client_id() is not None
        and get_google_oauth_client_secret() is not None,
        "connected": has_refresh_token or bool(connection.get("access_token")),
        "connected_at": connection.get("connected_at"),
        "last_error": connection.get("last_error"),
        "scopes": connected_scopes,
        "send_enabled": GMAIL_SEND_SCOPE in connected_scopes,
        "redirect_uri": get_google_oauth_redirect_uri(),
        "has_refresh_token": has_refresh_token,
        "token_expires_at": connection.get("token_expires_at"),
        "mail_loading_enabled": False,
    }


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


@router.post("/connect-url")
def google_gmail_connect_url(
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
    write_setting_json(
        session,
        GMAIL_OAUTH_STATE_KEY,
        {"state": state, "created_at": now},
        now,
    )
    session.commit()

    params = {
        "client_id": client_id,
        "redirect_uri": get_google_oauth_redirect_uri(),
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
        return RedirectResponse("/maintenance?google_gmail=error")

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
        return RedirectResponse("/maintenance?google_gmail=error")

    token_data = exchange_authorization_code(code)
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
    return RedirectResponse("/maintenance?google_gmail=connected")


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


def parse_import_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise json_error(
            422,
            "VALIDATION_ERROR",
            "Date must be formatted as YYYY-MM-DD.",
        ) from error


def exchange_authorization_code(code: str) -> dict[str, object]:
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
            "redirect_uri": get_google_oauth_redirect_uri(),
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
            if exists is None:
                return gmail_message_id
            if checked >= 100:
                break
        next_page_token = data.get("nextPageToken")
        if not isinstance(next_page_token, str) or next_page_token.strip() == "":
            return None
        page_token = next_page_token
    return None


def unloaded_gmail_message_ids_for_date(
    session: DatabaseSession,
    access_token: str,
    target_date: date,
) -> list[str]:
    query_start = target_date - timedelta(days=1)
    query_end = target_date + timedelta(days=2)
    query = (
        f"after:{query_start.strftime('%Y/%m/%d')} "
        f"before:{query_end.strftime('%Y/%m/%d')}"
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
    )


def required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or value.strip() == "":
        raise json_error(502, "GOOGLE_GMAIL_API_ERROR", f"Gmail message {key} is missing.")
    return value


def gmail_received_at(message: dict[str, object]) -> str:
    internal_date = message.get("internalDate")
    if isinstance(internal_date, str) and internal_date.isdigit():
        received_at = datetime.fromtimestamp(int(internal_date) / 1000, JST)
        now = jst_now()
        if received_at > now + timedelta(minutes=5):
            return jst_iso(now)
        return received_at.isoformat()
    return jst_iso()


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


def decode_gmail_body_data(value: object) -> str | None:
    if not isinstance(value, str) or value == "":
        return None
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
        "utf-8",
        errors="replace",
    )
