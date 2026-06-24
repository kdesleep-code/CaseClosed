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


def test_calendar_event_time_accepts_canonical_and_legacy_datetime_inputs() -> None:
    from caseclosed.google_integration import calendar_event_time

    assert calendar_event_time("2026-06-10T10:00:00+09:00", "Asia/Tokyo") == {
        "dateTime": "2026-06-10T10:00:00+09:00",
        "timeZone": "Asia/Tokyo",
    }
    assert calendar_event_time("2026-06-10T10:00", "Asia/Tokyo") == {
        "dateTime": "2026-06-10T10:00:00+09:00",
        "timeZone": "Asia/Tokyo",
    }
    assert calendar_event_time("2026-06-10T01:00:00+00:00", "Asia/Tokyo") == {
        "dateTime": "2026-06-10T10:00:00+09:00",
        "timeZone": "Asia/Tokyo",
    }


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
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.readonly "
        "https://www.googleapis.com/auth/calendar.events"
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


def test_google_gmail_connect_url_uses_frontend_origin_for_redirect_uri(
    client,
    database_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASECLOSED_GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("CASECLOSED_GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")

    response = client.post(
        "/api/v1/google/gmail/connect-url",
        json={"frontend_origin": "https://desktop-r043eh2.tail913207.ts.net:8443"},
    )

    assert response.status_code == 200
    parsed = urlparse(response.json()["data"]["authorization_url"])
    params = parse_qs(parsed.query)
    expected_redirect_uri = (
        "https://desktop-r043eh2.tail913207.ts.net:8443"
        "/api/v1/google/gmail/oauth/callback"
    )
    assert params["redirect_uri"] == [expected_redirect_uri]

    with sqlite3.connect(database_path) as connection:
        state_row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("google_gmail_oauth_state",),
        ).fetchone()

    assert state_row is not None
    state_data = json.loads(state_row[0])
    assert state_data["state"] == params["state"][0]
    assert state_data["redirect_uri"] == expected_redirect_uri


def test_google_calendar_status_reports_granted_scopes(client, database_path) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    response = client.get("/api/v1/google/gmail/calendar/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["connected"] is True
    assert data["calendar_read_enabled"] is True
    assert data["calendar_write_enabled"] is True
    assert data["calendar_auto_sync"]["enabled"] is True
    assert data["calendar_auto_sync"]["interval_minutes"] == 60


def test_google_calendar_auto_sync_settings_can_be_updated(client) -> None:
    response = client.patch(
        "/api/v1/google/gmail/calendar/auto-sync-settings",
        json={
            "enabled": True,
            "interval_minutes": 90,
            "calendar_ids": ["primary", "team@example.com", "primary"],
            "month_count": 4,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is True
    assert data["interval_minutes"] == 90
    assert data["calendar_ids"] == ["primary", "team@example.com"]
    assert data["month_count"] == 4


def test_google_calendar_auto_sync_once_records_sync_result(
    client,
    database_path,
    monkeypatch,
) -> None:
    client.get("/api/v1/google/gmail/status")
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.readonly",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_calendar_auto_sync_settings",
                "google_calendar_auto_sync_settings",
                json.dumps(
                    {
                        "enabled": True,
                        "interval_minutes": 60,
                        "calendar_ids": ["primary"],
                        "month_count": 1,
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration
    from caseclosed.db import runtime

    monkeypatch.setattr(
        google_integration,
        "jst_now",
        lambda: datetime(2026, 6, 14, 10, 0, 0, tzinfo=google_integration.JST),
    )

    def fake_calendar_api_get_json(path, access_token, params=None):
        assert path == "/calendars/primary/events"
        assert access_token == "test-access-token"
        assert params["timeMin"] == "2026-06-01T00:00:00+09:00"
        assert params["timeMax"] == "2026-07-01T00:00:00+09:00"
        return {
            "items": [
                {
                    "id": "auto_sync_event_1",
                    "etag": "etag-auto-1",
                    "status": "confirmed",
                    "summary": "Auto synced event",
                    "updated": "2026-06-14T09:30:00+09:00",
                    "start": {"dateTime": "2026-06-14T10:00:00+09:00"},
                    "end": {"dateTime": "2026-06-14T11:00:00+09:00"},
                }
            ]
        }

    monkeypatch.setattr(
        google_integration,
        "calendar_api_get_json",
        fake_calendar_api_get_json,
    )

    with runtime.SessionLocal() as session:
        result = google_integration.run_google_calendar_auto_sync_once(session)

    assert result["synced"] is True
    assert result["imported_count"] == 1
    with sqlite3.connect(database_path) as connection:
        settings_row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            ("google_calendar_auto_sync_settings",),
        ).fetchone()
        event_row = connection.execute(
            """
            SELECT summary, sync_status
            FROM calendar_events
            WHERE external_event_id = ?
            """,
            ("auto_sync_event_1",),
        ).fetchone()

    assert event_row == ("Auto synced event", "synced")
    settings = json.loads(settings_row[0])
    assert settings["last_success_at"] is not None
    assert settings["last_imported_count"] == 1
    assert settings["last_stop_reason"] == "synced"


def test_google_calendar_sync_inherits_links_for_recurring_instances(
    client,
    database_path,
    monkeypatch,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Recurring Case", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.readonly",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO calendar_events (
                id, source, external_calendar_id, external_event_id,
                summary, start_at, end_at, all_day, sync_status,
                attendance_requirement, created_at, updated_at, version
            )
            VALUES (
                'calendar_event_recurring_master', 'google', 'primary', 'weekly_master',
                'Weekly seminar', '2026-06-10T10:00:00+09:00',
                '2026-06-10T11:00:00+09:00', 0, 'synced', 'unknown',
                '2026-06-10T09:00:00+09:00', '2026-06-10T09:00:00+09:00', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO calendar_event_links (
                id, calendar_event_id, linked_type, linked_id, role,
                created_at, updated_at, version
            )
            VALUES (
                'calendar_event_link_recurring_case',
                'calendar_event_recurring_master',
                'case',
                ?,
                'related',
                '2026-06-10T09:00:00+09:00',
                '2026-06-10T09:00:00+09:00',
                1
            )
            """,
            (case_id,),
        )
        connection.commit()

    from caseclosed import google_integration

    def fake_calendar_api_get_json(path, access_token, params=None):
        assert access_token == "test-access-token"
        if path == "/calendars/primary":
            return {"id": "primary"}
        assert path == "/calendars/primary/events"
        return {
            "items": [
                {
                    "id": "weekly_master",
                    "etag": "etag-master",
                    "status": "confirmed",
                    "summary": "Weekly seminar",
                    "updated": "2026-06-10T09:00:00+09:00",
                    "start": {"dateTime": "2026-06-10T10:00:00+09:00"},
                    "end": {"dateTime": "2026-06-10T11:00:00+09:00"},
                },
                {
                    "id": "weekly_instance_20260617",
                    "etag": "etag-instance",
                    "status": "confirmed",
                    "summary": "Weekly seminar",
                    "updated": "2026-06-10T09:00:00+09:00",
                    "recurringEventId": "weekly_master",
                    "start": {"dateTime": "2026-06-17T10:00:00+09:00"},
                    "end": {"dateTime": "2026-06-17T11:00:00+09:00"},
                },
            ]
        }

    monkeypatch.setattr(
        google_integration,
        "calendar_api_get_json",
        fake_calendar_api_get_json,
    )

    response = client.post(
        "/api/v1/google/gmail/calendar/sync",
        json={"calendar_ids": ["primary"], "base_date": "2026-06-10", "month_count": 1},
    )

    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        child_row = connection.execute(
            """
            SELECT id, recurring_event_id
            FROM calendar_events
            WHERE external_event_id = 'weekly_instance_20260617'
            """
        ).fetchone()
        child_link_row = connection.execute(
            """
            SELECT linked_type, linked_id, role
            FROM calendar_event_links
            WHERE calendar_event_id = ?
            """,
            (child_row[0],),
        ).fetchone()

    assert child_row[1] == "weekly_master"
    assert child_link_row == ("case", case_id, "related")


def test_calendar_event_detail_inherits_links_for_existing_recurring_instance(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Existing Recurring Case", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO calendar_events (
                id, source, external_calendar_id, external_event_id,
                summary, start_at, end_at, all_day, sync_status,
                attendance_requirement, created_at, updated_at, version
            )
            VALUES (
                'calendar_event_existing_master', 'google', 'primary', 'existing_weekly_master',
                'Existing weekly', '2026-06-10T10:00:00+09:00',
                '2026-06-10T11:00:00+09:00', 0, 'missing_from_google', 'unknown',
                '2026-06-10T09:00:00+09:00', '2026-06-10T09:00:00+09:00', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO calendar_events (
                id, source, external_calendar_id, external_event_id,
                summary, start_at, end_at, all_day, sync_status,
                recurring_event_id, attendance_requirement, created_at, updated_at, version
            )
            VALUES (
                'calendar_event_existing_child', 'google', 'primary', 'existing_weekly_child',
                'Existing weekly', '2026-06-17T10:00:00+09:00',
                '2026-06-17T11:00:00+09:00', 0, 'synced',
                'existing_weekly_master', 'unknown',
                '2026-06-10T09:00:00+09:00', '2026-06-10T09:00:00+09:00', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO calendar_event_links (
                id, calendar_event_id, linked_type, linked_id, role,
                created_at, updated_at, version
            )
            VALUES (
                'calendar_event_link_existing_case',
                'calendar_event_existing_master',
                'case',
                ?,
                'related',
                '2026-06-10T09:00:00+09:00',
                '2026-06-10T09:00:00+09:00',
                1
            )
            """,
            (case_id,),
        )
        connection.commit()

    response = client.get("/api/v1/google/gmail/calendar/db-events/calendar_event_existing_child")

    assert response.status_code == 200
    links = response.json()["data"]["links"]
    assert [(link["linked_type"], link["linked_id"]) for link in links] == [("case", case_id)]


def test_calendar_db_events_deduplicates_primary_alias_rows(
    client,
    database_path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        for calendar_id, event_id in (
            ("horie@example.com", "calendar_event_real_primary"),
            ("primary", "calendar_event_primary_alias"),
        ):
            connection.execute(
                """
                INSERT INTO calendar_events (
                    id, source, external_calendar_id, external_event_id,
                    summary, start_at, end_at, all_day, sync_status,
                    attendance_requirement, created_at, updated_at, version
                )
                VALUES (?, 'google', ?, 'google_event_same', 'Shared event',
                        '2026-06-14T10:00:00+09:00',
                        '2026-06-14T11:00:00+09:00',
                        0, 'synced',
                        'unknown',
                        '2026-06-14T09:00:00+09:00',
                        '2026-06-14T09:00:00+09:00',
                        1)
                """,
                (event_id, calendar_id),
            )
        connection.commit()

    response = client.get(
        "/api/v1/google/gmail/calendar/db-events"
        "?calendar_id=horie%40example.com&calendar_id=primary"
        "&time_min=2026-06-14T00:00:00%2B09:00"
        "&time_max=2026-06-15T00:00:00%2B09:00"
    )

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == "calendar_event_real_primary"


def test_google_calendar_events_lists_primary_events(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.readonly",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration

    def fake_calendar_api_get_json(path, access_token, params=None):
        assert path == "/calendars/primary/events"
        assert access_token == "test-access-token"
        assert params["timeMin"] == "2026-06-10T00:00:00+09:00"
        return {
            "items": [
                {
                    "id": "event_1",
                    "summary": "Calendar check",
                    "htmlLink": "https://calendar.google.com/event?eid=event_1",
                    "start": {"dateTime": "2026-06-10T10:00:00+09:00"},
                    "end": {"dateTime": "2026-06-10T11:00:00+09:00"},
                }
            ]
        }

    monkeypatch.setattr(
        google_integration,
        "calendar_api_get_json",
        fake_calendar_api_get_json,
    )

    response = client.get(
        "/api/v1/google/gmail/calendar/events"
        "?time_min=2026-06-10T00:00:00%2B09:00"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"][0]["id"] == "event_1"
    assert data["items"][0]["summary"] == "Calendar check"


def test_google_calendar_create_event_posts_to_calendar(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration

    posted_payloads = []

    def fake_calendar_api_post_json(path, access_token, payload):
        assert path == "/calendars/primary/events"
        assert access_token == "test-access-token"
        posted_payloads.append(payload)
        return {
            "id": "created_event",
            "summary": payload["summary"],
            "htmlLink": "https://calendar.google.com/event?eid=created_event",
            "start": payload["start"],
            "end": payload["end"],
        }

    monkeypatch.setattr(
        google_integration,
        "calendar_api_post_json",
        fake_calendar_api_post_json,
    )

    response = client.post(
        "/api/v1/google/gmail/calendar/events",
        json={
            "summary": "Created from CaseClosed",
            "start": "2026-06-10T10:00:00+09:00",
            "end": "2026-06-10T11:00:00+09:00",
            "academic_series_id": "academic_series_test",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["event"]["id"] == "created_event"
    assert response.json()["data"]["db_event"]["academic_series_id"] == "academic_series_test"
    assert posted_payloads == [
        {
            "summary": "Created from CaseClosed",
            "start": {
                "dateTime": "2026-06-10T10:00:00+09:00",
                "timeZone": "Asia/Tokyo",
            },
            "end": {
                "dateTime": "2026-06-10T11:00:00+09:00",
                "timeZone": "Asia/Tokyo",
            },
        }
    ]
    with sqlite3.connect(database_path) as connection:
        event_row = connection.execute(
            """
            SELECT academic_series_id
            FROM calendar_events
            WHERE external_event_id = 'created_event'
            """
        ).fetchone()
        operation_row = connection.execute(
            """
            SELECT operation_type, status, external_service, external_id, attempt_count
            FROM external_operations
            WHERE operation_type = 'google_calendar_event_create'
            """
        ).fetchone()

    assert event_row == ("academic_series_test",)
    assert operation_row == (
        "google_calendar_event_create",
        "succeeded",
        "google_calendar",
        "created_event",
        1,
    )


def test_google_calendar_event_create_aligns_weekly_start_to_selected_weekday(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration

    posted_payloads = []

    def fake_calendar_api_post_json(path, access_token, payload):
        assert path == "/calendars/primary/events"
        assert access_token == "test-access-token"
        posted_payloads.append(payload)
        return {
            "id": "weekly_created_event",
            "summary": payload["summary"],
            "htmlLink": "https://calendar.google.com/event?eid=weekly_created_event",
            "start": payload["start"],
            "end": payload["end"],
            "recurrence": payload["recurrence"],
        }

    monkeypatch.setattr(
        google_integration,
        "calendar_api_post_json",
        fake_calendar_api_post_json,
    )

    response = client.post(
        "/api/v1/google/gmail/calendar/events",
        json={
            "summary": "Weekly Tuesday meeting",
            "start": "2026-06-15T10:00:00+09:00",
            "end": "2026-06-15T11:00:00+09:00",
            "recurrence_rule": "RRULE:FREQ=WEEKLY;BYDAY=TU",
        },
    )

    assert response.status_code == 200
    assert posted_payloads == [
        {
            "summary": "Weekly Tuesday meeting",
            "start": {
                "dateTime": "2026-06-16T10:00:00+09:00",
                "timeZone": "Asia/Tokyo",
            },
            "end": {
                "dateTime": "2026-06-16T11:00:00+09:00",
                "timeZone": "Asia/Tokyo",
            },
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TU"],
        }
    ]



def test_google_calendar_event_create_aligns_monthly_start_to_selected_day(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration

    posted_payloads = []

    def fake_calendar_api_post_json(path, access_token, payload):
        posted_payloads.append(payload)
        return {
            "id": "monthly_created_event",
            "summary": payload["summary"],
            "htmlLink": "https://calendar.google.com/event?eid=monthly_created_event",
            "start": payload["start"],
            "end": payload["end"],
            "recurrence": payload["recurrence"],
        }

    monkeypatch.setattr(google_integration, "calendar_api_post_json", fake_calendar_api_post_json)

    response = client.post(
        "/api/v1/google/gmail/calendar/events",
        json={
            "summary": "Monthly final day report",
            "start": "2026-06-15T10:00:00+09:00",
            "end": "2026-06-15T11:00:00+09:00",
            "recurrence_rule": "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1",
            "attendance_requirement": "not_required",
        },
    )

    assert response.status_code == 200
    assert posted_payloads[0]["start"]["dateTime"] == "2026-06-30T10:00:00+09:00"
    assert posted_payloads[0]["end"]["dateTime"] == "2026-06-30T11:00:00+09:00"
    assert response.json()["data"]["db_event"]["attendance_requirement"] == "not_required"


def test_google_calendar_event_create_aligns_yearly_start_to_selected_date(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    from caseclosed import google_integration

    posted_payloads = []

    def fake_calendar_api_post_json(path, access_token, payload):
        posted_payloads.append(payload)
        return {
            "id": "yearly_created_event",
            "summary": payload["summary"],
            "htmlLink": "https://calendar.google.com/event?eid=yearly_created_event",
            "start": payload["start"],
            "end": payload["end"],
            "recurrence": payload["recurrence"],
        }

    monkeypatch.setattr(google_integration, "calendar_api_post_json", fake_calendar_api_post_json)

    response = client.post(
        "/api/v1/google/gmail/calendar/events",
        json={
            "summary": "Yearly entrance task",
            "start": "2026-06-15T10:00:00+09:00",
            "end": "2026-06-15T11:00:00+09:00",
            "recurrence_rule": "RRULE:FREQ=YEARLY;BYMONTH=10;BYMONTHDAY=1",
        },
    )

    assert response.status_code == 200
    assert posted_payloads[0]["start"]["dateTime"] == "2026-10-01T10:00:00+09:00"
    assert posted_payloads[0]["end"]["dateTime"] == "2026-10-01T11:00:00+09:00"


def test_google_calendar_db_event_delete_deletes_google_event(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO calendar_events (
                id, source, external_calendar_id, external_event_id,
                summary, start_at, end_at, all_day, sync_status,
                attendance_requirement, created_at, updated_at, version
            )
            VALUES (
                'calendar_event_delete_me', 'google', 'primary', 'google_delete_me',
                'Delete me', '2026-06-10T10:00:00+09:00',
                '2026-06-10T11:00:00+09:00', 0, 'synced', 'unknown',
                '2026-06-10T09:00:00+09:00', '2026-06-10T09:00:00+09:00', 1
            )
            """
        )
        connection.commit()

    from caseclosed import google_integration

    deleted_paths = []

    def fake_calendar_api_delete(path, access_token):
        deleted_paths.append((path, access_token))

    monkeypatch.setattr(
        google_integration,
        "calendar_api_delete",
        fake_calendar_api_delete,
    )

    response = client.delete(
        "/api/v1/google/gmail/calendar/db-events/calendar_event_delete_me"
    )

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    assert deleted_paths == [
        ("/calendars/primary/events/google_delete_me", "test-access-token")
    ]
    with sqlite3.connect(database_path) as connection:
        event_row = connection.execute(
            """
            SELECT sync_status, google_status
            FROM calendar_events
            WHERE id = 'calendar_event_delete_me'
            """
        ).fetchone()
        operation_row = connection.execute(
            """
            SELECT operation_type, status, external_service, external_id
            FROM external_operations
            WHERE operation_type = 'google_calendar_event_delete'
            """
        ).fetchone()

    assert event_row == ("cancelled", "cancelled")
    assert operation_row == (
        "google_calendar_event_delete",
        "succeeded",
        "google_calendar",
        "google_delete_me",
    )


def test_google_calendar_db_event_delete_academic_series_deletes_all_events(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        for index, date in enumerate(["2026-10-07", "2026-10-14"], start=1):
            connection.execute(
                """
                INSERT INTO calendar_events (
                    id, source, external_calendar_id, external_event_id,
                    summary, start_at, end_at, all_day, sync_status,
                    academic_series_id, attendance_requirement,
                    created_at, updated_at, version
                )
                VALUES (?, 'google', 'primary', ?, 'Lecture',
                        ?, ?, 0, 'synced', 'academic_series_test', 'unknown',
                        '2026-06-10T09:00:00+09:00',
                        '2026-06-10T09:00:00+09:00', 1)
                """,
                (
                    f"calendar_event_academic_{index}",
                    f"academic_google_{index}",
                    f"{date}T15:15:00+09:00",
                    f"{date}T18:00:00+09:00",
                ),
            )
        connection.commit()

    from caseclosed import google_integration

    deleted_paths = []

    def fake_calendar_api_delete(path, access_token):
        deleted_paths.append((path, access_token))

    monkeypatch.setattr(
        google_integration,
        "calendar_api_delete",
        fake_calendar_api_delete,
    )

    response = client.delete(
        "/api/v1/google/gmail/calendar/db-events/calendar_event_academic_1?scope=series"
    )

    assert response.status_code == 200
    assert response.json()["data"]["deleted_count"] == 2
    assert response.json()["data"]["scope"] == "series"
    assert deleted_paths == [
        ("/calendars/primary/events/academic_google_1", "test-access-token"),
        ("/calendars/primary/events/academic_google_2", "test-access-token"),
    ]
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, sync_status, google_status
            FROM calendar_events
            WHERE academic_series_id = 'academic_series_test'
            ORDER BY id
            """
        ).fetchall()

    assert rows == [
        ("calendar_event_academic_1", "cancelled", "cancelled"),
        ("calendar_event_academic_2", "cancelled", "cancelled"),
    ]


def test_google_calendar_db_event_delete_recurring_series_deletes_master_once(
    client,
    database_path,
    monkeypatch,
) -> None:
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
                        "scopes": [
                            "https://www.googleapis.com/auth/calendar.events",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO calendar_events (
                id, source, external_calendar_id, external_event_id,
                summary, start_at, end_at, all_day, sync_status,
                attendance_requirement, created_at, updated_at, version
            )
            VALUES (
                'calendar_event_weekly_master', 'google', 'primary', 'weekly_master',
                'Weekly master', '2026-10-07T15:15:00+09:00',
                '2026-10-07T18:00:00+09:00', 0, 'synced', 'unknown',
                '2026-06-10T09:00:00+09:00', '2026-06-10T09:00:00+09:00', 1
            )
            """
        )
        for index, date in enumerate(["2026-10-14", "2026-10-21"], start=1):
            connection.execute(
                """
                INSERT INTO calendar_events (
                    id, source, external_calendar_id, external_event_id,
                    summary, start_at, end_at, all_day, recurring_event_id,
                    sync_status, attendance_requirement, created_at, updated_at, version
                )
                VALUES (?, 'google', 'primary', ?, 'Weekly child',
                        ?, ?, 0, 'weekly_master', 'synced', 'unknown',
                        '2026-06-10T09:00:00+09:00',
                        '2026-06-10T09:00:00+09:00', 1)
                """,
                (
                    f"calendar_event_weekly_child_{index}",
                    f"weekly_child_{index}",
                    f"{date}T15:15:00+09:00",
                    f"{date}T18:00:00+09:00",
                ),
            )
        connection.commit()

    from caseclosed import google_integration

    deleted_paths = []

    def fake_calendar_api_delete(path, access_token):
        deleted_paths.append((path, access_token))

    monkeypatch.setattr(
        google_integration,
        "calendar_api_delete",
        fake_calendar_api_delete,
    )

    response = client.delete(
        "/api/v1/google/gmail/calendar/db-events/calendar_event_weekly_child_1?scope=series"
    )

    assert response.status_code == 200
    assert response.json()["data"]["deleted_count"] == 3
    assert deleted_paths == [("/calendars/primary/events/weekly_master", "test-access-token")]
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, sync_status, google_status
            FROM calendar_events
            WHERE id LIKE 'calendar_event_weekly_%'
            ORDER BY id
            """
        ).fetchall()

    assert rows == [
        ("calendar_event_weekly_child_1", "cancelled", "cancelled"),
        ("calendar_event_weekly_child_2", "cancelled", "cancelled"),
        ("calendar_event_weekly_master", "cancelled", "cancelled"),
    ]


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


def test_google_gmail_auto_import_scans_past_loaded_message_until_previous_23(
    client,
    database_path,
    monkeypatch,
) -> None:
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_auto_latest_loaded",
            "gmail_thread_id": "thread_auto_latest_loaded",
            "from_address": "loaded.sender@example.com",
            "received_at": "2026-05-28T12:00:00+09:00",
            "subject": "Already loaded latest",
        },
    )
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_auto_older_loaded",
            "gmail_thread_id": "thread_auto_older_loaded",
            "from_address": "loaded.sender@example.com",
            "received_at": "2026-05-28T10:00:00+09:00",
            "subject": "Already loaded older",
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

    def gmail_message(message_id, thread_id, internal_date, subject):
        return {
            "id": message_id,
            "threadId": thread_id,
            "internalDate": internal_date,
            "labelIds": ["INBOX"],
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
            return {
                "messages": [
                    {"id": "gmail_auto_latest_loaded"},
                    {"id": "gmail_auto_gap"},
                    {"id": "gmail_auto_older_loaded"},
                ],
            }
        if path == "/users/me/messages/gmail_auto_latest_loaded":
            return gmail_message(
                "gmail_auto_latest_loaded",
                "thread_auto_latest_loaded",
                "1779951600000",
                "Already loaded latest",
            )
        if path == "/users/me/messages/gmail_auto_gap":
            return gmail_message(
                "gmail_auto_gap",
                "thread_auto_gap",
                "1779937200000",
                "Auto import gap",
            )
        if path == "/users/me/messages/gmail_auto_older_loaded":
            return gmail_message(
                "gmail_auto_older_loaded",
                "thread_auto_older_loaded",
                "1779904800000",
                "Already loaded older",
            )
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration
    from caseclosed.db import runtime

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )
    monkeypatch.setattr(
        google_integration,
        "jst_now",
        lambda: datetime(2026, 5, 28, 13, 0, tzinfo=runtime.JST),
    )

    with runtime.SessionLocal() as session:
        result = google_integration.run_google_gmail_auto_import_once(session)

    assert result["imported_count"] == 1
    with sqlite3.connect(database_path) as connection:
        imported = connection.execute(
            "SELECT subject FROM gmail_messages WHERE gmail_message_id = ?",
            ("gmail_auto_gap",),
        ).fetchone()
        settings = json.loads(
            connection.execute(
                "SELECT value_json FROM app_settings WHERE key = ?",
                ("google_gmail_auto_import_settings",),
            ).fetchone()[0]
        )

    assert imported == ("Auto import gap",)
    assert settings["last_imported_count"] == 1
    assert settings["last_error"] is None


def test_google_gmail_auto_import_skips_future_dated_loaded_message(
    client,
    database_path,
    monkeypatch,
) -> None:
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_auto_future_loaded",
            "gmail_thread_id": "thread_auto_future_loaded",
            "from_address": "loaded.sender@example.com",
            "received_at": "2026-05-28T12:00:00+09:00",
            "subject": "Future loaded",
        },
    )
    client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_auto_older_loaded",
            "gmail_thread_id": "thread_auto_older_loaded",
            "from_address": "loaded.sender@example.com",
            "received_at": "2026-05-28T10:00:00+09:00",
            "subject": "Already loaded older",
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

    def gmail_message(message_id, thread_id, internal_date, subject):
        return {
            "id": message_id,
            "threadId": thread_id,
            "internalDate": internal_date,
            "labelIds": ["INBOX"],
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
            return {
                "messages": [
                    {"id": "gmail_auto_future_loaded"},
                    {"id": "gmail_auto_gap"},
                    {"id": "gmail_auto_older_loaded"},
                ],
            }
        if path == "/users/me/messages/gmail_auto_future_loaded":
            return gmail_message(
                "gmail_auto_future_loaded",
                "thread_auto_future_loaded",
                "4102444800000",
                "Future loaded",
            )
        if path == "/users/me/messages/gmail_auto_gap":
            return gmail_message(
                "gmail_auto_gap",
                "thread_auto_gap",
                "1779937200000",
                "Auto import gap",
            )
        if path == "/users/me/messages/gmail_auto_older_loaded":
            return gmail_message(
                "gmail_auto_older_loaded",
                "thread_auto_older_loaded",
                "1779904800000",
                "Already loaded older",
            )
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration
    from caseclosed.db import runtime

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )
    monkeypatch.setattr(
        google_integration,
        "jst_now",
        lambda: datetime(2026, 5, 28, 12, 0, tzinfo=runtime.JST),
    )

    with runtime.SessionLocal() as session:
        result = google_integration.run_google_gmail_auto_import_once(session)

    assert result["imported_count"] == 1
    with sqlite3.connect(database_path) as connection:
        imported = connection.execute(
            "SELECT subject FROM gmail_messages WHERE gmail_message_id = ?",
            ("gmail_auto_gap",),
        ).fetchone()

    assert imported == ("Auto import gap",)


def test_google_gmail_auto_import_stops_after_three_day_lookback(
    client,
    database_path,
    monkeypatch,
) -> None:
    del client
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

    from caseclosed import google_integration
    from caseclosed.db import runtime

    def internal_date(year, month, day, hour):
        return str(
            int(
                datetime(year, month, day, hour, 0, tzinfo=runtime.JST).timestamp()
                * 1000
            )
        )

    def gmail_message(message_id, thread_id, internal_date_value, subject):
        return {
            "id": message_id,
            "threadId": thread_id,
            "internalDate": internal_date_value,
            "labelIds": ["INBOX"],
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

    requested_queries = []

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "test-access-token"
        if path == "/users/me/messages":
            requested_queries.append(params["q"])
            return {
                "messages": [
                    {"id": "gmail_auto_recent"},
                    {"id": "gmail_auto_too_old"},
                    {"id": "gmail_auto_not_reached"},
                ],
            }
        if path == "/users/me/messages/gmail_auto_recent":
            return gmail_message(
                "gmail_auto_recent",
                "thread_auto_recent",
                internal_date(2026, 5, 27, 12),
                "Recent auto import",
            )
        if path == "/users/me/messages/gmail_auto_too_old":
            return gmail_message(
                "gmail_auto_too_old",
                "thread_auto_too_old",
                internal_date(2026, 5, 24, 23),
                "Too old auto import",
            )
        if path == "/users/me/messages/gmail_auto_not_reached":
            raise AssertionError("auto import should stop before this message")
        raise AssertionError(f"unexpected Gmail API path: {path}")

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )
    monkeypatch.setattr(
        google_integration,
        "jst_now",
        lambda: datetime(2026, 5, 28, 12, 0, tzinfo=runtime.JST),
    )

    with runtime.SessionLocal() as session:
        result = google_integration.run_google_gmail_auto_import_once(session)

    assert result["imported_count"] == 1
    assert requested_queries == ["after:2026/05/24 -in:drafts"]
    with sqlite3.connect(database_path) as connection:
        imported_rows = connection.execute(
            """
            SELECT gmail_message_id, subject
            FROM gmail_messages
            WHERE gmail_message_id IN ('gmail_auto_recent', 'gmail_auto_too_old')
            ORDER BY gmail_message_id
            """
        ).fetchall()

    assert imported_rows == [("gmail_auto_recent", "Recent auto import")]


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
