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


def test_phase_1_seed_data_creates_default_settings(migrated_database) -> None:
    with sqlite3.connect(migrated_database) as connection:
        rows = connection.execute(
            """
            SELECT key, value_json
            FROM app_settings
            ORDER BY key
            """
        ).fetchall()

    assert rows == [
        ("default_follow_up_days", "7"),
        ("llm_cost_limit_daily", "null"),
        ("llm_cost_limit_monthly", "null"),
        ("login_failure_limit", "5"),
        ("session_lifetime_hours", "24"),
        ("worker_max_count", "4"),
        ("worker_min_count", "1"),
    ]
