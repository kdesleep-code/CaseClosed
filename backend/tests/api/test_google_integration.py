from __future__ import annotations

import base64
from datetime import datetime
import json
import sqlite3
from urllib.parse import parse_qs
from urllib.parse import urlparse


def test_google_gmail_status_reports_not_configured(client) -> None:
    response = client.get("/api/v1/google/gmail/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["configured"] is False
    assert data["connected"] is False
    assert data["mail_loading_enabled"] is False


def test_google_gmail_connect_url_requires_oauth_config(client) -> None:
    response = client.post("/api/v1/google/gmail/connect-url")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"


def test_google_gmail_connect_url_stores_state_without_loading_mail(
    client,
    database_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASECLOSED_GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("CASECLOSED_GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv(
        "CASECLOSED_GOOGLE_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v1/google/gmail/oauth/callback",
    )

    response = client.post("/api/v1/google/gmail/connect-url")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mail_loading_enabled"] is False
    parsed = urlparse(data["authorization_url"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["google-client-id"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["scope"] == [
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.send"
    ]

    with sqlite3.connect(database_path) as connection:
        state_row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("google_gmail_oauth_state",),
        ).fetchone()
        mail_count = connection.execute("SELECT count(1) FROM gmail_messages").fetchone()[0]

    assert state_row is not None
    assert json.loads(state_row[0])["state"] == params["state"][0]
    assert mail_count == 0


def test_google_gmail_import_latest_unloaded_uses_existing_ingestion_flow(
    client,
    database_path,
    monkeypatch,
) -> None:
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_existing",
            "gmail_thread_id": "thread_existing",
            "from_address": "existing.sender@example.com",
            "received_at": "2026-05-26T08:00:00+09:00",
        },
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "test-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "test-access-token"
        if path == "/users/me/messages":
            assert params["q"] == "-in:drafts"
            return {
                "messages": [
                    {"id": "gmail_existing"},
                    {"id": "gmail_draft"},
                    {"id": "gmail_real_new"},
                ],
            }
        if path == "/users/me/messages/gmail_draft":
            return {
                "id": "gmail_draft",
                "threadId": "thread_draft",
                "labelIds": ["DRAFT"],
                "payload": {"headers": []},
            }
        if path == "/users/me/messages/gmail_real_new":
            return {
                "id": "gmail_real_new",
                "threadId": "thread_real",
                "internalDate": "1779746400000",
                "labelIds": ["INBOX"],
                "snippet": "Real Gmail snippet",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "Real Sender <real.sender@example.com>"},
                        {"name": "To", "value": "Me <me@example.com>"},
                        {"name": "Subject", "value": "Real Gmail import"},
                        {"name": "Message-ID", "value": "<real-gmail@example.com>"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Real Gmail body"
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    response = client.post("/api/v1/google/gmail/import-latest-unloaded")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["imported"] is True
    assert data["mail"]["gmail_message_id"] == "gmail_real_new"
    assert data["mail"]["pending"] is True
    assert data["mail"]["pending_address"] == "real.sender@example.com"
    assert data["subject"] == "Real Gmail import"

    with sqlite3.connect(database_path) as connection:
        message_row = connection.execute(
            """
            SELECT gmail_message_id, gmail_thread_id, from_address, subject, body_text
            FROM gmail_messages
            WHERE gmail_message_id = 'gmail_real_new'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT effective_importance, pending_reason
            FROM mail_auto_state
            JOIN gmail_messages ON gmail_messages.id = mail_auto_state.message_id
            WHERE gmail_messages.gmail_message_id = 'gmail_real_new'
            """
        ).fetchone()

    assert message_row == (
        "gmail_real_new",
        "thread_real",
        "real.sender@example.com",
        "Real Gmail import",
        "Real Gmail body",
    )
    assert auto_row == ("pending", "unresolved_from_contact")


def test_google_gmail_import_unloaded_by_date_imports_matching_received_and_sent_mail(
    client,
    database_path,
    monkeypatch,
) -> None:
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_existing_for_day",
            "gmail_thread_id": "thread_existing_for_day",
            "from_address": "existing.sender@example.com",
            "received_at": "2026-05-26T08:00:00+09:00",
        },
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "test-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    requested_queries = []

    def gmail_message(message_id, thread_id, internal_date, subject, labels=None):
        return {
            "id": message_id,
            "threadId": thread_id,
            "internalDate": internal_date,
            "labelIds": labels or ["INBOX"],
            "snippet": subject,
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": f"{subject} <{message_id}@example.com>"},
                    {"name": "To", "value": "Me <me@example.com>"},
                    {"name": "Subject", "value": subject},
                    {"name": "Message-ID", "value": f"<{message_id}@example.com>"},
                ],
                "body": {
                    "data": base64.urlsafe_b64encode(
                        f"{subject} body".encode("utf-8")
                    ).decode("ascii").rstrip("=")
                },
            },
        }

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "test-access-token"
        if path == "/users/me/messages":
            requested_queries.append(params["q"])
            return {
                "messages": [
                    {"id": "gmail_existing_for_day"},
                    {"id": "gmail_matching_day"},
                    {"id": "gmail_next_day"},
                    {"id": "gmail_sent_day"},
                ],
            }
        if path == "/users/me/messages/gmail_matching_day":
            return gmail_message(
                "gmail_matching_day",
                "thread_matching_day",
                "1779746400000",
                "Matching day import",
            )
        if path == "/users/me/messages/gmail_next_day":
            return gmail_message(
                "gmail_next_day",
                "thread_next_day",
                "1779832800000",
                "Next day import",
            )
        if path == "/users/me/messages/gmail_sent_day":
            return gmail_message(
                "gmail_sent_day",
                "thread_sent_day",
                "1779746400000",
                "Sent day import",
                ["SENT"],
            )
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    response = client.post(
        "/api/v1/google/gmail/import-unloaded-by-date",
        json={"date": "2026-05-26"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["date"] == "2026-05-26"
    assert data["candidate_count"] == 3
    assert data["imported_count"] == 2
    assert data["skipped_out_of_date"] == 1
    assert data["items"][0]["mail"]["gmail_message_id"] == "gmail_matching_day"
    assert data["items"][1]["mail"]["gmail_message_id"] == "gmail_sent_day"
    assert requested_queries == ["after:2026/05/25 before:2026/05/28 -in:drafts"]

    with sqlite3.connect(database_path) as connection:
        imported_rows = connection.execute(
            """
            SELECT gmail_message_id, subject
            FROM gmail_messages
            WHERE gmail_message_id IN (
                'gmail_matching_day',
                'gmail_next_day',
                'gmail_sent_day'
            )
            ORDER BY gmail_message_id
            """
        ).fetchall()
        sent_auto_row = connection.execute(
            """
            SELECT mail_user_state.processed_status, mail_user_state.read_status,
                   mail_auto_state.effective_importance
            FROM gmail_messages
            JOIN mail_user_state ON mail_user_state.message_id = gmail_messages.id
            JOIN mail_auto_state ON mail_auto_state.message_id = gmail_messages.id
            WHERE gmail_messages.gmail_message_id = 'gmail_sent_day'
            """
        ).fetchone()

    assert imported_rows == [
        ("gmail_matching_day", "Matching day import"),
        ("gmail_sent_day", "Sent day import"),
    ]
    assert sent_auto_row == ("processed", "read", "sent")


def test_mail_day_stats_reports_loaded_received_and_sent_counts(client) -> None:
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_stats_received",
            "gmail_thread_id": "thread_stats_received",
            "from_address": "stats.received@example.com",
            "received_at": "2026-05-26T08:00:00+09:00",
            "subject": "Stats received",
        },
    )
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_stats_sent",
            "gmail_thread_id": "thread_stats_sent",
            "from_address": "me@example.com",
            "received_at": "2026-05-26T09:00:00+09:00",
            "subject": "Stats sent",
            "gmail_labels": ["SENT"],
        },
    )
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_stats_draft",
            "gmail_thread_id": "thread_stats_draft",
            "from_address": "me@example.com",
            "received_at": "2026-05-26T10:00:00+09:00",
            "subject": "Stats draft",
            "gmail_labels": ["DRAFT"],
        },
    )

    response = client.get("/api/v1/mails/day-stats?date=2026-05-26")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "date": "2026-05-26",
        "total_count": 2,
        "received_count": 1,
        "sent_count": 1,
    }


def test_google_gmail_received_at_clamps_future_internal_date(monkeypatch) -> None:
    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "jst_now",
        lambda: datetime(2026, 5, 26, 20, 0, 0, tzinfo=google_integration.JST),
    )

    assert google_integration.gmail_received_at(
        {"internalDate": "1779823819000"}
    ) == "2026-05-26T20:00:00+09:00"
