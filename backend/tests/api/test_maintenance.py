from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now

from conftest import insert_phase_2_external_operation
from conftest import insert_phase_2_job


def test_maintenance_status_reports_phase_1_defaults(client) -> None:
    response = client.get("/api/v1/maintenance/status")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": {
            "job_accepting": True,
            "running_jobs": 0,
            "action_required_jobs": 0,
            "pending_write_requests": 0,
            "external_unknown_count": 0,
            "llm_cost_month_used": 0.0,
            "llm_cost_month_remaining": None,
            "backup_status": "not_configured",
        },
    }


def test_maintenance_debug_lists_storage_operation_history(client) -> None:
    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "history.txt",
            "content_type": "text/plain",
            "data_base64": "aGlzdG9yeQ==",
        },
    )
    storage_object_id = upload_response.json()["data"]["storage_object"]["id"]

    response = client.get("/api/v1/maintenance/storage-operation-history")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert items[0]["storage_object_id"] == storage_object_id
    assert items[0]["operation_type"] == "created"
    assert items[0]["original_filename"] == "history.txt"
    assert items[0]["byte_size"] == len(b"history")


def test_maintenance_storage_operation_history_hides_contact_images(client) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Avatar Person",
            "avatar_url": None,
            "user_memo": "",
            "ai_memo": None,
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "tags": [],
            "email_addresses": [
                {"email_address": "avatar-person@example.com", "is_primary": True}
            ],
        },
    )
    contact_id = contact_response.json()["data"]["id"]

    image_response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "avatar.svg",
            "content_type": "image/svg+xml",
            "data_base64": "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4=",
        },
    )
    assert image_response.status_code == 200

    response = client.get("/api/v1/maintenance/storage-operation-history")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert all(item["scope"] == "managed" for item in items)
    assert all(item["original_filename"] != "avatar.svg" for item in items)


def test_maintenance_status_counts_phase_2_work(
    client,
    database_path: Path,
) -> None:
    insert_phase_2_job(database_path, job_id="job_running", status="running")
    insert_phase_2_external_operation(
        database_path,
        operation_id="op_unknown",
        status="unknown",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO write_requests (
                id, source, priority, operation_type, entity_type,
                payload_json, status, created_at
            ) VALUES (
                'wr_pending', 'system', 50, 'case_event.append',
                'case_event', '{}', 'pending', '2026-05-22T10:00:00+09:00'
            )
            """
        )
        connection.commit()

    response = client.get("/api/v1/maintenance/status")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "job_accepting": True,
        "running_jobs": 1,
        "action_required_jobs": 0,
        "pending_write_requests": 1,
        "external_unknown_count": 1,
        "llm_cost_month_used": 0.0,
        "llm_cost_month_remaining": None,
        "backup_status": "not_configured",
    }


def test_llm_cost_history_reports_budget_remaining(
    client,
    database_path: Path,
) -> None:
    now = jst_now()
    today = now.date().isoformat()
    first_started = now - timedelta(minutes=1)
    second_started = now
    first_started_at = jst_iso(first_started)
    first_finished_at = jst_iso(first_started + timedelta(seconds=1))
    second_started_at = jst_iso(second_started)
    second_finished_at = jst_iso(second_started + timedelta(seconds=1))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"""
            INSERT INTO llm_runs (
                id, function_type, provider_name, model_name, input_source_json,
                status, retry_count, max_retry_count, prompt_tokens,
                completion_tokens, total_tokens, estimated_cost, started_at,
                finished_at, created_at
            ) VALUES (
                'llm_run_cost_1', 'mail_summary', 'openai', 'gpt-test',
                '{{}}', 'succeeded', 0, 3, 100, 50, 150, 1.25,
                '{first_started_at}',
                '{first_finished_at}',
                '{first_started_at}'
            )
            """
        )
        connection.execute(
            f"""
            INSERT INTO llm_runs (
                id, function_type, provider_name, model_name, input_source_json,
                status, retry_count, max_retry_count, prompt_tokens,
                completion_tokens, total_tokens, estimated_cost, started_at,
                finished_at, created_at
            ) VALUES (
                'llm_run_cost_2', 'mail_thread_summary', 'openai', 'gpt-test',
                '{{}}', 'succeeded', 0, 3, 200, 80, 280, 2.5,
                '{second_started_at}',
                '{second_finished_at}',
                '{second_started_at}'
            )
            """
        )
        connection.commit()

    settings_response = client.patch(
        "/api/v1/maintenance/llm-cost-settings",
        json={"monthly_budget": 10.0},
    )

    assert settings_response.status_code == 200
    settings_data = settings_response.json()["data"]
    assert settings_data["monthly_budget"] == 10.0
    assert settings_data["month_used"] == 3.75
    assert settings_data["month_remaining"] == 6.25

    history_response = client.get("/api/v1/maintenance/llm-cost-history")

    assert history_response.status_code == 200
    history_data = history_response.json()["data"]
    assert history_data["source"] == "local_estimate"
    assert history_data["currency"] == "usd"
    assert history_data["today_used"] == 3.75
    assert history_data["total_used"] == 3.75
    assert history_data["daily"][-1]["date"] == today
    assert history_data["daily"][-1]["estimated_cost"] == 3.75
    assert history_data["by_function"][0]["estimated_cost"] == 2.5
    assert history_data["recent_runs"][0]["id"] == "llm_run_cost_2"
