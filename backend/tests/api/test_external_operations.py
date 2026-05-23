from __future__ import annotations

from pathlib import Path

import sqlite3

from conftest import insert_phase_2_external_operation

EXTERNAL_OPERATIONS_URL = "/api/v1/external-operations"


def test_external_operations_list_filters_unknown_operations(
    client,
    database_path: Path,
) -> None:
    insert_phase_2_external_operation(
        database_path,
        operation_id="op_unknown",
        status="unknown",
    )
    insert_phase_2_external_operation(
        database_path,
        operation_id="op_pending",
        status="pending",
    )

    response = client.get(f"{EXTERNAL_OPERATIONS_URL}?status=unknown")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert [
        operation["id"] for operation in response.json()["data"]["items"]
    ] == ["op_unknown"]
    assert response.json()["data"]["items"][0]["unknown_reason"] == (
        "network result unknown"
    )


def test_unknown_external_operation_can_be_marked_succeeded(
    client,
    database_path: Path,
) -> None:
    insert_phase_2_external_operation(
        database_path,
        operation_id="op_unknown",
        status="unknown",
    )

    response = client.post(
        f"{EXTERNAL_OPERATIONS_URL}/op_unknown/resolve",
        json={
            "resolution": "mark_succeeded",
            "external_id": "gmail-message-1",
            "note": "Checked Gmail manually.",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "succeeded"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, external_id, manual_resolution_required
            FROM external_operations
            WHERE id = ?
            """,
            ("op_unknown",),
        ).fetchone()

    assert row == ("succeeded", "gmail-message-1", 0)


def test_pending_external_operation_cannot_be_manually_resolved(
    client,
    database_path: Path,
) -> None:
    insert_phase_2_external_operation(
        database_path,
        operation_id="op_pending",
        status="pending",
    )

    response = client.post(
        f"{EXTERNAL_OPERATIONS_URL}/op_pending/resolve",
        json={"resolution": "mark_failed"},
    )

    assert response.status_code == 409
    assert response.json()["ok"] is False
