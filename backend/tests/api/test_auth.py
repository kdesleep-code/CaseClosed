from __future__ import annotations

import sqlite3
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


def test_login_creates_a_24_hour_session(client, certificate_headers) -> None:
    response = login(client, certificate_headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["session_expires_at"]
    assert "set-cookie" in response.headers


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


def test_logout_invalidates_session(client, certificate_headers) -> None:
    assert login(client, certificate_headers).status_code == 200

    logout_response = client.post(LOGOUT_URL, headers=certificate_headers)
    session_response = client.get(SESSION_URL, headers=certificate_headers)

    assert logout_response.status_code == 200
    assert_session_is_rejected(session_response)

