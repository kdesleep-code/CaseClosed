from __future__ import annotations

import sqlite3


def test_phase_1_seed_data_creates_system_cases(migrated_database) -> None:
    with sqlite3.connect(migrated_database) as connection:
        rows = connection.execute(
            """
            SELECT name, system_case_key, is_system_case
            FROM cases
            WHERE system_case_key IN ('inbox', 'system_maintenance')
            ORDER BY system_case_key
            """
        ).fetchall()

    assert rows == [
        ("Inbox / なんでも箱", "inbox", 1),
        ("システムメンテナンス", "system_maintenance", 1),
    ]

