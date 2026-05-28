from __future__ import annotations

from conftest import PHASE_1_TABLES
from conftest import PHASE_2_TABLES
from conftest import PHASE_3_TABLES
from conftest import PHASE_4_TABLES
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
        "mail_importance_rule_action",
        "mail_importance_rule_importance",
        "mail_importance_rule_instruction",
    } <= contact_columns


def test_phase_4_migrations_add_mail_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_4_TABLES <= table_names

    with sqlite3.connect(migrated_database) as connection:
        message_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(gmail_messages)").fetchall()
        }
        auto_state_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(mail_auto_state)").fetchall()
        }
        user_state_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(mail_user_state)").fetchall()
        }
        summary_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(mail_summaries)").fetchall()
        }
        block_filter_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(mail_llm_block_filters)"
            ).fetchall()
        }
        thread_summary_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(mail_thread_summaries)"
            ).fetchall()
        }
        send_request_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(mail_send_requests)"
            ).fetchall()
        }

    assert {
        "gmail_message_id",
        "gmail_thread_id",
        "message_id_header",
        "reply_to_address",
        "list_id",
    } <= message_columns
    assert {
        "effective_importance",
        "llm_run_id",
        "pending_reason",
        "pending_from_address_id",
        "llm_blocked",
        "llm_block_reason",
        "llm_blocked_at",
    } <= auto_state_columns
    assert {"read_status", "read_at"} <= user_state_columns
    assert {
        "message_id",
        "summary_text",
        "action_required",
        "deadline_text",
        "next_action",
        "key_points_json",
        "translation_text",
        "language",
        "llm_run_id",
    } <= summary_columns
    assert {
        "query_text",
        "reason",
        "is_enabled",
        "created_at",
        "updated_at",
        "version",
    } <= block_filter_columns
    assert {
        "thread_id",
        "summary_text",
        "action_required",
        "next_action",
        "key_points_json",
        "translation_text",
        "language",
        "llm_run_id",
    } <= thread_summary_columns
    assert {"attachment_names_json", "attachment_data_json"} <= send_request_columns
