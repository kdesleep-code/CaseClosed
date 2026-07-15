from __future__ import annotations

import base64
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


def test_case_name_update_renames_case_storage_directory(client, database_path) -> None:
    create_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Original Case Name",
            "description": "Original description.",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert create_response.status_code == 200
    case = create_response.json()["data"]["case"]

    update_response = client.patch(
        f"/api/v1/cases/{case['id']}",
        json={
            "name": "Renamed Case",
            "description": "Updated description.",
            "open_when_date": None,
            "open_when_text": None,
            "closed_when_text": None,
        },
    )

    assert update_response.status_code == 200
    updated_case = update_response.json()["data"]["case"]
    assert updated_case["name"] == "Renamed Case"
    assert updated_case["storage_directory_id"] == case["storage_directory_id"]

    with sqlite3.connect(database_path) as connection:
        directory_name = connection.execute(
            "SELECT name FROM storage_directories WHERE id = ?",
            (case["storage_directory_id"],),
        ).fetchone()[0]

    assert directory_name == "Renamed Case"


def test_case_current_situation_can_be_generated(client, database_path) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Context Case",
            "description": "This case is used to check generated current situation.",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]
    storage_directory_id = case_response.json()["data"]["case"]["storage_directory_id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO storage_objects (
              id, directory_id, location_id, scope, original_filename, content_type,
              byte_size, sha256_hex, storage_path, llm_input_allowed, source_type,
              source_message_id, status, created_at, updated_at, file_updated_at, version
            ) VALUES (?, ?, 'storage_location_internal', 'managed', ?, 'text/plain',
              128, ?, ?, 1, 'manual_upload', NULL, 'active', ?, ?, ?, 1)
            """,
            (
                "storage_object_case_context",
                storage_directory_id,
                "context-note.txt",
                "sha-context-current",
                "managed/test/context-note.txt",
                "2026-06-07T09:00:00+09:00",
                "2026-06-07T09:00:00+09:00",
                "2026-06-07T09:00:00+09:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO file_summaries (
              id, storage_object_id, storage_object_version_id, source_sha256_hex,
              source_filename, source_content_type, source_byte_size, summary_type,
              file_description, summary_points_json, llm_digest, structured_digest_json,
              coverage_json, token_estimate, llm_run_id, created_at, updated_at, version
            ) VALUES (?, ?, NULL, ?, ?, 'text/plain', 128, 'llm_digest',
              ?, ?, ?, '{}', '{}', 20, NULL, ?, ?, 1)
            """,
            (
                "file_summary_case_context",
                "storage_object_case_context",
                "sha-context-current",
                "context-note.txt",
                "Case context note file.",
                '["A related file summary is available."]',
                "Digest of the related case file.",
                "2026-06-07T09:01:00+09:00",
                "2026-06-07T09:01:00+09:00",
            ),
        )

    generate_response = client.post(f"/api/v1/cases/{case_id}/current-situation")

    assert generate_response.status_code == 200
    current_situation = generate_response.json()["data"]["current_situation"]
    assert current_situation["case_id"] == case_id
    assert current_situation["version_no"] == 1
    assert "Context Case" in current_situation["context_markdown"]
    assert "Task状況: 未接続" in current_situation["context_markdown"]
    assert "関連ファイルDigest: 1件" in current_situation["context_markdown"]

    detail_response = client.get(f"/api/v1/cases/{case_id}")
    assert detail_response.status_code == 200
    assert (
        detail_response.json()["data"]["current_situation"]["id"]
        == current_situation["id"]
    )

    with sqlite3.connect(database_path) as connection:
        context_row = connection.execute(
            """
            SELECT version_no, context_markdown, created_by
            FROM case_context_versions
            WHERE case_id = ?
            """,
            (case_id,),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT function_type, input_source_json, input_diagnostic_json, output_text_preview
            FROM llm_runs
            WHERE id = ?
            """,
            (current_situation["llm_run_id"],),
        ).fetchone()

    assert context_row == (
        1,
        current_situation["context_markdown"],
        "llm",
    )
    assert llm_run_row[0] == "case_current_situation_summary"
    assert "mail_thread_count" in llm_run_row[1]
    assert "This case is used to check" not in llm_run_row[1]
    assert '"file_count": 1' in llm_run_row[1]
    assert "Context Case" in llm_run_row[3]


def test_case_files_can_be_linked_and_unlinked_without_moving_source_file(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Linked Files", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "shared-note.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"shared file").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] is None

    link_response = client.post(
        f"/api/v1/cases/{case_id}/files/{storage_object['id']}/link"
    )
    assert link_response.status_code == 200

    case_files = client.get(f"/api/v1/cases/{case_id}/files").json()["data"]["items"]
    assert [item["id"] for item in case_files] == [storage_object["id"]]

    root_files = client.get("/api/v1/storage/objects").json()["data"]["items"]
    assert storage_object["id"] in [item["id"] for item in root_files]

    unlink_response = client.delete(
        f"/api/v1/cases/{case_id}/files/{storage_object['id']}/link"
    )
    assert unlink_response.status_code == 200

    assert client.get(f"/api/v1/cases/{case_id}/files").json()["data"]["items"] == []
    root_files_after_unlink = client.get("/api/v1/storage/objects").json()["data"]["items"]
    assert storage_object["id"] in [item["id"] for item in root_files_after_unlink]
    with sqlite3.connect(database_path) as connection:
        link_status = connection.execute(
            "SELECT status FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert link_status == "deleted"


def test_case_file_unlink_does_not_move_case_directory_file(client) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Case Upload", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case = case_response.json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "case-only.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"case file").decode("ascii"),
            "directory_id": case["storage_directory_id"],
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] == case["storage_directory_id"]

    case_files = client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"]
    assert [item["id"] for item in case_files] == [storage_object["id"]]

    unlink_response = client.delete(
        f"/api/v1/cases/{case['id']}/files/{storage_object['id']}/link"
    )
    assert unlink_response.status_code == 200
    assert unlink_response.json()["data"]["unlinked"] is False
    assert (
        unlink_response.json()["data"]["storage_object"]["directory_id"]
        == case["storage_directory_id"]
    )
    assert [
        item["id"]
        for item in client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"]
    ] == [storage_object["id"]]


def test_case_file_link_can_move_inside_case_without_moving_source_file(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Case Link Path", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case = case_response.json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "root-note.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"root file").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] is None

    directory = client.post(
        "/api/v1/storage/directories",
        json={"name": "linked-folder", "parent_id": case["storage_directory_id"]},
    ).json()["data"]["directory"]

    link_response = client.post(
        f"/api/v1/cases/{case['id']}/files/{storage_object['id']}/link",
        json={"directory_id": directory["id"]},
    )
    assert link_response.status_code == 200
    assert link_response.json()["data"]["storage_object"]["directory_id"] is None

    assert client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"] == []
    directory_objects = client.get(
        f"/api/v1/storage/objects?directory_id={directory['id']}"
    ).json()["data"]["items"]
    assert [item["id"] for item in directory_objects] == [storage_object["id"]]
    root_objects = client.get("/api/v1/storage/objects").json()["data"]["items"]
    assert storage_object["id"] in [item["id"] for item in root_objects]

    with sqlite3.connect(database_path) as connection:
        link_directory_id = connection.execute(
            "SELECT directory_id FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert link_directory_id == directory["id"]


def test_storage_move_into_linked_case_moves_body_to_existing_link_path(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Storage Link Move", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case = case_response.json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "root-report.pdf",
            "content_type": "application/pdf",
            "data_base64": base64.b64encode(b"pdf").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]

    directory = client.post(
        "/api/v1/storage/directories",
        json={"name": "reports", "parent_id": case["storage_directory_id"]},
    ).json()["data"]["directory"]

    link_response = client.post(
        f"/api/v1/cases/{case['id']}/files/{storage_object['id']}/link",
        json={"directory_id": directory["id"]},
    )
    assert link_response.status_code == 200

    move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": case["storage_directory_id"]},
    )
    assert move_response.status_code == 200
    assert move_response.json()["data"]["storage_object"]["directory_id"] == directory["id"]

    assert client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"] == []
    directory_objects = client.get(
        f"/api/v1/storage/objects?directory_id={directory['id']}"
    ).json()["data"]["items"]
    assert [item["id"] for item in directory_objects] == [storage_object["id"]]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT directory_id, status FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()
    assert row == (directory["id"], "deleted")


def test_moving_case_body_to_storage_root_leaves_no_case_link(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Root Body Rule", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case = case_response.json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "case-body.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"case body").decode("ascii"),
            "directory_id": case["storage_directory_id"],
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] == case["storage_directory_id"]

    move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": None},
    )
    assert move_response.status_code == 200
    assert move_response.json()["data"]["storage_object"]["directory_id"] is None

    root_objects = client.get("/api/v1/storage/objects").json()["data"]["items"]
    root_item = next(item for item in root_objects if item["id"] == storage_object["id"])
    assert root_item["display_source"] == "physical"

    case_files = client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"]
    assert case_files == []

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT directory_id, status FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()
    assert row is None


def test_moving_case_body_to_another_case_leaves_no_old_case_link(
    client,
    database_path,
) -> None:
    case_a = client.post(
        "/api/v1/cases",
        json={"name": "Source Case", "progress_status": "in_progress", "ball_status": "user"},
    ).json()["data"]["case"]
    case_b = client.post(
        "/api/v1/cases",
        json={"name": "Target Case", "progress_status": "in_progress", "ball_status": "user"},
    ).json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "case-to-case.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"case to case").decode("ascii"),
            "directory_id": case_a["storage_directory_id"],
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]

    move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": case_b["storage_directory_id"]},
    )
    assert move_response.status_code == 200
    assert (
        move_response.json()["data"]["storage_object"]["directory_id"]
        == case_b["storage_directory_id"]
    )

    assert client.get(f"/api/v1/cases/{case_a['id']}/files").json()["data"]["items"] == []
    case_b_files = client.get(f"/api/v1/cases/{case_b['id']}/files").json()["data"]["items"]
    assert [item["id"] for item in case_b_files] == [storage_object["id"]]
    assert case_b_files[0]["display_source"] == "physical"

    with sqlite3.connect(database_path) as connection:
        link_count = connection.execute(
            "SELECT count(*) FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert link_count == 0


def test_case_file_move_into_case_with_root_link_moves_body_to_root_and_deletes_link(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={"name": "Case Subdir", "progress_status": "in_progress", "ball_status": "user"},
    )
    assert case_response.status_code == 200
    case = case_response.json()["data"]["case"]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "shared-movie.mp4",
            "content_type": "video/mp4",
            "data_base64": base64.b64encode(b"movie").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]

    link_response = client.post(
        f"/api/v1/cases/{case['id']}/files/{storage_object['id']}/link"
    )
    assert link_response.status_code == 200
    assert [
        item["id"] for item in client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"]
    ] == [storage_object["id"]]

    directory = client.post(
        "/api/v1/storage/directories",
        json={"name": "videos", "parent_id": case["storage_directory_id"]},
    ).json()["data"]["directory"]

    move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": directory["id"]},
    )
    assert move_response.status_code == 200
    assert (
        move_response.json()["data"]["storage_object"]["directory_id"]
        == case["storage_directory_id"]
    )

    assert [
        item["id"]
        for item in client.get(f"/api/v1/cases/{case['id']}/files").json()["data"]["items"]
    ] == [storage_object["id"]]
    directory_objects = client.get(
        f"/api/v1/storage/objects?directory_id={directory['id']}"
    ).json()["data"]["items"]
    assert directory_objects == []

    with sqlite3.connect(database_path) as connection:
        link_status, link_directory_id = connection.execute(
            "SELECT status, directory_id FROM file_links WHERE storage_object_id = ?",
            (storage_object["id"],),
        ).fetchone()
    assert link_status == "deleted"
    assert link_directory_id == case["storage_directory_id"]


def test_user_case_can_be_deleted_without_deleting_storage_directory(
    client,
    database_path,
) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Temporary Case",
            "description": None,
            "progress_status": "not_started",
            "ball_status": "none",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]
    storage_directory_id = case_response.json()["data"]["case"]["storage_directory_id"]

    delete_response = client.delete(f"/api/v1/cases/{case_id}")

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted"] is True
    assert client.get(f"/api/v1/cases/{case_id}").status_code == 404
    with sqlite3.connect(database_path) as connection:
        directory_row = connection.execute(
            """
            SELECT directory_kind, case_id, status
            FROM storage_directories
            WHERE id = ?
            """,
            (storage_directory_id,),
        ).fetchone()
    assert directory_row == ("normal", None, "active")


def test_system_case_cannot_be_deleted(client) -> None:
    list_response = client.get("/api/v1/cases?status=waiting")
    inbox = next(
        item
        for item in list_response.json()["data"]["items"]
        if item["system_case_key"] == "inbox"
    )

    delete_response = client.delete(f"/api/v1/cases/{inbox['id']}")

    assert delete_response.status_code == 409
    assert delete_response.json()["error"]["code"] == "SYSTEM_CASE_PROTECTED"


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
        connection.execute(
            """
            INSERT INTO tasks (
              id, case_id, storage_directory_id, parent_task_id, title, description,
              done_when_text, status, priority, due_at, estimate_minutes,
              scheduled_minutes, worked_minutes, source_type, source_id,
              completed_at, canceled_at, canceled_reason, deleted_at, deleted_reason,
              created_at, updated_at, version
            )
            VALUES (
              'task_user_ball', 'case_user_ball', NULL, NULL, 'Open task', NULL,
              NULL, 'not_started', 'middle', NULL, NULL,
              0, 0, 'manual', NULL,
              NULL, NULL, NULL, NULL, NULL,
              '2026-05-30T09:00:00+09:00', '2026-05-30T09:00:00+09:00', 1
            )
            """
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


def test_future_start_task_does_not_put_case_in_user_ball(client, database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO cases (
              id, name, progress_status, ball_status, closed_at, archived_at,
              is_system_case, system_case_key, created_at, updated_at, version
            )
            VALUES (?, ?, 'not_started', 'none', NULL, NULL, 0, NULL, ?, ?, 1)
            """,
            [
                (
                    "case_future_task",
                    "Future Task Case",
                    "2026-05-30T09:00:00+09:00",
                    "2026-05-30T09:00:00+09:00",
                ),
                (
                    "case_actionable_task",
                    "Actionable Task Case",
                    "2026-05-30T09:00:00+09:00",
                    "2026-05-30T09:00:00+09:00",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO tasks (
              id, case_id, storage_directory_id, parent_task_id, title, description,
              done_when_text, status, priority, start_at, due_at, estimate_minutes,
              scheduled_minutes, worked_minutes, source_type, source_id,
              completed_at, canceled_at, canceled_reason, deleted_at, deleted_reason,
              created_at, updated_at, version
            )
            VALUES (?, ?, NULL, NULL, ?, NULL,
              NULL, 'not_started', 'middle', ?, NULL, NULL,
              0, 0, 'manual', NULL,
              NULL, NULL, NULL, NULL, NULL,
              '2026-05-30T09:00:00+09:00', '2026-05-30T09:00:00+09:00', 1
            )
            """,
            [
                (
                    "task_future_start",
                    "case_future_task",
                    "Future start task",
                    "2099-01-01",
                ),
                (
                    "task_actionable_start",
                    "case_actionable_task",
                    "Actionable task",
                    "2000-01-01",
                ),
            ],
        )

    user_ball_ids = {
        item["id"]
        for item in client.get("/api/v1/cases?status=user_ball").json()["data"][
            "items"
        ]
    }
    waiting_ids = {
        item["id"]
        for item in client.get("/api/v1/cases?status=waiting").json()["data"][
            "items"
        ]
    }

    assert "case_future_task" not in user_ball_ids
    assert "case_future_task" in waiting_ids
    assert "case_actionable_task" in user_ball_ids


def test_low_and_skip_case_mail_do_not_put_case_in_user_ball(client, database_path) -> None:
    created_cases: dict[str, str] = {}
    for importance in ["low", "skip", "high"]:
        response = client.post(
            "/api/v1/cases",
            json={
                "name": f"Case mail {importance}",
                "description": None,
                "progress_status": "waiting",
                "ball_status": "none",
            },
        )
        assert response.status_code == 200
        created_cases[importance] = response.json()["data"]["case"]["id"]

    message_ids: dict[str, str] = {}
    for importance in ["low", "skip", "high"]:
        response = client.post(
            "/api/v1/mails/mock-ingest",
            json={
                "gmail_message_id": f"gmail_case_mail_{importance}",
                "gmail_thread_id": f"thread_case_mail_{importance}",
                "message_id_header": f"<case-mail-{importance}@example.com>",
                "subject": f"Case mail {importance}",
                "from_address": f"case.mail.{importance}@example.com",
                "received_at": "2026-05-31T11:00:00+09:00",
                "body_text": f"This {importance} mail is linked to a Case.",
            },
        )
        assert response.status_code == 200
        message_ids[importance] = response.json()["data"]["message_id"]

    with sqlite3.connect(database_path) as connection:
        for importance, message_id in message_ids.items():
            connection.execute(
                """
                UPDATE mail_auto_state
                SET suggested_importance = ?, effective_importance = ?
                WHERE message_id = ?
                """,
                (importance, importance, message_id),
            )
            connection.execute(
                """
                UPDATE mail_user_state
                SET processed_status = 'unprocessed', user_importance = NULL
                WHERE message_id = ?
                """,
                (message_id,),
            )
            connection.execute(
                """
                INSERT INTO case_mail_links (
                    id, case_id, message_id, created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    f"case_mail_link_{importance}",
                    created_cases[importance],
                    message_id,
                    "2026-05-31T11:05:00+09:00",
                    "2026-05-31T11:05:00+09:00",
                ),
            )
        connection.commit()

    user_ball_ids = {
        item["id"]
        for item in client.get("/api/v1/cases?status=user_ball").json()["data"][
            "items"
        ]
    }
    waiting_ids = {
        item["id"]
        for item in client.get("/api/v1/cases?status=waiting").json()["data"]["items"]
    }

    assert created_cases["high"] in user_ball_ids
    assert created_cases["low"] not in user_ball_ids
    assert created_cases["skip"] not in user_ball_ids
    assert created_cases["low"] in waiting_ids
    assert created_cases["skip"] in waiting_ids


def test_case_can_be_completed_reopened_and_archived(client, database_path) -> None:
    genre_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "State Genre", "color_hex": "#4477aa"},
    )
    assert genre_response.status_code == 200
    genre_id = genre_response.json()["data"]["genre"]["id"]
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "State Case",
            "description": None,
            "progress_status": "waiting",
            "ball_status": "other",
            "genre_id": genre_id,
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]
    storage_directory_id = case_response.json()["data"]["case"]["storage_directory_id"]

    complete_response = client.post(f"/api/v1/cases/{case_id}/complete")

    assert complete_response.status_code == 200
    completed_case = complete_response.json()["data"]["case"]
    assert completed_case["closed_at"] is not None
    assert completed_case["archived_at"] is None
    assert completed_case["progress_status"] == "completed"
    assert completed_case["ball_status"] == "none"
    assert case_id in {
        item["id"]
        for item in client.get("/api/v1/cases?status=completed").json()["data"][
            "items"
        ]
    }

    reopen_response = client.post(f"/api/v1/cases/{case_id}/reopen")

    assert reopen_response.status_code == 200
    reopened_case = reopen_response.json()["data"]["case"]
    assert reopened_case["closed_at"] is None
    assert reopened_case["archived_at"] is None
    assert reopened_case["progress_status"] == "waiting"
    assert reopened_case["ball_status"] == "none"
    assert case_id in {
        item["id"] for item in client.get("/api/v1/cases?status=waiting").json()["data"]["items"]
    }

    archive_response = client.post(f"/api/v1/cases/{case_id}/archive")

    assert archive_response.status_code == 200
    archived_case = archive_response.json()["data"]["case"]
    assert archived_case["closed_at"] is None
    assert archived_case["archived_at"] is not None
    with sqlite3.connect(database_path) as connection:
        archived_parent = connection.execute(
            """
            SELECT parent.name, parent.parent_id
            FROM storage_directories AS case_directory
            JOIN storage_directories AS parent ON parent.id = case_directory.parent_id
            WHERE case_directory.id = ?
            """,
            (storage_directory_id,),
        ).fetchone()
        genre_directory_id = connection.execute(
            "SELECT id FROM storage_directories WHERE name = 'State Genre' AND parent_id IS NULL"
        ).fetchone()[0]
    assert archived_parent == ("Archived Cases", genre_directory_id)
    assert case_id in {
        item["id"]
        for item in client.get("/api/v1/cases?status=archived").json()["data"][
            "items"
        ]
    }
    detail_response = client.get(f"/api/v1/cases/{case_id}")
    assert [
        event["event_type"]
        for event in detail_response.json()["data"]["recent_events"][:3]
    ] == ["case_archived", "case_reopened", "case_closed"]
    closed_event = detail_response.json()["data"]["recent_events"][2]
    assert closed_event["metadata"] == {
        "previous_progress_status": "waiting",
        "previous_ball_status": "none",
    }

    reopened_again_response = client.post(f"/api/v1/cases/{case_id}/reopen")
    assert reopened_again_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        reopened_parent = connection.execute(
            """
            SELECT parent.name, parent.parent_id
            FROM storage_directories AS case_directory
            JOIN storage_directories AS parent ON parent.id = case_directory.parent_id
            WHERE case_directory.id = ?
            """,
            (storage_directory_id,),
        ).fetchone()
    assert reopened_parent == ("State Genre", None)


def test_system_case_cannot_be_completed_or_archived(client) -> None:
    list_response = client.get("/api/v1/cases?status=waiting")
    inbox = next(
        item
        for item in list_response.json()["data"]["items"]
        if item["system_case_key"] == "inbox"
    )

    complete_response = client.post(f"/api/v1/cases/{inbox['id']}/complete")
    archive_response = client.post(f"/api/v1/cases/{inbox['id']}/archive")

    assert complete_response.status_code == 409
    assert complete_response.json()["error"]["code"] == "SYSTEM_CASE_PROTECTED"
    assert archive_response.status_code == 409
    assert archive_response.json()["error"]["code"] == "SYSTEM_CASE_PROTECTED"


def test_case_genres_can_be_managed(client, database_path) -> None:
    create_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "Research", "color_hex": "0x3af"},
    )

    assert create_response.status_code == 200
    genre = create_response.json()["data"]["genre"]
    assert genre["title"] == "Research"
    assert genre["color_hex"] == "#33aaff"
    assert genre["sort_order"] == 0

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
    created_case = case_response.json()["data"]["case"]
    assert created_case["genre_id"] == genre["id"]
    with sqlite3.connect(database_path) as connection:
        case_parent_name = connection.execute(
            """
            SELECT parent.name
            FROM storage_directories AS case_directory
            JOIN storage_directories AS parent ON parent.id = case_directory.parent_id
            WHERE case_directory.id = ?
            """,
            (created_case["storage_directory_id"],),
        ).fetchone()[0]
    assert case_parent_name == "Committee"

    list_response = client.get("/api/v1/cases/genres")
    assert list_response.status_code == 200
    assert "Committee" in [
        item["title"] for item in list_response.json()["data"]["items"]
    ]

    second_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "Research", "color_hex": "#33aa66"},
    )
    assert second_response.status_code == 200
    second_genre = second_response.json()["data"]["genre"]
    reorder_response = client.patch(
        "/api/v1/cases/genres/reorder",
        json={"genre_ids": [second_genre["id"], genre["id"]]},
    )
    assert reorder_response.status_code == 200
    reordered_titles = [
        item["title"] for item in reorder_response.json()["data"]["items"]
    ]
    assert reordered_titles[:2] == ["Research", "Committee"]

    delete_response = client.delete(f"/api/v1/cases/genres/{genre['id']}")
    assert delete_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT genre_id FROM cases WHERE name = 'Genre Case'"
            ).fetchone()[0]
            is None
        )
        moved_parent_name = connection.execute(
            """
            SELECT parent.name
            FROM storage_directories AS case_directory
            JOIN storage_directories AS parent ON parent.id = case_directory.parent_id
            WHERE case_directory.id = ?
            """,
            (created_case["storage_directory_id"],),
        ).fetchone()[0]
        deleted_genre_statuses = connection.execute(
            """
            SELECT status
            FROM storage_directories
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (
                f"storage_directory_case_genre_{genre['id']}",
                f"storage_directory_case_genre_{genre['id']}_archived_cases",
            ),
        ).fetchall()
    assert moved_parent_name == "No genre"
    assert [row[0] for row in deleted_genre_statuses] == ["archived", "archived"]


def test_case_can_be_created_with_case_storage_directory(client, database_path) -> None:
    genre_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "Research", "color_hex": "#33aaff"},
    )
    assert genre_response.status_code == 200
    genre = genre_response.json()["data"]["genre"]
    response = client.post(
        "/api/v1/cases",
        json={
            "name": "Phase 7 Base Case",
            "description": "First user case.",
            "open_when_date": "2026-05-30",
            "closed_when_text": "Close when all linked tasks are done.",
            "progress_status": "in_progress",
            "ball_status": "user",
            "genre_id": genre["id"],
            "tags": ["Research", "Annual", "research"],
        },
    )

    assert response.status_code == 200
    created_case = response.json()["data"]["case"]
    assert created_case["name"] == "Phase 7 Base Case"
    assert created_case["is_system_case"] is False
    assert created_case["progress_status"] == "in_progress"
    assert created_case["open_when_date"] == "2026-05-30"
    assert created_case["open_when_text"] is None
    assert created_case["closed_when_text"] == "Close when all linked tasks are done."
    assert created_case["tags"] == ["Research", "Annual"]

    detail_response = client.get(f"/api/v1/cases/{created_case['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["recent_events"][0]["event_type"] == "case_created"
    with sqlite3.connect(database_path) as connection:
        directory = connection.execute(
            """
            SELECT case_directory.name, case_directory.directory_kind, case_directory.case_id,
                   case_directory.status, genre_directory.name, genre_directory.parent_id
            FROM storage_directories AS case_directory
            JOIN storage_directories AS genre_directory ON genre_directory.id = case_directory.parent_id
            WHERE case_directory.id = ?
            """,
            (created_case["storage_directory_id"],),
        ).fetchone()
        archived_directory = connection.execute(
            """
            SELECT archived.name, archived.parent_id, archived.case_id, archived.status
            FROM storage_directories AS archived
            JOIN storage_directories AS genre_directory ON genre_directory.id = archived.parent_id
            WHERE genre_directory.name = 'Research' AND archived.name = 'Archived Cases'
            """
        ).fetchone()
    assert directory == ("Phase 7 Base Case", "case", created_case["id"], "active", "Research", None)
    assert archived_directory[0] == "Archived Cases"
    assert archived_directory[2:] == (None, "active")


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
            "open_when_date": "2026-04-01",
            "closed_when_text": "Close after the report is submitted.",
            "tags": ["Research", "Annual", "research"],
        },
    )

    assert update_response.status_code == 200
    updated_case = update_response.json()["data"]["case"]
    assert updated_case["description"] == "This case tracks the overview text."
    assert updated_case["open_when_date"] == "2026-04-01"
    assert updated_case["open_when_text"] is None
    assert updated_case["closed_when_text"] == "Close after the report is submitted."
    assert updated_case["tags"] == ["Research", "Annual"]
    assert updated_case["version"] == 2

    clear_response = client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "description": "   ",
            "open_when_date": None,
            "open_when_text": None,
            "closed_when_text": "",
            "tags": [],
        },
    )
    assert clear_response.status_code == 200
    cleared_case = clear_response.json()["data"]["case"]
    assert cleared_case["description"] is None
    assert cleared_case["open_when_date"] is None
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
    followup_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_case_mail_link_followup",
            "gmail_thread_id": "thread_case_mail_link",
            "message_id_header": "<case-mail-link-followup@example.com>",
            "subject": "Re: Case mail link",
            "from_address": "case.mail@example.com",
            "received_at": "2026-05-31T12:00:00+09:00",
            "body_text": "This follow-up is the latest message in the linked thread.",
        },
    )
    followup_message_id = followup_response.json()["data"]["message_id"]
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO case_mail_links (
                id, case_id, message_id, created_at, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "case_mail_link_test",
                    case_id,
                    message_id,
                    "2026-05-31T11:05:00+09:00",
                    "2026-05-31T11:05:00+09:00",
                    1,
                ),
                (
                    "case_mail_link_test_followup",
                    case_id,
                    followup_message_id,
                    "2026-05-31T12:05:00+09:00",
                    "2026-05-31T12:05:00+09:00",
                    1,
                ),
            ],
        )

    list_response = client.get(f"/api/v1/cases/{case_id}/mail-links")
    detail_response = client.get(f"/api/v1/cases/{case_id}")

    assert list_response.status_code == 200
    items = list_response.json()["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["message_id"] == followup_message_id
    assert item["subject"] == "Re: Case mail link"
    assert item["mail_url"] == f"/mail/{followup_message_id}"
    assert detail_response.json()["data"]["case"]["mail_count"] == 1
    assert detail_response.json()["data"]["related_mails"][0]["message_id"] == (
        followup_message_id
    )


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
    for display_name, email, avatar_url in [
        ("Primary Collaborator", "primary@example.com", "/storage/contact-images/primary.webp"),
        ("Second Reviewer", "second@example.com", None),
    ]:
        contact_response = client.post(
            "/api/v1/contacts",
            json={
                "display_name": display_name,
                "avatar_url": avatar_url,
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
    assert first["contact_avatar_url"] == "/storage/contact-images/primary.webp"
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
        json={"role": "external advisor"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["stakeholder"]["role"] == "external advisor"

    clear_role_response = client.patch(
        f"/api/v1/cases/{case_id}/stakeholders/{first['id']}",
        json={"role": ""},
    )
    assert clear_role_response.status_code == 200
    assert clear_role_response.json()["data"]["stakeholder"]["role"] == ""

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


def test_case_tool_icon_settings_match_tool_links_by_longest_url(
    client,
    database_path,
) -> None:
    svg_base64 = (
        "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
    )
    broad_response = client.post(
        "/api/v1/cases/tool-icons",
        json={
            "icon_filename": "github.svg",
            "icon_content_type": "image/svg+xml",
            "icon_data_base64": svg_base64,
            "match_url": "github.com",
        },
    )
    assert broad_response.status_code == 200
    broad = broad_response.json()["data"]["tool_icon"]

    narrow_response = client.post(
        "/api/v1/cases/tool-icons",
        json={
            "icon_filename": "repo.svg",
            "icon_content_type": "image/svg+xml",
            "icon_data_base64": svg_base64,
            "match_url": "github.com/example/repo",
        },
    )
    assert narrow_response.status_code == 200
    narrow = narrow_response.json()["data"]["tool_icon"]

    with sqlite3.connect(database_path) as connection:
        icon_row = connection.execute(
            "SELECT scope, storage_path FROM storage_objects WHERE id = ?",
            (narrow["storage_object_id"],),
        ).fetchone()
    assert icon_row == (
        "case-tool-icons",
        f"case-tool-icons/{narrow['storage_object_id'][15:17]}/{narrow['storage_object_id']}.svg",
    )

    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Tool Icon Case",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    case_id = case_response.json()["data"]["case"]["id"]
    link_response = client.post(
        f"/api/v1/cases/{case_id}/tool-links",
        json={"url": "https://github.com/example/repo/issues"},
    )
    assert link_response.status_code == 200
    tool_link = link_response.json()["data"]["tool_link"]
    assert tool_link["icon_setting_id"] == narrow["id"]
    assert tool_link["icon_url"] == narrow["icon_url"]

    listed_response = client.get(f"/api/v1/cases/{case_id}/tool-links")
    assert listed_response.status_code == 200
    assert listed_response.json()["data"]["items"][0]["icon_setting_id"] == narrow["id"]

    update_response = client.patch(
        f"/api/v1/cases/tool-icons/{narrow['id']}",
        json={"match_url": "github.com/example/repo/issues"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["tool_icon"]["match_url"] == (
        "github.com/example/repo/issues"
    )

    delete_response = client.delete(f"/api/v1/cases/tool-icons/{narrow['id']}")
    assert delete_response.status_code == 200
    assert client.get(narrow["icon_url"]).status_code == 404

    fallback_link = client.get(f"/api/v1/cases/{case_id}/tool-links").json()["data"]["items"][0]
    assert fallback_link["icon_setting_id"] == broad["id"]
    assert fallback_link["icon_url"] == broad["icon_url"]


def test_deleting_case_deletes_related_tasks(client, database_path) -> None:
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Task Delete Case",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]

    task_response = client.post(
        "/api/v1/tasks",
        json={"case_id": case_id, "title": "Task tied to deleted Case"},
    )
    assert task_response.status_code == 200
    task = task_response.json()["data"]["task"]

    delete_response = client.delete(f"/api/v1/cases/{case_id}")
    assert delete_response.status_code == 200

    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    deleted_task_response = client.get(f"/api/v1/tasks/{task['id']}?include_deleted=1")
    assert deleted_task_response.status_code == 200
    deleted_task = deleted_task_response.json()["data"]["task"]
    assert deleted_task["deleted_at"] is not None
    assert deleted_task["deleted_reason"] == "case_deleted"

    with sqlite3.connect(database_path) as connection:
        directory_status = connection.execute(
            "SELECT status FROM storage_directories WHERE id = ?",
            (task["storage_directory_id"],),
        ).fetchone()[0]
    assert directory_status == "deleted"
