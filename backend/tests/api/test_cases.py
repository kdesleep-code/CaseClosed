from __future__ import annotations

import sqlite3


def test_cases_can_be_listed_and_read(client) -> None:
    response = client.get("/api/v1/cases?status=waiting")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    system_case_keys = {item["system_case_key"] for item in items}
    assert "inbox" in system_case_keys
    assert "system_maintenance" not in system_case_keys
    assert all("mail_count" in item for item in items)
    assert all("genre_id" in item for item in items)
    assert all("next_task" in item for item in items)
    assert all("next_calendar_event" in item for item in items)

    inbox = next(item for item in items if item["system_case_key"] == "inbox")
    assert inbox["genre_id"] is None
    detail_response = client.get(f"/api/v1/cases/{inbox['id']}")

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["case"]["id"] == inbox["id"]
    assert detail["related_mails"] == []
    assert detail["tasks"] == []
    assert detail["files"] == []


def test_cases_can_be_filtered_by_work_state(client, database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO cases (
              id, name, progress_status, ball_status, closed_at, archived_at,
              is_system_case, system_case_key, created_at, updated_at, version
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, 1)
            """,
            [
                (
                    "case_user_ball",
                    "User ball",
                    "in_progress",
                    "user",
                    None,
                    None,
                    "2026-05-30T09:00:00+09:00",
                    "2026-05-30T09:00:00+09:00",
                ),
                (
                    "case_waiting",
                    "Waiting",
                    "waiting",
                    "other",
                    None,
                    None,
                    "2026-05-30T09:00:00+09:00",
                    "2026-05-30T09:00:00+09:00",
                ),
                (
                    "case_completed",
                    "Completed",
                    "completed",
                    "none",
                    "2026-05-30T10:00:00+09:00",
                    None,
                    "2026-05-30T09:00:00+09:00",
                    "2026-05-30T10:00:00+09:00",
                ),
            ],
        )

    user_ball_items = client.get("/api/v1/cases?status=user_ball").json()["data"][
        "items"
    ]
    waiting_items = client.get("/api/v1/cases?status=waiting").json()["data"]["items"]
    completed_items = client.get("/api/v1/cases?status=completed").json()["data"][
        "items"
    ]

    assert {item["id"] for item in user_ball_items} == {"case_user_ball"}
    assert "case_waiting" in {item["id"] for item in waiting_items}
    assert "case_system_inbox" in {item["id"] for item in waiting_items}
    assert {item["id"] for item in completed_items} == {"case_completed"}


def test_case_genres_can_be_managed(client, database_path) -> None:
    create_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "Research", "color_hex": "0x3af"},
    )

    assert create_response.status_code == 200
    genre = create_response.json()["data"]["genre"]
    assert genre["title"] == "Research"
    assert genre["color_hex"] == "#33aaff"

    update_response = client.patch(
        f"/api/v1/cases/genres/{genre['id']}",
        json={"title": "Committee", "color_hex": "#8844cc"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["genre"]["title"] == "Committee"

    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Genre Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
            "genre_id": genre["id"],
        },
    )
    assert case_response.status_code == 200
    assert case_response.json()["data"]["case"]["genre_id"] == genre["id"]

    list_response = client.get("/api/v1/cases/genres")
    assert list_response.status_code == 200
    assert "Committee" in [
        item["title"] for item in list_response.json()["data"]["items"]
    ]

    delete_response = client.delete(f"/api/v1/cases/genres/{genre['id']}")
    assert delete_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT genre_id FROM cases WHERE name = 'Genre Case'"
            ).fetchone()[0]
            is None
        )


def test_case_can_be_created_without_delete_api(client, app, database_path) -> None:
    response = client.post(
        "/api/v1/cases",
        json={
            "name": "Phase 7 Base Case",
            "description": "First user case.",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )

    assert response.status_code == 200
    created_case = response.json()["data"]["case"]
    assert created_case["name"] == "Phase 7 Base Case"
    assert created_case["is_system_case"] is False
    assert created_case["progress_status"] == "in_progress"

    detail_response = client.get(f"/api/v1/cases/{created_case['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["recent_events"][0]["event_type"] == "case_created"
    with sqlite3.connect(database_path) as connection:
        directory = connection.execute(
            """
            SELECT name, directory_kind, case_id, status
            FROM storage_directories
            WHERE case_id = ?
            """,
            (created_case["id"],),
        ).fetchone()
    assert directory == ("Phase 7 Base Case", "case", created_case["id"], "active")

    case_delete_routes = [
        route
        for route in app.routes
        if "DELETE" in getattr(route, "methods", set())
        and getattr(route, "path", "") == "/api/v1/cases/{case_id}"
    ]
    assert case_delete_routes == []


def test_case_overview_can_be_updated(client) -> None:
    response = client.post(
        "/api/v1/cases",
        json={
            "name": "Overview Case",
            "description": None,
            "progress_status": "not_started",
            "ball_status": "none",
        },
    )
    assert response.status_code == 200
    case_id = response.json()["data"]["case"]["id"]

    update_response = client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "description": "This case tracks the overview text.",
            "open_when_text": "Open this case every April.",
            "closed_when_text": "Close after the report is submitted.",
            "tags": ["Research", "Annual", "research"],
        },
    )

    assert update_response.status_code == 200
    updated_case = update_response.json()["data"]["case"]
    assert updated_case["description"] == "This case tracks the overview text."
    assert updated_case["open_when_text"] == "Open this case every April."
    assert updated_case["closed_when_text"] == "Close after the report is submitted."
    assert updated_case["tags"] == ["Research", "Annual"]
    assert updated_case["version"] == 2

    clear_response = client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "description": "   ",
            "open_when_text": " ",
            "closed_when_text": "",
            "tags": [],
        },
    )
    assert clear_response.status_code == 200
    cleared_case = clear_response.json()["data"]["case"]
    assert cleared_case["description"] is None
    assert cleared_case["open_when_text"] is None
    assert cleared_case["closed_when_text"] is None
    assert cleared_case["tags"] == []


def test_case_mail_links_can_be_listed(client, database_path) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Mail Link Case",
            "description": None,
            "progress_status": "not_started",
            "ball_status": "none",
        },
    )
    case_id = case_response.json()["data"]["case"]["id"]
    mail_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_case_mail_link",
            "gmail_thread_id": "thread_case_mail_link",
            "message_id_header": "<case-mail-link@example.com>",
            "subject": "Case mail link",
            "from_address": "case.mail@example.com",
            "received_at": "2026-05-31T11:00:00+09:00",
            "body_text": "This mail should be visible from the Case mail list.",
        },
    )
    message_id = mail_response.json()["data"]["message_id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO case_mail_links (
                id, case_id, message_id, created_at, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "case_mail_link_test",
                case_id,
                message_id,
                "2026-05-31T11:05:00+09:00",
                "2026-05-31T11:05:00+09:00",
                1,
            ),
        )

    list_response = client.get(f"/api/v1/cases/{case_id}/mail-links")
    detail_response = client.get(f"/api/v1/cases/{case_id}")

    assert list_response.status_code == 200
    item = list_response.json()["data"]["items"][0]
    assert item["message_id"] == message_id
    assert item["subject"] == "Case mail link"
    assert item["mail_url"] == f"/mail/{message_id}"
    assert detail_response.json()["data"]["case"]["mail_count"] == 1
    assert detail_response.json()["data"]["related_mails"][0]["message_id"] == message_id


def test_case_stakeholders_can_be_managed(client) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Stakeholder Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

    contacts = []
    for display_name, email in [
        ("Primary Collaborator", "primary@example.com"),
        ("Second Reviewer", "second@example.com"),
    ]:
        contact_response = client.post(
            "/api/v1/contacts",
            json={
                "display_name": display_name,
                "avatar_url": None,
                "user_memo": "",
                "ai_memo": None,
                "status": "active",
                "kind": "person",
                "sender_resolution_mode": "self",
                "tags": [],
                "email_addresses": [{"email_address": email, "is_primary": True}],
            },
        )
        assert contact_response.status_code == 200
        contacts.append(contact_response.json()["data"])

    missing_contact_response = client.post(
        f"/api/v1/cases/{case_id}/stakeholders",
        json={"contact_id": "contact_missing", "role": "stakeholder"},
    )
    assert missing_contact_response.status_code == 422

    first_response = client.post(
        f"/api/v1/cases/{case_id}/stakeholders",
        json={"contact_id": contacts[0]["id"], "role": "owner"},
    )
    assert first_response.status_code == 200
    first = first_response.json()["data"]["stakeholder"]
    assert first["contact_display_name"] == "Primary Collaborator"
    assert first["role"] == "owner"

    duplicate_response = client.post(
        f"/api/v1/cases/{case_id}/stakeholders",
        json={"contact_id": contacts[0]["id"], "role": "reviewer"},
    )
    assert duplicate_response.status_code == 409

    second_response = client.post(
        f"/api/v1/cases/{case_id}/stakeholders",
        json={"contact_id": contacts[1]["id"], "role": "reviewer"},
    )
    assert second_response.status_code == 200
    second = second_response.json()["data"]["stakeholder"]

    update_response = client.patch(
        f"/api/v1/cases/{case_id}/stakeholders/{first['id']}",
        json={"role": "collaborator"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["stakeholder"]["role"] == "collaborator"

    reorder_response = client.post(
        f"/api/v1/cases/{case_id}/stakeholders/reorder",
        json={"stakeholder_ids": [second["id"], first["id"]]},
    )
    assert reorder_response.status_code == 200
    assert [item["id"] for item in reorder_response.json()["data"]["items"]] == [
        second["id"],
        first["id"],
    ]

    detail_response = client.get(f"/api/v1/cases/{case_id}")
    assert detail_response.status_code == 200
    assert [item["id"] for item in detail_response.json()["data"]["stakeholders"]] == [
        second["id"],
        first["id"],
    ]

    delete_response = client.delete(
        f"/api/v1/cases/{case_id}/stakeholders/{second['id']}"
    )
    assert delete_response.status_code == 200
    list_response = client.get(f"/api/v1/cases/{case_id}/stakeholders")
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [first["id"]]


def test_case_tool_links_can_be_managed(client) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Tool Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

    first_response = client.post(
        f"/api/v1/cases/{case_id}/tool-links",
        json={"url": "https://github.com/example/repo"},
    )
    assert first_response.status_code == 200
    first = first_response.json()["data"]["tool_link"]
    assert first["url"] == "https://github.com/example/repo"
    assert first["icon_label"] == "GI"

    second_response = client.post(
        f"/api/v1/cases/{case_id}/tool-links",
        json={"url": "https://reports.example.com", "icon_label": "RP"},
    )
    assert second_response.status_code == 200
    second = second_response.json()["data"]["tool_link"]
    assert second["icon_label"] == "RP"

    reorder_response = client.post(
        f"/api/v1/cases/{case_id}/tool-links/reorder",
        json={"tool_link_ids": [second["id"], first["id"]]},
    )
    assert reorder_response.status_code == 200
    assert [item["id"] for item in reorder_response.json()["data"]["items"]] == [
        second["id"],
        first["id"],
    ]

    detail_response = client.get(f"/api/v1/cases/{case_id}")
    assert detail_response.status_code == 200
    assert [item["id"] for item in detail_response.json()["data"]["tool_links"]] == [
        second["id"],
        first["id"],
    ]

    delete_response = client.delete(
        f"/api/v1/cases/{case_id}/tool-links/{second['id']}"
    )
    assert delete_response.status_code == 200
    list_response = client.get(f"/api/v1/cases/{case_id}/tool-links")
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [first["id"]]
