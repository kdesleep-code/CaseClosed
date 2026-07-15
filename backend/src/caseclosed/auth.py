from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import AppSetting
from caseclosed.db.models import AuthLoginAttempt
from caseclosed.db.models import ClientCertificate
from caseclosed.db.models import Session
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now
from caseclosed.db.runtime import parse_iso_datetime
from caseclosed.settings import get_bootstrap_password
from caseclosed.settings import get_low_mail_review_password
from caseclosed.settings import get_session_lifetime_override_minutes
from caseclosed.settings import is_secure_cookie_enabled

SESSION_COOKIE_NAME = "caseclosed_session"
PASSWORD_HASH_KEY = "auth_password_hash"
LOW_MAIL_REVIEW_PASSWORD_HASH_KEY = "auth_low_mail_review_password_hash"
LOGIN_LOCK_KEY = "auth_login_locked"
ACCESS_MODE_FULL = "full"
ACCESS_MODE_LOW_MAIL_REVIEW = "low_mail_review"

password_hasher = PasswordHasher()
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


def json_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"ok": False, "error": {"code": code, "message": message}},
    )


def read_setting(session: DatabaseSession, key: str) -> AppSetting | None:
    return session.scalar(select(AppSetting).where(AppSetting.key == key))


def setting_int(session: DatabaseSession, key: str, default: int) -> int:
    setting = read_setting(session, key)
    return int(setting.value_json) if setting is not None else default


def session_lifetime(session: DatabaseSession) -> timedelta:
    override_minutes = get_session_lifetime_override_minutes()
    if override_minutes is not None:
        return timedelta(minutes=override_minutes)

    return timedelta(hours=setting_int(session, "session_lifetime_hours", 24))


def upsert_setting(session: DatabaseSession, key: str, value_json: str) -> None:
    setting = read_setting(session, key)
    if setting is None:
        session.add(
            AppSetting(
                id=f"setting_{key}",
                key=key,
                value_json=value_json,
                updated_at=jst_iso(),
            )
        )
        return

    setting.value_json = value_json
    setting.updated_at = jst_iso()


def ensure_password_hash(session: DatabaseSession) -> str:
    setting = read_setting(session, PASSWORD_HASH_KEY)
    if setting is not None:
        return setting.value_json

    password = get_bootstrap_password()
    if password is None:
        raise json_error(503, "PASSWORD_NOT_CONFIGURED", "Password is not configured.")

    password_hash = password_hasher.hash(password)
    upsert_setting(session, PASSWORD_HASH_KEY, password_hash)
    session.flush()
    return password_hash


def verify_password(session: DatabaseSession, password: str) -> bool:
    try:
        return password_hasher.verify(ensure_password_hash(session), password)
    except VerifyMismatchError:
        return False


def ensure_low_mail_review_password_hash(session: DatabaseSession) -> str | None:
    setting = read_setting(session, LOW_MAIL_REVIEW_PASSWORD_HASH_KEY)
    if setting is not None:
        return setting.value_json

    password = get_low_mail_review_password()
    if password is None:
        return None
    password_hash = password_hasher.hash(password)
    upsert_setting(session, LOW_MAIL_REVIEW_PASSWORD_HASH_KEY, password_hash)
    session.flush()
    return password_hash


def verify_low_mail_review_password(
    session: DatabaseSession,
    password: str,
) -> bool:
    password_hash = ensure_low_mail_review_password_hash(session)
    if password_hash is None:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def client_fingerprint(request: Request) -> str | None:
    return request.headers.get("X-Client-Cert-Fingerprint")


def attempt_context(request: Request) -> dict[str, str | None]:
    return {
        "client_fingerprint": client_fingerprint(request),
        "ip_address": request.client.host if request.client is not None else None,
        "user_agent": request.headers.get("user-agent"),
    }


def record_attempt(
    session: DatabaseSession,
    request: Request,
    *,
    success: bool,
    failure_reason: str | None = None,
) -> None:
    session.add(
        AuthLoginAttempt(
            id=f"attempt_{uuid4().hex}",
            success=int(success),
            failure_reason=failure_reason,
            attempted_at=jst_iso(),
            **attempt_context(request),
        )
    )


def consecutive_failures(session: DatabaseSession) -> int:
    recent_attempts = session.scalars(
        select(AuthLoginAttempt)
        .order_by(AuthLoginAttempt.attempted_at.desc(), AuthLoginAttempt.id.desc())
        .limit(5)
    ).all()

    failures = 0
    for attempt in recent_attempts:
        if attempt.success:
            break
        failures += 1
    return failures


def login_is_locked(session: DatabaseSession) -> bool:
    setting = read_setting(session, LOGIN_LOCK_KEY)
    return setting is not None and setting.value_json == "true"


def get_or_create_test_certificate(
    session: DatabaseSession,
    request: Request,
) -> ClientCertificate | None:
    fingerprint = client_fingerprint(request)
    if fingerprint is None:
        return None

    certificate = session.scalar(
        select(ClientCertificate).where(
            ClientCertificate.certificate_fingerprint == fingerprint
        )
    )
    if certificate is not None:
        certificate.last_seen_at = jst_iso()
        certificate.updated_at = jst_iso()
        return certificate

    now = jst_now()
    certificate = ClientCertificate(
        id=f"cert_{uuid4().hex}",
        device_name="Bootstrap device",
        certificate_fingerprint=fingerprint,
        issued_at=jst_iso(now),
        expires_at=jst_iso(now + timedelta(days=180)),
        last_seen_at=jst_iso(now),
        created_at=jst_iso(now),
        updated_at=jst_iso(now),
    )
    session.add(certificate)
    return certificate


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_from_cookie(
    session: DatabaseSession,
    request: Request,
) -> Session | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return None

    app_session = session.scalar(
        select(Session).where(Session.session_token_hash == hash_session_token(token))
    )
    if app_session is None or app_session.logout_at is not None:
        return None
    now = jst_now()
    lifetime_cutoff = now - session_lifetime(session)
    if (
        parse_iso_datetime(app_session.expires_at) <= now
        or parse_iso_datetime(app_session.login_at) <= lifetime_cutoff
    ):
        return None
    return app_session


def session_access_mode(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    return (
        ACCESS_MODE_LOW_MAIL_REVIEW
        if token.startswith(f"{ACCESS_MODE_LOW_MAIL_REVIEW}.")
        else ACCESS_MODE_FULL
    )


def require_session_access_mode(
    session: DatabaseSession,
    request: Request,
    required_mode: str,
) -> Session:
    app_session = session_from_cookie(session, request)
    if app_session is None:
        raise json_error(401, "UNAUTHORIZED", "No active session.")
    if session_access_mode(request) != required_mode:
        raise json_error(403, "FORBIDDEN", "This session cannot access this resource.")
    return app_session


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if login_is_locked(session):
        record_attempt(session, request, success=False, failure_reason="locked")
        session.commit()
        raise json_error(423, "LOGIN_LOCKED", "Login is locked.")

    access_mode = ACCESS_MODE_FULL
    if not verify_password(session, payload.password):
        if verify_low_mail_review_password(session, payload.password):
            access_mode = ACCESS_MODE_LOW_MAIL_REVIEW
        else:
            record_attempt(session, request, success=False, failure_reason="invalid_password")
            if consecutive_failures(session) >= setting_int(
                session,
                "login_failure_limit",
                5,
            ):
                upsert_setting(session, LOGIN_LOCK_KEY, "true")
            session.commit()
            raise json_error(401, "INVALID_CREDENTIALS", "Invalid password.")

    record_attempt(session, request, success=True)
    certificate = get_or_create_test_certificate(session, request)
    now = jst_now()
    expires_at = jst_iso(now + session_lifetime(session))
    session_token = f"{access_mode}.{secrets.token_urlsafe(32)}"
    session.add(
        Session(
            id=f"session_{uuid4().hex}",
            client_certificate_id=certificate.id if certificate is not None else None,
            session_token_hash=hash_session_token(session_token),
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client is not None else None,
            login_at=jst_iso(now),
            expires_at=expires_at,
            created_at=jst_iso(now),
            updated_at=jst_iso(now),
        )
    )
    session.commit()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=is_secure_cookie_enabled(),
        samesite="lax",
        expires=expires_at,
    )
    return {
        "ok": True,
        "data": {
            "session_expires_at": expires_at,
            "ip_address": request.client.host if request.client is not None else None,
            "device_name": certificate.device_name if certificate is not None else None,
            "access_mode": access_mode,
        },
    }


@router.get("/session")
def session_status(
    request: Request,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    app_session = session_from_cookie(session, request)
    if app_session is None:
        raise json_error(401, "UNAUTHORIZED", "No active session.")

    certificate = (
        session.get(ClientCertificate, app_session.client_certificate_id)
        if app_session.client_certificate_id is not None
        else None
    )
    return {
        "ok": True,
        "data": {
            "authenticated": True,
            "session_expires_at": app_session.expires_at,
            "client_certificate_id": app_session.client_certificate_id,
            "device_name": certificate.device_name if certificate is not None else None,
            "ip_address": app_session.ip_address,
            "access_mode": session_access_mode(request),
        },
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    app_session = session_from_cookie(session, request)
    if app_session is not None:
        app_session.logout_at = jst_iso()
        app_session.updated_at = jst_iso()
        session.commit()

    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True, "data": {}}
