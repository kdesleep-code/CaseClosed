from __future__ import annotations

import sqlite3
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from conftest import TEST_PASSWORD

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
SESSION_URL = "/api/v1/auth/session"


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
