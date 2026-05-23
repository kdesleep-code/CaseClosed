from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path


def test_single_db_writer_applies_pending_case_event_write_request(
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
                'wr_case_event', 'system', 50, 'case_event.append',
                'case_event', 'event_writer_test',
                ?, 'pending', '2026-05-22T10:00:00+09:00'
            )
            """,
            (
                """
                {
                  "case_id": "case_system_inbox",
                  "event_type": "writer_test",
                  "title": "Writer applied",
                  "occurred_at": "2026-05-22T10:01:00+09:00"
                }
                """,
            ),
        )
        connection.commit()

    writer = importlib.import_module("caseclosed.services.single_db_writer")

    assert writer.apply_next_write_request() == "wr_case_event"

    with sqlite3.connect(database_path) as connection:
        write_row = connection.execute(
            "SELECT status, applied_at FROM write_requests WHERE id = ?",
            ("wr_case_event",),
        ).fetchone()
        event_row = connection.execute(
            "SELECT id, case_id, event_type, title FROM case_events WHERE id = ?",
            ("event_writer_test",),
        ).fetchone()

    assert write_row[0] == "applied"
    assert write_row[1].endswith("+09:00")
    assert event_row == (
        "event_writer_test",
        "case_system_inbox",
        "writer_test",
        "Writer applied",
    )
