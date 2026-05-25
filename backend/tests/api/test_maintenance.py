from __future__ import annotations

import sqlite3
from pathlib import Path

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
            "backup_status": "not_configured",
        },
    }


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
        "backup_status": "not_configured",
    }
