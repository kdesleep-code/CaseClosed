from __future__ import annotations

import sqlite3
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path


def create_case(client, name: str = "Task Case") -> dict[str, object]:
    response = client.post(
        "/api/v1/cases",
        json={"name": name, "progress_status": "in_progress", "ball_status": "user"},
    )
    assert response.status_code == 200
    return response.json()["data"]["case"]


def jst_today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def ingest_task_source_mail(client, *, subject: str = "Task source mail") -> str:
    response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_task_source_1",
            "gmail_thread_id": "thread_task_source",
            "message_id_header": "<gmail-task-source-1@example.com>",
            "subject": subject,
            "from_address": "task.sender@example.com",
            "to_addresses": ["user@example.com"],
            "received_at": "2026-06-09T09:00:00+09:00",
            "body_text": "Please prepare the review response by next Friday.",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["message_id"]


def test_task_can_be_created_listed_updated_and_restored(
    client,
    database_path: Path,
) -> None:
    case = create_case(client)

    create_response = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Prepare review notes",
            "description": "Read the manuscript and write notes.",
            "done_when_text": "Review notes are ready to submit.",
            "progress_memo": "Initial memo.",
            "priority": "high",
            "due_at": "2026-06-10T12:00:00+09:00",
            "estimate_minutes": 45,
            "source_type": "manual",
        },
    )
    assert create_response.status_code == 200
    task = create_response.json()["data"]["task"]
    assert task["case_id"] == case["id"]
    assert task["storage_directory_id"] is not None
    assert task["done_when_text"] == "Review notes are ready to submit."
    assert task["progress_memo"] == "Initial memo."
    assert task["priority"] == "high"
    assert task["status"] == "not_started"
    assert task["deleted_at"] is None

    list_response = client.get(f"/api/v1/tasks?case_id={case['id']}")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [task["id"]]

    update_response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "base_version": task["version"],
            "title": "Prepare final review notes",
            "done_when_text": "Final notes are shared with the committee.",
            "progress_memo": "Read the abstract and methods.",
            "priority": "low",
            "status": "in_progress",
            "worked_minutes": 15,
        },
    )
    assert update_response.status_code == 200
    updated_task = update_response.json()["data"]["task"]
    assert updated_task["title"] == "Prepare final review notes"
    assert updated_task["done_when_text"] == "Final notes are shared with the committee."
    assert updated_task["progress_memo"] == "Read the abstract and methods."
    assert updated_task["priority"] == "low"
    assert updated_task["status"] == "in_progress"
    assert updated_task["worked_minutes"] == 15
    assert updated_task["storage_directory_id"] == task["storage_directory_id"]

    delete_response = client.post(
        f"/api/v1/tasks/{task['id']}/delete",
        json={"reason": "duplicate"},
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted"] is True

    with sqlite3.connect(database_path) as connection:
        deleted_directory_status = connection.execute(
            "SELECT status FROM storage_directories WHERE id = ?",
            (task["storage_directory_id"],),
        ).fetchone()[0]
    assert deleted_directory_status == "deleted"

    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert client.get(f"/api/v1/tasks/{task['id']}?include_deleted=1").status_code == 200

    restore_response = client.post(f"/api/v1/tasks/{task['id']}/restore")
    assert restore_response.status_code == 200
    assert restore_response.json()["data"]["task"]["deleted_at"] is None

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT title, status, priority, deleted_at, storage_directory_id FROM tasks WHERE id = ?",
            (task["id"],),
        ).fetchone()
        directory_row = connection.execute(
            "SELECT parent_id, directory_kind, case_id, name, status FROM storage_directories WHERE id = ?",
            (task["storage_directory_id"],),
        ).fetchone()
    assert row == (
        "Prepare final review notes",
        "in_progress",
        "low",
        None,
        task["storage_directory_id"],
    )
    assert directory_row == (
        case["storage_directory_id"],
        "task",
        case["id"],
        "Prepare final review notes",
        "active",
    )

    directories_response = client.get(
        f"/api/v1/storage/directories?parent_id={case['storage_directory_id']}",
    )
    assert directories_response.status_code == 200
    directories = directories_response.json()["data"]["items"]
    assert any(
        item["id"] == task["storage_directory_id"]
        and item["name"] == "Prepare final review notes"
        and item["directory_kind"] == "task"
        for item in directories
    )


def test_task_progress_entries_are_appended_as_timeline(client) -> None:
    case = create_case(client, "Progress Entry Case")
    task = client.post(
        "/api/v1/tasks",
        json={"case_id": case["id"], "title": "Write progress"},
    ).json()["data"]["task"]
    assert task["status"] == "not_started"

    first_response = client.post(
        f"/api/v1/tasks/{task['id']}/progress-entries",
        json={"body": "Read the first document."},
    )
    assert first_response.status_code == 200
    first_data = first_response.json()["data"]
    assert first_data["entry"]["body"] == "Read the first document."
    assert first_data["task"]["status"] == "in_progress"
    assert first_data["task"]["progress_memo"] == "Read the first document."
    assert [item["body"] for item in first_data["task"]["progress_entries"]] == [
        "Read the first document."
    ]
    first_entry_id = first_data["entry"]["id"]

    update_entry_response = client.patch(
        f"/api/v1/tasks/{task['id']}/progress-entries/{first_entry_id}",
        json={"body": "Read the first document and made notes."},
    )
    assert update_entry_response.status_code == 200
    assert update_entry_response.json()["data"]["entry"]["body"] == (
        "Read the first document and made notes."
    )

    second_response = client.post(
        f"/api/v1/tasks/{task['id']}/progress-entries",
        json={"body": "Drafted a response."},
    )
    assert second_response.status_code == 200
    second_entry_id = second_response.json()["data"]["entry"]["id"]

    delete_entry_response = client.delete(
        f"/api/v1/tasks/{task['id']}/progress-entries/{second_entry_id}",
    )
    assert delete_entry_response.status_code == 200
    assert delete_entry_response.json()["data"]["deleted"] is True

    detail_response = client.get(f"/api/v1/tasks/{task['id']}")
    assert detail_response.status_code == 200
    detail_task = detail_response.json()["data"]["task"]
    assert [item["body"] for item in detail_task["progress_entries"]] == [
        "Read the first document and made notes.",
    ]
    assert detail_task["progress_memo"] == "Read the first document and made notes."


def test_completed_task_keeps_progress_entries_and_uses_overwritable_done_memo(
    client,
    database_path: Path,
) -> None:
    case = create_case(client, "Done Memo Case")
    task = client.post(
        "/api/v1/tasks",
        json={"case_id": case["id"], "title": "Finish memo behavior"},
    ).json()["data"]["task"]

    entry_response = client.post(
        f"/api/v1/tasks/{task['id']}/progress-entries",
        json={"body": "Progress before completion."},
    )
    assert entry_response.status_code == 200

    complete_response = client.post(f"/api/v1/tasks/{task['id']}/complete")
    assert complete_response.status_code == 200
    completed_task = complete_response.json()["data"]["task"]
    assert completed_task["status"] == "completed"
    assert completed_task["progress_memo"] is None
    assert [item["body"] for item in completed_task["progress_entries"]] == [
        "Progress before completion.",
    ]
    with sqlite3.connect(database_path) as connection:
        completed_directory = connection.execute(
            """
            SELECT id, parent_id, directory_kind, case_id, name, status
            FROM storage_directories
            WHERE id = ?
            """,
            (completed_task["storage_directory_id"],),
        ).fetchone()
        completed_tasks_parent = connection.execute(
            """
            SELECT id, parent_id, directory_kind, case_id, name, status
            FROM storage_directories
            WHERE id = ?
            """,
            (f"storage_directory_case_{case['id']}_completed_tasks",),
        ).fetchone()
    assert completed_tasks_parent == (
        f"storage_directory_case_{case['id']}_completed_tasks",
        case["storage_directory_id"],
        "normal",
        case["id"],
        "Completed Tasks",
        "active",
    )
    assert completed_directory == (
        completed_task["storage_directory_id"],
        completed_tasks_parent[0],
        "task",
        case["id"],
        "Finish memo behavior",
        "active",
    )

    append_response = client.post(
        f"/api/v1/tasks/{task['id']}/progress-entries",
        json={"body": "This should not become a dated entry."},
    )
    assert append_response.status_code == 409
    assert append_response.json()["error"]["code"] == "TASK_CLOSED"

    done_memo_response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "base_version": completed_task["version"],
            "progress_memo": "Memo after Done.",
        },
    )
    assert done_memo_response.status_code == 200
    done_memo_task = done_memo_response.json()["data"]["task"]
    assert done_memo_task["status"] == "completed"
    assert done_memo_task["progress_memo"] == "Memo after Done."
    assert [item["body"] for item in done_memo_task["progress_entries"]] == [
        "Progress before completion.",
    ]


def test_task_start_date_arrival_moves_not_started_to_in_progress(client) -> None:
    case = create_case(client, "Started Task Case")
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Start date arrived",
            "start_at": "2000-01-01",
        },
    ).json()["data"]["task"]
    assert task["status"] == "in_progress"

    future_task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Future task",
            "start_at": "2999-01-01",
        },
    ).json()["data"]["task"]
    assert future_task["status"] == "not_started"

    list_response = client.get(f"/api/v1/tasks?case_id={case['id']}&status=all")
    assert list_response.status_code == 200
    listed = {item["id"]: item for item in list_response.json()["data"]["items"]}
    assert listed[task["id"]]["status"] == "in_progress"
    assert listed[future_task["id"]]["status"] == "not_started"


def test_task_in_not_started_case_does_not_auto_start(client) -> None:
    response = client.post(
        "/api/v1/cases",
        json={
            "name": "Future Case",
            "progress_status": "not_started",
            "ball_status": "none",
            "open_when_date": "2999-01-01",
        },
    )
    assert response.status_code == 200
    case = response.json()["data"]["case"]

    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Case is not started",
            "start_at": "2000-01-01",
        },
    ).json()["data"]["task"]
    assert task["status"] == "not_started"
    assert task["case_open_when_date"] == "2999-01-01"

    list_response = client.get(f"/api/v1/tasks?case_id={case['id']}&status=all")
    assert list_response.status_code == 200
    listed_task = list_response.json()["data"]["items"][0]
    assert listed_task["status"] == "not_started"
    assert listed_task["case_open_when_date"] == "2999-01-01"


def test_monthly_recurring_task_creates_next_task_on_complete(client) -> None:
    case = create_case(client, "Monthly Recurring Task Case")
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Monthly report",
            "due_at": "2099-01-31",
            "recurrence_rule_type": "monthly",
            "recurrence_month_day": 0,
            "recurrence_start_offset_days": -7,
        },
    ).json()["data"]["task"]
    assert task["recurrence_rule_type"] == "monthly"

    complete_response = client.post(f"/api/v1/tasks/{task['id']}/complete")
    assert complete_response.status_code == 200
    data = complete_response.json()["data"]
    next_task = data["next_recurring_task"]
    assert next_task is not None
    assert next_task["case_id"] == case["id"]
    assert next_task["title"] == "Monthly report"
    assert next_task["due_at"] == "2099-02-28"
    assert next_task["start_at"] == "2099-02-21"
    assert next_task["source_type"] == "recurring"
    assert next_task["source_id"] == task["id"]
    assert next_task["recurrence_series_id"] == task["id"]
    assert next_task["recurrence_sequence"] == 1


def test_monthly_weekday_recurring_task_creates_next_task_on_complete(client) -> None:
    case = create_case(client, "Monthly Weekday Recurring Task Case")
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Monthly last Friday report",
            "due_at": "2099-01-31",
            "recurrence_rule_type": "monthly",
            "recurrence_month_week": -1,
            "recurrence_month_weekday": 5,
            "recurrence_start_offset_days": -3,
        },
    ).json()["data"]["task"]
    assert task["recurrence_month_week"] == -1
    assert task["recurrence_month_weekday"] == 5

    complete_response = client.post(f"/api/v1/tasks/{task['id']}/complete")
    assert complete_response.status_code == 200
    next_task = complete_response.json()["data"]["next_recurring_task"]
    assert next_task["due_at"] == "2099-02-27"
    assert next_task["start_at"] == "2099-02-24"
    assert next_task["recurrence_month_day"] is None
    assert next_task["recurrence_month_week"] == -1
    assert next_task["recurrence_month_weekday"] == 5


def test_yearly_recurring_task_creates_next_task_on_complete(client) -> None:
    case = create_case(client, "Yearly Recurring Task Case")
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Annual report",
            "due_at": "2099-03-31",
            "recurrence_rule_type": "yearly",
            "recurrence_year_month": 3,
            "recurrence_month_day": 0,
            "recurrence_start_offset_days": -14,
        },
    ).json()["data"]["task"]
    assert task["recurrence_rule_type"] == "yearly"
    assert task["recurrence_year_month"] == 3

    complete_response = client.post(f"/api/v1/tasks/{task['id']}/complete")
    assert complete_response.status_code == 200
    next_task = complete_response.json()["data"]["next_recurring_task"]
    assert next_task["due_at"] == "2100-03-31"
    assert next_task["start_at"] == "2100-03-17"
    assert next_task["recurrence_rule_type"] == "yearly"
    assert next_task["recurrence_year_month"] == 3
    assert next_task["recurrence_month_day"] == 0


def test_recurring_task_without_dates_autofills_initial_dates(client) -> None:
    case = create_case(client, "Autofill Recurring Dates Case")
    today = date.today()
    sunday_based_today = (today.weekday() + 1) % 7
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Weekly auto date task",
            "recurrence_rule_type": "weekly",
            "recurrence_weekdays": [sunday_based_today],
            "recurrence_start_offset_days": -2,
        },
    ).json()["data"]["task"]

    assert task["due_at"] == today.isoformat()
    assert task["start_at"] == (today - timedelta(days=2)).isoformat()


def test_adding_recurrence_to_undated_task_autofills_dates(client) -> None:
    case = create_case(client, "Patch Recurring Dates Case")
    task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Patch repeat later",
        },
    ).json()["data"]["task"]
    assert task["due_at"] is None
    assert task["start_at"] is None

    response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={
            "base_version": task["version"],
            "recurrence_rule_type": "monthly",
            "recurrence_month_day": 0,
            "recurrence_start_offset_days": -7,
        },
    )
    assert response.status_code == 200
    updated = response.json()["data"]["task"]
    assert updated["due_at"] is not None
    assert updated["start_at"] == (
        date.fromisoformat(updated["due_at"]) - timedelta(days=7)
    ).isoformat()


def next_expected_weekday(base: date, weekdays: set[int], *, interval_weeks: int) -> date:
    for delta in range(1, 370):
        candidate = base + timedelta(days=delta)
        sunday_based_weekday = (candidate.weekday() + 1) % 7
        if sunday_based_weekday in weekdays and (interval_weeks == 1 or delta >= 8):
            return candidate
    raise AssertionError("No expected weekday found.")


def test_weekly_and_biweekly_recurring_tasks_create_next_task_on_complete(client) -> None:
    case = create_case(client, "Weekly Recurring Task Case")
    for rule_type, interval_weeks in (("weekly", 1), ("biweekly", 2)):
        task = client.post(
            "/api/v1/tasks",
            json={
                "case_id": case["id"],
                "title": f"{rule_type} meeting prep",
                "due_at": "2099-01-01",
                "recurrence_rule_type": rule_type,
                "recurrence_weekdays": [1, 5],
                "recurrence_start_offset_days": -2,
            },
        ).json()["data"]["task"]
        complete_response = client.post(f"/api/v1/tasks/{task['id']}/complete")
        assert complete_response.status_code == 200
        next_task = complete_response.json()["data"]["next_recurring_task"]
        expected_due = next_expected_weekday(
            date.fromisoformat("2099-01-01"),
            {1, 5},
            interval_weeks=interval_weeks,
        )
        assert next_task["due_at"] == expected_due.isoformat()
        assert next_task["start_at"] == (expected_due - timedelta(days=2)).isoformat()
        assert next_task["recurrence_rule_type"] == rule_type
        assert next_task["recurrence_weekdays"] == [1, 5]


def test_task_complete_requires_closed_child_tasks(client) -> None:
    case = create_case(client, "Parent Task Case")
    parent = client.post(
        "/api/v1/tasks",
        json={"case_id": case["id"], "title": "Parent task"},
    ).json()["data"]["task"]
    child = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "parent_task_id": parent["id"],
            "title": "Child task",
        },
    ).json()["data"]["task"]

    blocked_response = client.post(f"/api/v1/tasks/{parent['id']}/complete")
    assert blocked_response.status_code == 409
    assert blocked_response.json()["error"]["code"] == "OPEN_CHILD_TASKS"

    parent_detail_response = client.get(f"/api/v1/tasks/{parent['id']}")
    assert parent_detail_response.status_code == 200
    assert [item["id"] for item in parent_detail_response.json()["data"]["task"]["subtasks"]] == [
        child["id"]
    ]

    child_complete_response = client.post(f"/api/v1/tasks/{child['id']}/complete")
    assert child_complete_response.status_code == 200
    assert child_complete_response.json()["data"]["task"]["status"] == "completed"

    parent_complete_response = client.post(f"/api/v1/tasks/{parent['id']}/complete")
    assert parent_complete_response.status_code == 200
    assert parent_complete_response.json()["data"]["task"]["status"] == "completed"
    assert parent_complete_response.json()["data"]["optimistic_state"]["status"] == "completed"


def test_task_cancel_and_case_complete_constraint(client) -> None:
    case = create_case(client, "Case Complete Task Constraint")
    open_task = client.post(
        "/api/v1/tasks",
        json={"case_id": case["id"], "title": "Open task"},
    ).json()["data"]["task"]

    blocked_case_response = client.post(f"/api/v1/cases/{case['id']}/complete")
    assert blocked_case_response.status_code == 409
    assert blocked_case_response.json()["error"]["code"] == "OPEN_TASKS"

    cancel_response = client.post(
        f"/api/v1/tasks/{open_task['id']}/cancel",
        json={"reason": "No longer needed"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["task"]["status"] == "canceled"
    assert cancel_response.json()["data"]["task"]["canceled_reason"] == "No longer needed"

    complete_case_response = client.post(f"/api/v1/cases/{case['id']}/complete")
    assert complete_case_response.status_code == 200
    assert complete_case_response.json()["data"]["case"]["progress_status"] == "completed"


def test_task_rejects_invalid_parent_case(client) -> None:
    case_a = create_case(client, "Case A")
    case_b = create_case(client, "Case B")
    parent = client.post(
        "/api/v1/tasks",
        json={"case_id": case_a["id"], "title": "Parent in A"},
    ).json()["data"]["task"]

    response = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case_b["id"],
            "parent_task_id": parent["id"],
            "title": "Child in B",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PARENT_TASK"


def test_task_can_be_generated_from_assigned_mail(client, database_path: Path) -> None:
    case = create_case(client, "Mail Task Case")
    message_id = ingest_task_source_mail(client, subject="Please review the draft")
    assign_response = client.post(
        f"/api/v1/mails/{message_id}/case-links",
        json={"case_id": case["id"]},
    )
    assert assign_response.status_code == 200

    response = client.post(
        "/api/v1/tasks/from-mail",
        json={"message_id": message_id},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    task = data["task"]
    assert task["case_id"] == case["id"]
    assert task["source_type"] == "mail"
    assert task["source_id"] == message_id
    assert task["start_at"] == jst_today()
    assert task["title"] != ""
    assert data["prefill"]["priority"] == "middle"
    assert data["llm_run_id"].startswith("llm_run_")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT source_type, source_id FROM tasks WHERE id = ?",
            (task["id"],),
        ).fetchone()
        llm_row = connection.execute(
            "SELECT function_type, status FROM llm_runs WHERE id = ?",
            (data["llm_run_id"],),
        ).fetchone()
    assert row == ("mail", message_id)
    assert llm_row == ("mail_task_suggestion", "succeeded")


def test_task_generation_with_case_id_assigns_source_mail_thread(
    client,
    database_path: Path,
) -> None:
    case = create_case(client, "Explicit Mail Task Case")
    message_id = ingest_task_source_mail(client, subject="Please prepare handout")

    response = client.post(
        "/api/v1/tasks/from-mail",
        json={"message_id": message_id, "case_id": case["id"]},
    )
    assert response.status_code == 200
    task = response.json()["data"]["task"]
    assert task["case_id"] == case["id"]
    assert task["source_id"] == message_id

    with sqlite3.connect(database_path) as connection:
        link_count = connection.execute(
            """
            SELECT count(1)
            FROM case_mail_links
            WHERE case_id = ? AND message_id = ?
            """,
            (case["id"], message_id),
        ).fetchone()[0]
    assert link_count == 1


def test_case_detail_exposes_next_task_and_task_counts(client) -> None:
    case = create_case(client, "Case Task Summary")
    later = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Later task",
            "due_at": "2026-06-20",
        },
    ).json()["data"]["task"]
    next_task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Soon task",
            "due_at": "2026-06-10",
        },
    ).json()["data"]["task"]
    client.post(f"/api/v1/tasks/{later['id']}/complete")

    response = client.get(f"/api/v1/cases/{case['id']}")
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["case"]["open_task_count"] == 1
    assert detail["case"]["next_task"]["id"] == next_task["id"]
    assert detail["case"]["next_task"]["title"] == "Soon task"
    assert [item["id"] for item in detail["tasks"]] == [next_task["id"]]


def test_case_detail_uses_not_started_task_as_next_task_fallback(client) -> None:
    case = create_case(client, "Case Future Task Summary")
    future_task = client.post(
        "/api/v1/tasks",
        json={
            "case_id": case["id"],
            "title": "Future task",
            "start_at": "2099-01-01",
            "due_at": "2099-01-08",
        },
    ).json()["data"]["task"]

    response = client.get(f"/api/v1/cases/{case['id']}")

    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["case"]["open_task_count"] == 0
    assert detail["case"]["next_task"]["id"] == future_task["id"]
    assert detail["tasks"] == []
