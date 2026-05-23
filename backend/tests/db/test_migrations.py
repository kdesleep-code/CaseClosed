from __future__ import annotations

from conftest import PHASE_1_TABLES
from conftest import PHASE_2_TABLES
from conftest import PHASE_3_TABLES
from conftest import sqlite_table_names
import sqlite3


def test_phase_1_migrations_upgrade_a_new_sqlite_database(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_1_TABLES <= table_names


def test_phase_2_migrations_add_job_and_writer_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_2_TABLES <= table_names


def test_phase_3_migrations_add_contact_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_3_TABLES <= table_names

    with sqlite3.connect(migrated_database) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(contact_email_addresses)"
            ).fetchall()
        }
        contact_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(contacts)").fetchall()
        }

    assert {
        "status",
        "has_inbound_message_history",
        "deactivated_at",
        "deleted_at",
    } <= columns
    assert {
        "kind",
        "sender_resolution_mode",
        "mailing_list_recipient_expression",
    } <= contact_columns
