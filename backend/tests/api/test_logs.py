from __future__ import annotations

import sqlite3
from pathlib import Path


def test_logs_list_combines_types_with_search_and_paging(
    client,
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO system_logs (
                id, level, component, message, metadata_json, occurred_at, created_at
            ) VALUES (
                'system_log_1', 'warning', 'calendar', 'Calendar sync delayed',
                '{"calendar":"primary"}', '2026-06-14T10:00:00+09:00',
                '2026-06-14T10:00:00+09:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_logs (
                id, action_type, target_type, target_id, metadata_json,
                occurred_at, created_at
            ) VALUES (
                'audit_log_1', 'case.updated', 'case', 'case_1',
                '{"name":"Target"}', '2026-06-14T11:00:00+09:00',
                '2026-06-14T11:00:00+09:00'
            )
            """
        )
        connection.commit()

    response = client.get("/api/v1/logs?q=calendar&types=system,audit")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page_size"] == 100
    assert data["total"] == 1
    assert data["items"][0]["id"] == "system_log_1"
    assert data["items"][0]["source_type"] == "system"
    assert data["items"][0]["metadata"] == {"calendar": "primary"}


def test_logs_export_returns_csv(client, database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO system_logs (
                id, level, component, message, metadata_json, occurred_at, created_at
            ) VALUES (
                'system_log_csv', 'info', 'storage', 'Export me',
                NULL, '2026-06-14T12:00:00+09:00',
                '2026-06-14T12:00:00+09:00'
            )
            """
        )
        connection.commit()

    response = client.get("/api/v1/logs/export?q=Export%20me&types=system")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "caseclosed-logs.csv" in response.headers["content-disposition"]
    assert "system_log_csv" in response.text
    assert "Export me" in response.text


def test_storage_logs_only_include_managed_scope(client, database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO storage_operation_history (
                id, storage_object_id, operation_type, actor, scope,
                original_filename, content_type, byte_size, storage_path,
                source_type, source_message_id, directory_id, details_json, created_at
            ) VALUES (
                'storage_log_managed', 'storage_object_managed', 'created',
                'user', 'managed', 'paper.pdf', 'application/pdf', 123,
                'data/storage/managed/paper.pdf', NULL, NULL, NULL, NULL,
                '2026-06-14T12:00:00+09:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO storage_operation_history (
                id, storage_object_id, operation_type, actor, scope,
                original_filename, content_type, byte_size, storage_path,
                source_type, source_message_id, directory_id, details_json, created_at
            ) VALUES (
                'storage_log_contact_image', 'storage_object_contact_image', 'created',
                'user', 'contact_image', 'avatar.png', 'image/png', 456,
                'data/storage/contact-images/avatar.png', NULL, NULL, NULL, NULL,
                '2026-06-14T12:01:00+09:00'
            )
            """
        )
        connection.commit()

    response = client.get("/api/v1/logs?types=storage")

    assert response.status_code == 200
    item_ids = [item["id"] for item in response.json()["data"]["items"]]
    assert item_ids == ["storage_log_managed"]
