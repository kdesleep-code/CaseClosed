from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_audit_log_writer_records_audit_log_without_write_request(
    client,
    database_path: Path,
) -> None:
    del client
    audit_module = importlib.import_module("caseclosed.services.audit_log_writer")
    writer = audit_module.AuditLogWriter()

    audit_log_id = writer.write(
        action_type="mail_list.view",
        target_type="mail",
        target_id="mail_1",
        metadata={"screen": "mail_list"},
    )

    with sqlite3.connect(database_path) as connection:
        audit_row = connection.execute(
            """
            SELECT action_type, target_type, target_id, metadata_json, occurred_at
            FROM audit_logs
            WHERE id = ?
            """,
            (audit_log_id,),
        ).fetchone()
        write_request_count = connection.execute(
            "SELECT COUNT(*) FROM write_requests",
        ).fetchone()[0]

    assert audit_row[0:4] == (
        "mail_list.view",
        "mail",
        "mail_1",
        '{"screen": "mail_list"}',
    )
    assert audit_row[4].endswith("+09:00")
    assert write_request_count == 0


def test_audit_log_writer_and_single_db_writer_progress_independently(
    client,
    database_path: Path,
) -> None:
    del client
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO write_requests (
                id, source, priority, operation_type, entity_type, entity_id,
                payload_json, status, created_at
            ) VALUES (
                'wr_audit_independent', 'system', 50, 'case_event.append',
                'case_event', 'event_audit_independent',
                ?, 'pending', '2026-05-22T10:00:00+09:00'
            )
            """,
            (
                """
                {
                  "case_id": "case_system_inbox",
                  "event_type": "audit_independent",
                  "title": "Writer progressed",
                  "occurred_at": "2026-05-22T10:01:00+09:00"
                }
                """,
            ),
        )
        connection.commit()

    audit_module = importlib.import_module("caseclosed.services.audit_log_writer")
    single_writer = importlib.import_module("caseclosed.services.single_db_writer")

    audit_log_id = audit_module.AuditLogWriter().write(
        action_type="case_event.queue",
        target_type="write_request",
        target_id="wr_audit_independent",
    )
    assert single_writer.apply_next_write_request() == "wr_audit_independent"

    with sqlite3.connect(database_path) as connection:
        audit_status = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE id = ?",
            (audit_log_id,),
        ).fetchone()[0]
        write_row = connection.execute(
            "SELECT status FROM write_requests WHERE id = ?",
            ("wr_audit_independent",),
        ).fetchone()
        event_row = connection.execute(
            "SELECT title FROM case_events WHERE id = ?",
            ("event_audit_independent",),
        ).fetchone()

    assert audit_status == 1
    assert write_row == ("applied",)
    assert event_row == ("Writer progressed",)
