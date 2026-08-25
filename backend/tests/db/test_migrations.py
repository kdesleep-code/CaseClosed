from __future__ import annotations

from conftest import PHASE_1_TABLES
from conftest import PHASE_2_TABLES
from conftest import PHASE_3_TABLES
from conftest import PHASE_4_TABLES
from conftest import PHASE_6_TABLES
from conftest import PHASE_9_TABLES
from conftest import EXTENSION_TABLES
from conftest import sqlite_table_names
import sqlite3


def test_phase_1_migrations_upgrade_a_new_sqlite_database(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_1_TABLES <= table_names


def test_dictionary_migration_adds_entry_tables_and_indexes(migrated_database) -> None:
    table_names = sqlite_table_names(migrated_database)
    assert {
        "dictionary_entries",
        "dictionary_entry_aliases",
        "dictionary_entry_links",
    } <= table_names

    with sqlite3.connect(migrated_database) as connection:
        index_names = {
            row[1]
            for table_name in ("dictionary_entry_aliases", "dictionary_entry_links")
            for row in connection.execute(f"PRAGMA index_list({table_name})").fetchall()
        }

    assert {
        "ix_dictionary_entry_aliases_entry_id",
        "ix_dictionary_entry_links_source",
        "ix_dictionary_entry_links_target",
    } <= index_names


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
        "inbound_message_count",
    } <= contact_columns


def test_phase_4_migrations_add_mail_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_4_TABLES <= table_names
    assert "mail_send_request_case_links" in table_names

    with sqlite3.connect(migrated_database) as connection:
        message_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(gmail_messages)").fetchall()
        }
        thread_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(gmail_threads)").fetchall()
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
        send_request_case_link_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(mail_send_request_case_links)"
            ).fetchall()
        }
        index_names = {
            row[1]
            for table_name in (
                "gmail_messages",
                "gmail_message_attachments",
                "mail_send_requests",
                "case_mail_links",
                "contact_tags",
                "mail_send_request_case_links",
            )
            for row in connection.execute(f"PRAGMA index_list({table_name})").fetchall()
        }

    assert {
        "gmail_message_id",
        "gmail_thread_id",
        "message_id_header",
        "reply_to_address",
        "list_id",
    } <= message_columns
    assert "future_importance_rule" in thread_columns
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
    assert {"send_request_id", "case_id", "created_at", "updated_at"} <= send_request_case_link_columns
    assert {
        "ix_gmail_messages_received_at_id",
        "ix_gmail_messages_thread_received",
        "ix_gmail_message_attachments_message",
        "ix_mail_send_requests_sent_message",
        "ix_mail_send_requests_visible",
        "ix_case_mail_links_message",
        "ix_contact_tags_contact",
        "ix_mail_send_request_case_links_request",
        "ix_mail_send_request_case_links_case",
    } <= index_names


def test_phase_6_migrations_add_storage_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_6_TABLES <= table_names

    with sqlite3.connect(migrated_database) as connection:
        storage_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(storage_objects)"
            ).fetchall()
        }
        location_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(storage_locations)"
            ).fetchall()
        }
        file_summary_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(file_summaries)"
            ).fetchall()
        }
        file_version_diff_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(file_version_diffs)"
            ).fetchall()
        }
        internal_location = connection.execute(
            """
            SELECT label, kind, root_path, status
            FROM storage_locations
            WHERE id = 'storage_location_internal'
            """
        ).fetchone()

    assert {
        "id",
        "scope",
        "original_filename",
        "content_type",
        "byte_size",
        "sha256_hex",
        "location_id",
        "storage_path",
        "status",
    } <= storage_columns
    assert {
        "id",
        "label",
        "kind",
        "root_path",
        "mount_hint",
        "marker_id",
        "status",
    } <= location_columns
    assert {
        "storage_object_id",
        "storage_object_version_id",
        "source_sha256_hex",
        "file_description",
        "summary_points_json",
        "llm_digest",
        "structured_digest_json",
        "coverage_json",
        "llm_run_id",
    } <= file_summary_columns
    assert {
        "storage_object_id",
        "previous_version_id",
        "previous_sha256_hex",
        "current_sha256_hex",
        "diff_kind",
        "summary_text",
        "added_lines_json",
        "removed_lines_json",
        "coverage_json",
    } <= file_version_diff_columns
    assert internal_location == (
        "Internal Storage",
        "internal",
        "./data/storage",
        "active",
    )


def test_phase_9_migrations_add_calendar_event_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert PHASE_9_TABLES <= table_names

    with sqlite3.connect(migrated_database) as connection:
        event_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(calendar_events)"
            ).fetchall()
        }
        link_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(calendar_event_links)"
            ).fetchall()
        }

    assert {
        "id",
        "source",
        "external_calendar_id",
        "external_event_id",
        "external_etag",
        "external_ical_uid",
        "external_html_link",
        "external_updated_at",
        "google_status",
        "summary",
        "description",
        "location",
        "start_at",
        "end_at",
        "all_day",
        "time_zone",
        "recurring_event_id",
        "attendance_requirement",
        "tags_json",
        "metadata_json",
        "sync_status",
        "last_synced_at",
        "local_note",
        "created_at",
        "updated_at",
        "version",
    } <= event_columns
    assert {
        "id",
        "calendar_event_id",
        "linked_type",
        "linked_id",
        "role",
        "created_at",
        "updated_at",
        "version",
    } <= link_columns


def test_phase_9_migrations_add_academic_calendar_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert {
        "academic_years",
        "academic_semesters",
        "academic_periods",
        "academic_calendar_days",
    } <= table_names

    with sqlite3.connect(migrated_database) as connection:
        year_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(academic_years)"
            ).fetchall()
        }
        semester_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(academic_semesters)"
            ).fetchall()
        }
        period_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(academic_periods)"
            ).fetchall()
        }
        day_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(academic_calendar_days)"
            ).fetchall()
        }

    assert {
        "id",
        "year_label",
        "starts_on",
        "ends_on",
        "note",
        "created_at",
        "updated_at",
        "version",
    } <= year_columns
    assert {
        "id",
        "academic_year_id",
        "label",
        "starts_on",
        "ends_on",
        "sort_order",
        "note",
        "created_at",
        "updated_at",
        "version",
    } <= semester_columns
    assert {
        "id",
        "period_no",
        "label",
        "starts_at",
        "ends_at",
        "sort_order",
        "note",
        "created_at",
        "updated_at",
        "version",
    } <= period_columns
    assert "academic_year_id" not in period_columns
    assert {
        "id",
        "academic_year_id",
        "date",
        "day_type",
        "label",
        "is_teaching_day",
        "effective_weekday",
        "source",
        "note",
        "created_at",
        "updated_at",
        "version",
    } <= day_columns


def test_migrations_add_extension_tables(
    migrated_database,
) -> None:
    table_names = sqlite_table_names(migrated_database)

    assert EXTENSION_TABLES <= table_names

    with sqlite3.connect(migrated_database) as connection:
        definition_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(extension_definitions)"
            ).fetchall()
        }
        instance_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(extension_instances)"
            ).fetchall()
        }

    assert {
        "id",
        "slug",
        "name",
        "description",
        "root_path",
        "command_json",
        "url_path",
        "tags_json",
        "manifest_json",
        "status",
        "created_at",
        "updated_at",
        "version",
    } <= definition_columns
    assert {
        "id",
        "extension_id",
        "case_id",
        "status",
        "host",
        "port",
        "base_url",
        "process_id",
        "token_hash",
        "launch_context_json",
        "started_at",
        "last_seen_at",
        "idle_timeout_seconds",
        "stopped_at",
        "error_message",
        "created_at",
        "updated_at",
        "version",
    } <= instance_columns
