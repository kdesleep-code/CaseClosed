from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from email import policy
from email.parser import BytesParser
from datetime import timedelta
from pathlib import Path

from conftest import TEST_PASSWORD

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
SESSION_URL = "/api/v1/auth/session"
PASSWORD_URL = "/api/v1/auth/password"
LOW_MAIL_REVIEW_PASSWORD_URL = "/api/v1/auth/low-mail-review-password"
PASSWORD_RESET_URL = "/api/v1/auth/password-reset"


def login(client, certificate_headers: dict[str, str], password: str = TEST_PASSWORD):
    return client.post(
        LOGIN_URL,
        json={"password": password},
        headers=certificate_headers,
    )


def assert_session_is_rejected(response) -> None:
    if response.status_code != 200:
        assert response.status_code in {401, 403}
        return

    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["authenticated"] is False


def test_login_creates_a_session(client, certificate_headers) -> None:
    response = login(client, certificate_headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["session_expires_at"]
    assert response.json()["data"]["session_expires_at"].endswith("+09:00")
    assert response.json()["data"]["ip_address"] == "testclient"
    assert "set-cookie" in response.headers


def test_login_session_expires_after_24_hours(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    response = login(client, certificate_headers)

    with sqlite3.connect(database_path) as connection:
        login_at = connection.execute(
            "SELECT login_at FROM sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]

    expires_at = response.json()["data"]["session_expires_at"]
    assert datetime.fromisoformat(expires_at) - datetime.fromisoformat(login_at) == (
        timedelta(hours=24)
    )


def test_login_cookie_is_httponly_and_samesite_lax(
    client,
    certificate_headers,
) -> None:
    response = login(client, certificate_headers)

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_production_login_cookie_is_secure(
    client,
    certificate_headers,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASECLOSED_ENV", "production")

    response = login(client, certificate_headers)

    assert "secure" in response.headers["set-cookie"].lower()


def test_four_failed_logins_do_not_lock_a_following_success(
    client,
    certificate_headers,
) -> None:
    for _ in range(4):
        response = login(client, certificate_headers, password="wrong password")
        assert response.status_code in {401, 403}

    response = login(client, certificate_headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_five_failed_logins_lock_later_login(client, certificate_headers) -> None:
    for _ in range(5):
        response = login(client, certificate_headers, password="wrong password")
        assert response.status_code in {401, 403, 423}

    response = login(client, certificate_headers)

    assert response.status_code in {401, 403, 423}
    assert response.json()["ok"] is False


def test_five_failed_logins_persist_login_lock(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    for _ in range(5):
        login(client, certificate_headers, password="wrong password")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = 'auth_login_locked'"
        ).fetchone()

    assert row == ("true",)


def test_session_check_reports_authenticated_session(
    client,
    certificate_headers,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    response = client.get(SESSION_URL, headers=certificate_headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["authenticated"] is True
    assert response.json()["data"]["session_expires_at"]
    assert response.json()["data"]["ip_address"] == "testclient"


def test_expired_session_is_rejected(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = ?",
            ("2000-01-01T00:00:00Z",),
        )
        connection.commit()

    response = client.get(SESSION_URL, headers=certificate_headers)

    assert_session_is_rejected(response)


def test_development_lifetime_rejects_an_old_session(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE sessions SET login_at = ?",
            ("2000-01-01T00:00:00Z",),
        )
        connection.commit()

    response = client.get(SESSION_URL, headers=certificate_headers)

    assert_session_is_rejected(response)


def test_logout_invalidates_session(client, certificate_headers) -> None:
    assert login(client, certificate_headers).status_code == 200

    logout_response = client.post(LOGOUT_URL, headers=certificate_headers)
    session_response = client.get(SESSION_URL, headers=certificate_headers)

    assert logout_response.status_code == 200
    assert_session_is_rejected(session_response)


def test_password_is_stored_as_hash_after_bootstrap_login(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = 'auth_password_hash'"
        ).fetchone()

    assert row is not None
    assert TEST_PASSWORD not in row[0]
    assert row[0].startswith("$argon2")


def test_login_attempts_record_failure_then_success(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    login(client, certificate_headers, password="wrong password")
    assert login(client, certificate_headers).status_code == 200

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT client_fingerprint, success, failure_reason
            FROM auth_login_attempts
            ORDER BY attempted_at, id
            """
        ).fetchall()

    assert rows == [
        (
            certificate_headers["X-Client-Cert-Fingerprint"],
            0,
            "invalid_password",
        ),
        (certificate_headers["X-Client-Cert-Fingerprint"], 1, None),
    ]


def test_low_mail_review_password_creates_restricted_session(
    client,
    certificate_headers,
    monkeypatch,
    database_path: Path,
) -> None:
    review_password = "review-only-password"
    monkeypatch.setenv("CASECLOSED_LOW_MAIL_REVIEW_PASSWORD", review_password)

    response = login(client, certificate_headers, password=review_password)

    assert response.status_code == 200
    assert response.json()["data"]["access_mode"] == "low_mail_review"
    session_response = client.get(SESSION_URL, headers=certificate_headers)
    assert session_response.json()["data"]["access_mode"] == "low_mail_review"
    with sqlite3.connect(database_path) as connection:
        password_hash = connection.execute(
            "SELECT value_json FROM app_settings "
            "WHERE key = 'auth_low_mail_review_password_hash'"
        ).fetchone()[0]
    assert review_password not in password_hash
    assert password_hash.startswith("$argon2")


def test_low_mail_review_password_does_not_count_as_failed_login(
    client,
    certificate_headers,
    monkeypatch,
    database_path: Path,
) -> None:
    monkeypatch.setenv("CASECLOSED_LOW_MAIL_REVIEW_PASSWORD", "review-only-password")

    assert login(
        client,
        certificate_headers,
        password="review-only-password",
    ).status_code == 200

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT success, failure_reason FROM auth_login_attempts "
            "ORDER BY attempted_at DESC, id DESC LIMIT 1"
        ).fetchone()
    assert row == (1, None)


def test_full_password_can_be_changed_from_authenticated_session(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    new_password = "new-full-password-2026"
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        PASSWORD_URL,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": new_password,
        },
        headers=certificate_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["password_type"] == "full"
    assert client.post(LOGOUT_URL, headers=certificate_headers).status_code == 200
    assert login(client, certificate_headers).status_code == 401
    next_login = login(client, certificate_headers, password=new_password)
    assert next_login.status_code == 200
    with sqlite3.connect(database_path) as connection:
        password_hash = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = 'auth_password_hash'"
        ).fetchone()[0]
        audit = connection.execute(
            "SELECT action_type, target_id FROM audit_logs "
            "WHERE target_type = 'auth_password' ORDER BY occurred_at DESC LIMIT 1"
        ).fetchone()
    assert new_password not in password_hash
    assert password_hash.startswith("$argon2")
    assert audit == ("auth_password_changed", "full")


def test_password_change_rejects_invalid_current_password(
    client,
    certificate_headers,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        PASSWORD_URL,
        json={
            "current_password": "incorrect-current-password",
            "new_password": "new-full-password-2026",
        },
        headers=certificate_headers,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "CURRENT_PASSWORD_INVALID"
    assert login(client, certificate_headers).status_code == 200


def test_password_change_rejects_short_password(client, certificate_headers) -> None:
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        PASSWORD_URL,
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
        headers=certificate_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PASSWORD_TOO_SHORT"


def test_low_mail_review_password_can_be_set_from_maintenance_session(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    review_password = "new-review-password-2026"
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        LOW_MAIL_REVIEW_PASSWORD_URL,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": review_password,
        },
        headers=certificate_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["password_type"] == "low_mail_review"
    assert client.post(LOGOUT_URL, headers=certificate_headers).status_code == 200
    review_login = login(client, certificate_headers, password=review_password)
    assert review_login.status_code == 200
    assert review_login.json()["data"]["access_mode"] == "low_mail_review"
    with sqlite3.connect(database_path) as connection:
        password_hash = connection.execute(
            "SELECT value_json FROM app_settings "
            "WHERE key = 'auth_low_mail_review_password_hash'"
        ).fetchone()[0]
    assert review_password not in password_hash
    assert password_hash.startswith("$argon2")


def test_low_mail_review_session_cannot_change_passwords(
    client,
    certificate_headers,
    monkeypatch,
) -> None:
    review_password = "existing-review-password"
    monkeypatch.setenv("CASECLOSED_LOW_MAIL_REVIEW_PASSWORD", review_password)
    assert login(client, certificate_headers, password=review_password).status_code == 200

    response = client.patch(
        LOW_MAIL_REVIEW_PASSWORD_URL,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "replacement-review-password",
        },
        headers=certificate_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_password_change_invalidates_other_sessions(
    client,
    certificate_headers,
    database_path: Path,
) -> None:
    assert login(client, certificate_headers).status_code == 200
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        LOW_MAIL_REVIEW_PASSWORD_URL,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "new-review-password-2026",
        },
        headers=certificate_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["invalidated_sessions"] == 1
    with sqlite3.connect(database_path) as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE logout_at IS NULL"
        ).fetchone()[0]
    assert active_count == 1


def test_password_change_clears_login_lock(
    client,
    certificate_headers,
) -> None:
    new_password = "new-full-password-after-lock"
    assert login(client, certificate_headers).status_code == 200
    for _ in range(5):
        login(client, certificate_headers, password="wrong password")

    response = client.patch(
        PASSWORD_URL,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": new_password,
        },
        headers=certificate_headers,
    )

    assert response.status_code == 200
    assert client.post(LOGOUT_URL, headers=certificate_headers).status_code == 200
    assert login(client, certificate_headers, password=new_password).status_code == 200



def test_password_change_accepts_eight_characters(
    client,
    certificate_headers,
) -> None:
    assert login(client, certificate_headers).status_code == 200

    response = client.patch(
        PASSWORD_URL,
        json={"current_password": TEST_PASSWORD, "new_password": "Abc12345"},
        headers=certificate_headers,
    )

    assert response.status_code == 200
    assert login(client, certificate_headers, password="Abc12345").status_code == 200


def test_password_reset_emails_connected_gmail_and_invalidates_sessions(
    client,
    certificate_headers,
    database_path: Path,
    monkeypatch,
) -> None:
    from caseclosed import google_integration

    assert login(client, certificate_headers).status_code == 200
    connection_data = {
        "access_token": "reset-access-token",
        "scopes": [google_integration.GMAIL_SEND_SCOPE],
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO app_settings (id, key, value_json, updated_at) VALUES (?, ?, ?, ?)",
            (
                "setting_google_gmail_oauth_connection",
                google_integration.GMAIL_CONNECTION_KEY,
                json.dumps(connection_data),
                "2026-07-28T12:00:00+09:00",
            ),
        )
        connection.commit()

    sent_messages: list[bytes] = []
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        lambda path, access_token: {"emailAddress": "Owner@Gmail.com"},
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        lambda access_token, raw_message: sent_messages.append(raw_message) or {"id": "sent"},
    )

    response = client.post(PASSWORD_RESET_URL, headers=certificate_headers)

    assert response.status_code == 200
    assert response.json()["data"]["email_sent"] is True
    assert "password" not in response.json()["data"]
    assert len(sent_messages) == 1
    message = BytesParser(policy=policy.default).parsebytes(sent_messages[0])
    assert message["From"] == "owner@gmail.com"
    assert message["To"] == "owner@gmail.com"
    match = re.search(r"New password: ([A-Za-z0-9]+)", message.get_content())
    assert match is not None
    new_password = match.group(1)
    assert len(new_password) == 16
    assert client.get(SESSION_URL, headers=certificate_headers).status_code == 401
    assert login(client, certificate_headers, password=new_password).status_code == 200

    limited = client.post(PASSWORD_RESET_URL, headers=certificate_headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "PASSWORD_RESET_RATE_LIMITED"
    assert len(sent_messages) == 1

    with sqlite3.connect(database_path) as connection:
        audit = connection.execute(
            "SELECT action_type, session_id FROM audit_logs "
            "WHERE action_type = ? ORDER BY occurred_at DESC LIMIT 1",
            ("auth_password_reset_by_email",),
        ).fetchone()
    assert audit == ("auth_password_reset_by_email", None)


def test_password_reset_does_not_change_password_when_mail_fails(
    client,
    certificate_headers,
    database_path: Path,
    monkeypatch,
) -> None:
    from caseclosed import auth

    assert login(client, certificate_headers).status_code == 200
    with sqlite3.connect(database_path) as connection:
        original_hash = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("auth_password_hash",),
        ).fetchone()[0]

    def fail_send(*args, **kwargs):
        raise RuntimeError("simulated Gmail failure")

    monkeypatch.setattr(auth, "send_password_reset_email", fail_send)
    response = client.post(PASSWORD_RESET_URL, headers=certificate_headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PASSWORD_RESET_MAIL_FAILED"
    with sqlite3.connect(database_path) as connection:
        current_hash = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("auth_password_hash",),
        ).fetchone()[0]
        reset_marker = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("auth_password_reset_last_sent_at",),
        ).fetchone()
    assert current_hash == original_hash
    assert reset_marker is None
    assert login(client, certificate_headers).status_code == 200
