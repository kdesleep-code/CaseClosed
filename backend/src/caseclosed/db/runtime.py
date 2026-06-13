from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from caseclosed.db.base import Base
from caseclosed.db.models import AppSetting
from caseclosed.db.models import Case
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import StorageDirectory
from caseclosed.db.models import StorageLocation
from caseclosed.db.models import Task
from caseclosed.settings import get_database_url
from caseclosed.settings import get_storage_root

JST = timezone(timedelta(hours=9), "JST")
SEED_TIMESTAMP = "2026-05-22T00:00:00+09:00"

INITIAL_SETTINGS = {
    "default_follow_up_days": "7",
    "session_lifetime_hours": "24",
    "login_failure_limit": "5",
    "llm_cost_limit_daily": "null",
    "llm_cost_limit_monthly": "null",
    "worker_min_count": "1",
    "worker_max_count": "4",
}


def jst_now() -> datetime:
    return datetime.now(JST)


def jst_iso(value: datetime | None = None) -> str:
    return (value or jst_now()).astimezone(JST).isoformat()


def parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST)


def build_engine() -> Engine:
    return create_engine(get_database_url(), future=True)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def rebuild_runtime_database() -> None:
    global engine
    global SessionLocal

    engine = build_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def bootstrap_database() -> None:
    Base.metadata.create_all(engine)
    ensure_runtime_schema()

    with SessionLocal() as session:
        seed_settings(session)
        seed_system_cases(session)
        ensure_case_storage_directories(session)
        ensure_task_storage_directories(session)
        seed_storage_locations(session)
        normalize_llm_blocked_mail_importance(session)
        normalize_llm_skip_mail_importance(session)
        session.commit()


def ensure_runtime_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "cases" in table_names:
        case_columns = {column["name"] for column in inspector.get_columns("cases")}
        with engine.begin() as connection:
            if "genre_id" not in case_columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN genre_id TEXT"))
            if "open_when_text" not in case_columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN open_when_text TEXT"))
            if "open_when_date" not in case_columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN open_when_date TEXT"))
            if "closed_when_text" not in case_columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN closed_when_text TEXT"))
            if "tags_json" not in case_columns:
                connection.execute(text("ALTER TABLE cases ADD COLUMN tags_json TEXT"))
    if "case_genres" in table_names:
        genre_columns = {column["name"] for column in inspector.get_columns("case_genres")}
        with engine.begin() as connection:
            if "sort_order" not in genre_columns:
                connection.execute(
                    text("ALTER TABLE case_genres ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
                )
    if "case_stakeholders" not in table_names and "cases" in table_names and "contacts" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_stakeholders (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        contact_id TEXT NOT NULL REFERENCES contacts(id),
                        role TEXT NOT NULL DEFAULT 'stakeholder',
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    if "case_mail_links" not in table_names and "cases" in table_names and "gmail_messages" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_mail_links (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        message_id TEXT NOT NULL REFERENCES gmail_messages(id),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    if "case_auto_assign_rules" not in table_names and "cases" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_auto_assign_rules (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        rule_type TEXT NOT NULL,
                        rule_value TEXT NOT NULL,
                        label TEXT,
                        is_enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        UNIQUE(case_id, rule_type, rule_value)
                    )
                    """
                )
            )
    if "file_links" not in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE file_links (
                        id TEXT PRIMARY KEY,
                        storage_object_id TEXT NOT NULL REFERENCES storage_objects(id),
                        linked_type TEXT NOT NULL,
                        linked_id TEXT NOT NULL,
                        directory_id TEXT,
                        label TEXT,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    elif "directory_id" not in {
        column["name"] for column in inspector.get_columns("file_links")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE file_links ADD COLUMN directory_id TEXT"))
    if "case_tool_links" not in table_names and "cases" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_tool_links (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        url TEXT NOT NULL,
                        icon_label TEXT NOT NULL,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    if "tasks" not in table_names and "cases" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        storage_directory_id TEXT REFERENCES storage_directories(id),
                        parent_task_id TEXT REFERENCES tasks(id),
                        title TEXT NOT NULL,
                        description TEXT,
                        done_when_text TEXT,
                        progress_memo TEXT,
                        status TEXT NOT NULL DEFAULT 'not_started',
                        priority TEXT NOT NULL DEFAULT 'middle',
                        start_at TEXT,
                        due_at TEXT,
                        estimate_minutes INTEGER,
                        scheduled_minutes INTEGER NOT NULL DEFAULT 0,
                        worked_minutes INTEGER NOT NULL DEFAULT 0,
                        source_type TEXT,
                        source_id TEXT,
                        completed_at TEXT,
                        canceled_at TEXT,
                        canceled_reason TEXT,
                        deleted_at TEXT,
                        deleted_reason TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    elif "storage_directory_id" not in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN storage_directory_id TEXT")
            )
    if "tasks" in table_names and "done_when_text" not in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN done_when_text TEXT"))
    if "tasks" in table_names and "priority" not in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'middle'")
            )
    if "tasks" in inspect(engine).get_table_names() and "progress_memo" not in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN progress_memo TEXT"))
    if "tasks" in inspect(engine).get_table_names() and "start_at" not in {
        column["name"] for column in inspect(engine).get_columns("tasks")
    }:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN start_at TEXT"))
    if "tasks" in inspect(engine).get_table_names():
        task_columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
        recurrence_columns = {
            "recurrence_rule_type": "TEXT",
            "recurrence_month_day": "INTEGER",
            "recurrence_year_month": "INTEGER",
            "recurrence_month_week": "INTEGER",
            "recurrence_month_weekday": "INTEGER",
            "recurrence_weekdays_json": "TEXT",
            "recurrence_start_offset_days": "INTEGER",
            "recurrence_series_id": "TEXT",
            "recurrence_sequence": "INTEGER NOT NULL DEFAULT 0",
        }
        with engine.begin() as connection:
            for column_name, column_type in recurrence_columns.items():
                if column_name not in task_columns:
                    connection.execute(
                        text(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_type}")
                    )
    if "task_links" not in table_names and "tasks" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE task_links (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL REFERENCES tasks(id),
                        linked_type TEXT NOT NULL,
                        linked_id TEXT,
                        url TEXT,
                        label TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
    if "task_suggestions" not in table_names and "cases" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE task_suggestions (
                        id TEXT PRIMARY KEY,
                        case_id TEXT REFERENCES cases(id),
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        suggested_title TEXT NOT NULL,
                        suggested_detail TEXT,
                        suggested_due_at TEXT,
                        suggested_estimate_minutes INTEGER,
                        suggested_priority_hint TEXT,
                        suggestion_kind TEXT NOT NULL DEFAULT 'task',
                        parent_task_id TEXT REFERENCES tasks(id),
                        llm_run_id TEXT REFERENCES llm_runs(id),
                        status TEXT NOT NULL DEFAULT 'pending',
                        accepted_task_id TEXT REFERENCES tasks(id),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            )
    if "task_work_blocks" not in table_names and "tasks" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE task_work_blocks (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL REFERENCES tasks(id),
                        calendar_event_link_id TEXT,
                        planned_minutes INTEGER NOT NULL,
                        actual_minutes INTEGER,
                        started_at TEXT,
                        ended_at TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
    if "task_progress_entries" not in inspect(engine).get_table_names() and "tasks" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE task_progress_entries (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL REFERENCES tasks(id),
                        body TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
            )
    if "file_icon_settings" not in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE file_icon_settings (
                        id TEXT PRIMARY KEY,
                        storage_object_id TEXT,
                        icon_filename TEXT,
                        icon_content_type TEXT NOT NULL,
                        icon_data_url TEXT,
                        extensions_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    else:
        file_icon_columns = {
            column["name"] for column in inspector.get_columns("file_icon_settings")
        }
        if "storage_object_id" not in file_icon_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE file_icon_settings ADD COLUMN storage_object_id TEXT")
                )
    if "case_tool_icon_settings" not in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_tool_icon_settings (
                        id TEXT PRIMARY KEY,
                        storage_object_id TEXT,
                        icon_filename TEXT,
                        icon_content_type TEXT NOT NULL,
                        icon_data_url TEXT,
                        match_url TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
    if "calendar_events" not in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE calendar_events (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL DEFAULT 'google',
                        external_calendar_id TEXT,
                        external_event_id TEXT,
                        external_etag TEXT,
                        external_ical_uid TEXT,
                        external_html_link TEXT,
                        external_updated_at TEXT,
                        google_status TEXT,
                        summary TEXT NOT NULL DEFAULT '',
                        description TEXT,
                        location TEXT,
                        start_at TEXT NOT NULL,
                        end_at TEXT NOT NULL,
                        all_day INTEGER NOT NULL DEFAULT 0,
                        time_zone TEXT,
                        recurring_event_id TEXT,
                        attendance_requirement TEXT NOT NULL DEFAULT 'unknown',
                        tags_json TEXT,
                        metadata_json TEXT,
                        sync_status TEXT NOT NULL DEFAULT 'synced',
                        last_synced_at TEXT,
                        local_note TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        UNIQUE(source, external_calendar_id, external_event_id)
                    )
                    """
                )
            )
    if "calendar_events" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_calendar_events_range
                    ON calendar_events (start_at, end_at)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_calendar_events_sync_status
                    ON calendar_events (sync_status)
                    """
                )
            )
    if (
        "calendar_event_links" not in inspect(engine).get_table_names()
        and "calendar_events" in inspect(engine).get_table_names()
    ):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE calendar_event_links (
                        id TEXT PRIMARY KEY,
                        calendar_event_id TEXT NOT NULL REFERENCES calendar_events(id),
                        linked_type TEXT NOT NULL,
                        linked_id TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'related',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        UNIQUE(calendar_event_id, linked_type, linked_id, role)
                    )
                    """
                )
            )
    if "calendar_event_links" in inspect(engine).get_table_names():
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_calendar_event_links_target
                    ON calendar_event_links (linked_type, linked_id)
                    """
                )
            )
    if "contacts" not in table_names:
        return

    contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
    mail_auto_state_columns = (
        {column["name"] for column in inspector.get_columns("mail_auto_state")}
        if "mail_auto_state" in table_names
        else set()
    )
    mail_user_state_columns = (
        {column["name"] for column in inspector.get_columns("mail_user_state")}
        if "mail_user_state" in table_names
        else set()
    )
    mail_summary_columns = (
        {column["name"] for column in inspector.get_columns("mail_summaries")}
        if "mail_summaries" in table_names
        else set()
    )
    mail_send_request_columns = (
        {column["name"] for column in inspector.get_columns("mail_send_requests")}
        if "mail_send_requests" in table_names
        else set()
    )
    mail_thread_summary_columns = (
        {column["name"] for column in inspector.get_columns("mail_thread_summaries")}
        if "mail_thread_summaries" in table_names
        else set()
    )
    storage_object_columns = (
        {column["name"] for column in inspector.get_columns("storage_objects")}
        if "storage_objects" in table_names
        else set()
    )

    with engine.begin() as connection:
        if "avatar_url" not in contact_columns:
            connection.execute(text("ALTER TABLE contacts ADD COLUMN avatar_url TEXT"))
        if "user_memo" not in contact_columns:
            connection.execute(text("ALTER TABLE contacts ADD COLUMN user_memo TEXT"))
            if "memo" in contact_columns:
                connection.execute(
                    text("UPDATE contacts SET user_memo = memo WHERE user_memo IS NULL")
                )
        if "ai_memo" not in contact_columns:
            connection.execute(text("ALTER TABLE contacts ADD COLUMN ai_memo TEXT"))
        if "mail_importance_rule_action" not in contact_columns:
            connection.execute(
                text(
                    "ALTER TABLE contacts ADD COLUMN "
                    "mail_importance_rule_action TEXT NOT NULL DEFAULT 'llm'"
                )
            )
        if "mail_importance_rule_importance" not in contact_columns:
            connection.execute(
                text("ALTER TABLE contacts ADD COLUMN mail_importance_rule_importance TEXT")
            )
        if "mail_importance_rule_instruction" not in contact_columns:
            connection.execute(
                text("ALTER TABLE contacts ADD COLUMN mail_importance_rule_instruction TEXT")
            )
        if "inbound_message_count" not in contact_columns:
            connection.execute(
                text(
                    "ALTER TABLE contacts "
                    "ADD COLUMN inbound_message_count INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "latest_received_at" not in contact_columns:
            connection.execute(text("ALTER TABLE contacts ADD COLUMN latest_received_at TEXT"))
        if (
            "gmail_messages" in table_names
            and "contact_email_addresses" in table_names
            and (
                "inbound_message_count" not in contact_columns
                or "latest_received_at" not in contact_columns
            )
        ):
            if "gmail_messages" in table_names and "contact_email_addresses" in table_names:
                connection.execute(
                    text(
                        """
                        UPDATE contacts
                        SET
                            inbound_message_count = (
                                SELECT COUNT(DISTINCT gmail_messages.id)
                                FROM gmail_messages
                                JOIN contact_email_addresses
                                    ON contact_email_addresses.normalized_email_address
                                        IN (
                                            gmail_messages.from_address,
                                            gmail_messages.reply_to_address
                                        )
                                WHERE contact_email_addresses.contact_id = contacts.id
                                  AND contact_email_addresses.deleted_at IS NULL
                                  AND COALESCE(gmail_messages.gmail_labels_json, '')
                                      NOT LIKE '%"SENT"%'
                            ),
                            latest_received_at = (
                                SELECT MAX(gmail_messages.received_at)
                                FROM gmail_messages
                                JOIN contact_email_addresses
                                    ON contact_email_addresses.normalized_email_address
                                        IN (
                                            gmail_messages.from_address,
                                            gmail_messages.reply_to_address
                                        )
                                WHERE contact_email_addresses.contact_id = contacts.id
                                  AND contact_email_addresses.deleted_at IS NULL
                                  AND COALESCE(gmail_messages.gmail_labels_json, '')
                                      NOT LIKE '%"SENT"%'
                            )
                        """
                    )
                )
        if "mail_auto_state" in table_names and "llm_run_id" not in mail_auto_state_columns:
            connection.execute(text("ALTER TABLE mail_auto_state ADD COLUMN llm_run_id TEXT"))
        if "mail_auto_state" in table_names and "llm_blocked" not in mail_auto_state_columns:
            connection.execute(
                text(
                    "ALTER TABLE mail_auto_state "
                    "ADD COLUMN llm_blocked INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "mail_auto_state" in table_names and "llm_block_reason" not in mail_auto_state_columns:
            connection.execute(
                text("ALTER TABLE mail_auto_state ADD COLUMN llm_block_reason TEXT")
            )
        if "mail_auto_state" in table_names and "llm_blocked_at" not in mail_auto_state_columns:
            connection.execute(
                text("ALTER TABLE mail_auto_state ADD COLUMN llm_blocked_at TEXT")
            )
        if "mail_user_state" in table_names and "read_status" not in mail_user_state_columns:
            connection.execute(
                text(
                    "ALTER TABLE mail_user_state "
                    "ADD COLUMN read_status TEXT NOT NULL DEFAULT 'unread'"
                )
            )
        if "mail_user_state" in table_names and "read_at" not in mail_user_state_columns:
            connection.execute(text("ALTER TABLE mail_user_state ADD COLUMN read_at TEXT"))
        if "gmail_messages" in table_names and "mail_summaries" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE mail_summaries (
                        id TEXT PRIMARY KEY,
                        message_id TEXT NOT NULL UNIQUE REFERENCES gmail_messages(id),
                        summary_text TEXT NOT NULL,
                        action_required INTEGER,
                        deadline_text TEXT,
                        next_action TEXT,
                        key_points_json TEXT,
                        language TEXT NOT NULL DEFAULT 'ja',
                        llm_run_id TEXT REFERENCES llm_runs(id),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if "mail_summaries" in table_names and "translation_text" not in mail_summary_columns:
            connection.execute(
                text("ALTER TABLE mail_summaries ADD COLUMN translation_text TEXT")
            )
        if "gmail_messages" in table_names and "mail_send_requests" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE mail_send_requests (
                        id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        to_addresses_json TEXT NOT NULL,
                        cc_addresses_json TEXT,
                        bcc_addresses_json TEXT,
                        subject TEXT,
                        body_text TEXT NOT NULL,
                        attachment_names_json TEXT,
                        attachment_data_json TEXT,
                        reply_to_message_id TEXT REFERENCES gmail_messages(id),
                        sent_message_id TEXT REFERENCES gmail_messages(id),
                        scheduled_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if (
            "mail_send_requests" in table_names
            and "sent_message_id" not in mail_send_request_columns
        ):
            connection.execute(
                text(
                    "ALTER TABLE mail_send_requests "
                    "ADD COLUMN sent_message_id TEXT REFERENCES gmail_messages(id)"
                )
            )
        if (
            "mail_send_requests" in table_names
            and "attachment_data_json" not in mail_send_request_columns
        ):
            connection.execute(
                text("ALTER TABLE mail_send_requests ADD COLUMN attachment_data_json TEXT")
            )
        if "gmail_messages" in table_names and "mail_llm_block_filters" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE mail_llm_block_filters (
                        id TEXT PRIMARY KEY,
                        query_text TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        is_enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if "gmail_threads" in table_names and "mail_thread_summaries" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE mail_thread_summaries (
                        id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL UNIQUE REFERENCES gmail_threads(id),
                        summary_text TEXT NOT NULL,
                        action_required INTEGER,
                        next_action TEXT,
                        key_points_json TEXT,
                        translation_text TEXT,
                        language TEXT NOT NULL DEFAULT 'ja',
                        llm_run_id TEXT REFERENCES llm_runs(id),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if (
            "mail_thread_summaries" in table_names
            and "translation_text" not in mail_thread_summary_columns
        ):
            connection.execute(
                text("ALTER TABLE mail_thread_summaries ADD COLUMN translation_text TEXT")
            )
        if "storage_locations" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE storage_locations (
                        id TEXT PRIMARY KEY,
                        label TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'internal',
                        root_path TEXT NOT NULL,
                        mount_hint TEXT,
                        marker_id TEXT,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if "storage_objects" in table_names and "location_id" not in storage_object_columns:
            connection.execute(
                text(
                    "ALTER TABLE storage_objects "
                    "ADD COLUMN location_id TEXT NOT NULL "
                    "DEFAULT 'storage_location_internal'"
                )
            )
        if (
            "storage_objects" in table_names
            and "llm_input_allowed" not in storage_object_columns
        ):
            connection.execute(
                text(
                    "ALTER TABLE storage_objects "
                    "ADD COLUMN llm_input_allowed INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "storage_objects" in table_names and "source_type" not in storage_object_columns:
            connection.execute(text("ALTER TABLE storage_objects ADD COLUMN source_type TEXT"))
        if (
            "storage_objects" in table_names
            and "source_message_id" not in storage_object_columns
        ):
            connection.execute(
                text("ALTER TABLE storage_objects ADD COLUMN source_message_id TEXT")
            )
        if "storage_objects" in table_names and "file_summaries" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE file_summaries (
                        id TEXT PRIMARY KEY,
                        storage_object_id TEXT NOT NULL REFERENCES storage_objects(id),
                        storage_object_version_id TEXT REFERENCES storage_object_versions(id),
                        source_sha256_hex TEXT NOT NULL,
                        source_filename TEXT,
                        source_content_type TEXT,
                        source_byte_size INTEGER NOT NULL DEFAULT 0,
                        summary_type TEXT NOT NULL DEFAULT 'llm_digest',
                        file_description TEXT NOT NULL,
                        summary_points_json TEXT NOT NULL,
                        llm_digest TEXT NOT NULL,
                        structured_digest_json TEXT NOT NULL,
                        coverage_json TEXT NOT NULL,
                        token_estimate INTEGER,
                        llm_run_id TEXT REFERENCES llm_runs(id),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if "storage_objects" in table_names and "file_version_diffs" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE file_version_diffs (
                        id TEXT PRIMARY KEY,
                        storage_object_id TEXT NOT NULL REFERENCES storage_objects(id),
                        previous_version_id TEXT NOT NULL REFERENCES storage_object_versions(id),
                        previous_sha256_hex TEXT NOT NULL,
                        current_sha256_hex TEXT NOT NULL,
                        diff_kind TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        added_lines_json TEXT NOT NULL,
                        removed_lines_json TEXT NOT NULL,
                        coverage_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            )
        if "cases" in table_names and "case_context_versions" not in table_names:
            connection.execute(
                text(
                    """
                    CREATE TABLE case_context_versions (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL REFERENCES cases(id),
                        version_no INTEGER NOT NULL,
                        context_markdown TEXT NOT NULL,
                        source_event_until_at TEXT,
                        llm_run_id TEXT REFERENCES llm_runs(id),
                        created_at TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        UNIQUE(case_id, version_no)
                    )
                    """
                )
            )
        if "storage_objects" in table_names:
            connection.execute(
                text(
                    """
                    UPDATE storage_objects
                    SET source_type = 'direct_upload'
                    WHERE source_type IS NULL AND scope = 'managed'
                    """
                )
            )
            if "gmail_message_attachments" in table_names:
                connection.execute(
                    text(
                        """
                        UPDATE storage_objects
                        SET
                            source_type = 'mail_attachment',
                            source_message_id = (
                                SELECT gmail_message_attachments.message_id
                                FROM gmail_message_attachments
                                WHERE gmail_message_attachments.storage_object_id
                                    = storage_objects.id
                                LIMIT 1
                            )
                        WHERE id IN (
                            SELECT storage_object_id
                            FROM gmail_message_attachments
                            WHERE storage_object_id IS NOT NULL
                        )
                        """
                    )
                )


def seed_settings(session: Session) -> None:
    existing_keys = set(session.scalars(select(AppSetting.key)).all())
    for key, value_json in INITIAL_SETTINGS.items():
        if key in existing_keys:
            continue
        session.add(
            AppSetting(
                id=f"setting_{key}",
                key=key,
                value_json=value_json,
                updated_at=SEED_TIMESTAMP,
            )
        )


def seed_storage_locations(session: Session) -> None:
    existing = session.get(StorageLocation, "storage_location_internal")
    root_path = get_storage_root().as_posix()
    if existing is None:
        session.add(
            StorageLocation(
                id="storage_location_internal",
                label="Internal Storage",
                kind="internal",
                root_path=root_path,
                mount_hint=None,
                marker_id="caseclosed-internal-storage",
                status="active",
                created_at=SEED_TIMESTAMP,
                updated_at=SEED_TIMESTAMP,
                version=1,
            )
        )
        return
    if existing.root_path != root_path:
        existing.root_path = root_path
        existing.updated_at = jst_iso()
        existing.version += 1


def case_storage_directory_id(case_id: str) -> str:
    return f"storage_directory_case_{case_id}"


def case_handover_storage_directory_id(case_id: str) -> str:
    return f"storage_directory_case_{case_id}_handover"


def ensure_case_storage_directory(
    session: Session,
    case: Case,
    *,
    now: str | None = None,
) -> StorageDirectory:
    timestamp = now or jst_iso()
    directory = session.scalar(
        select(StorageDirectory)
        .where(StorageDirectory.directory_kind == "case")
        .where(StorageDirectory.case_id == case.id)
        .order_by(StorageDirectory.created_at.asc(), StorageDirectory.id.asc())
        .limit(1)
    )
    if directory is None:
        directory = StorageDirectory(
            id=case_storage_directory_id(case.id),
            parent_id=None,
            directory_kind="case",
            case_id=case.id,
            name=case.name,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        session.add(directory)
        ensure_case_handover_storage_directory(session, case, now=timestamp, case_directory=directory)
        return directory

    changed = False
    if directory.parent_id is not None:
        directory.parent_id = None
        changed = True
    if directory.name != case.name:
        directory.name = case.name
        changed = True
    if directory.status != "active":
        directory.status = "active"
        changed = True
    if changed:
        directory.updated_at = timestamp
        directory.version += 1
    ensure_case_handover_storage_directory(session, case, now=timestamp, case_directory=directory)
    return directory


def ensure_case_handover_storage_directory(
    session: Session,
    case: Case,
    *,
    now: str | None = None,
    case_directory: StorageDirectory | None = None,
) -> StorageDirectory:
    timestamp = now or jst_iso()
    parent = case_directory or session.get(StorageDirectory, case_storage_directory_id(case.id))
    if parent is None:
        parent = StorageDirectory(
            id=case_storage_directory_id(case.id),
            parent_id=None,
            directory_kind="case",
            case_id=case.id,
            name=case.name,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        session.add(parent)
    directory = session.get(StorageDirectory, case_handover_storage_directory_id(case.id))
    if directory is None:
        directory = StorageDirectory(
            id=case_handover_storage_directory_id(case.id),
            parent_id=parent.id,
            directory_kind="normal",
            case_id=case.id,
            name="引継ぎ資料",
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        session.add(directory)
        return directory

    changed = False
    if directory.parent_id != parent.id:
        directory.parent_id = parent.id
        changed = True
    if directory.directory_kind != "normal":
        directory.directory_kind = "normal"
        changed = True
    if directory.case_id != case.id:
        directory.case_id = case.id
        changed = True
    if directory.name != "引継ぎ資料":
        directory.name = "引継ぎ資料"
        changed = True
    if directory.status != "active":
        directory.status = "active"
        changed = True
    if changed:
        directory.updated_at = timestamp
        directory.version += 1
    return directory


def ensure_case_storage_directories(session: Session) -> None:
    cases = session.scalars(select(Case)).all()
    now = jst_iso()
    for case in cases:
        ensure_case_storage_directory(session, case, now=now)


def task_storage_directory_id(task_id: str) -> str:
    return f"storage_directory_task_{task_id}"


def completed_tasks_storage_directory_id(case_id: str) -> str:
    return f"storage_directory_case_{case_id}_completed_tasks"


def ensure_completed_tasks_storage_directory(
    session: Session,
    case: Case,
    *,
    now: str | None = None,
) -> StorageDirectory:
    timestamp = now or jst_iso()
    case_directory = ensure_case_storage_directory(session, case, now=timestamp)
    directory = session.get(StorageDirectory, completed_tasks_storage_directory_id(case.id))
    if directory is None:
        directory = StorageDirectory(
            id=completed_tasks_storage_directory_id(case.id),
            parent_id=case_directory.id,
            directory_kind="normal",
            case_id=case.id,
            name="Completed Tasks",
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        session.add(directory)
        return directory

    changed = False
    if directory.parent_id != case_directory.id:
        directory.parent_id = case_directory.id
        changed = True
    if directory.directory_kind != "normal":
        directory.directory_kind = "normal"
        changed = True
    if directory.case_id != case.id:
        directory.case_id = case.id
        changed = True
    if directory.name != "Completed Tasks":
        directory.name = "Completed Tasks"
        changed = True
    if directory.status != "active":
        directory.status = "active"
        changed = True
    if changed:
        directory.updated_at = timestamp
        directory.version += 1
    return directory


def ensure_task_storage_directory(
    session: Session,
    task: Task,
    *,
    now: str | None = None,
) -> StorageDirectory | None:
    case = session.get(Case, task.case_id)
    if case is None:
        return None

    timestamp = now or jst_iso()
    case_directory = ensure_case_storage_directory(session, case, now=timestamp)
    parent_directory = (
        ensure_completed_tasks_storage_directory(session, case, now=timestamp)
        if task.status == "completed"
        else case_directory
    )
    directory = (
        session.get(StorageDirectory, task.storage_directory_id)
        if task.storage_directory_id is not None
        else None
    )
    if directory is None:
        directory = session.get(StorageDirectory, task_storage_directory_id(task.id))

    if directory is None:
        directory = StorageDirectory(
            id=task_storage_directory_id(task.id),
            parent_id=parent_directory.id,
            directory_kind="task",
            case_id=case.id,
            name=task.title,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
            version=1,
        )
        session.add(directory)
        task.storage_directory_id = directory.id
        return directory

    changed = False
    if directory.parent_id != parent_directory.id:
        directory.parent_id = parent_directory.id
        changed = True
    if directory.directory_kind != "task":
        directory.directory_kind = "task"
        changed = True
    if directory.case_id != case.id:
        directory.case_id = case.id
        changed = True
    if directory.name != task.title:
        directory.name = task.title
        changed = True
    if directory.status != "active":
        directory.status = "active"
        changed = True
    if task.storage_directory_id != directory.id:
        task.storage_directory_id = directory.id
        changed = True
    if changed:
        directory.updated_at = timestamp
        directory.version += 1
    return directory


def ensure_task_storage_directories(session: Session) -> None:
    tasks = session.scalars(select(Task).where(Task.deleted_at.is_(None))).all()
    now = jst_iso()
    for task in tasks:
        ensure_task_storage_directory(session, task, now=now)


def seed_system_cases(session: Session) -> None:
    existing_keys = set(
        session.scalars(
            select(Case.system_case_key).where(Case.system_case_key.is_not(None))
        ).all()
    )
    seeds = (
        ("case_system_inbox", "Bucket", "inbox"),
    )
    for case_id, name, key in seeds:
        if key in existing_keys:
            existing_case = session.get(Case, case_id)
            if existing_case is not None and existing_case.name != name:
                existing_case.name = name
                existing_case.updated_at = jst_iso()
                existing_case.version += 1
            continue
        session.add(
            Case(
                id=case_id,
                name=name,
                progress_status="not_started",
                ball_status="none",
                is_system_case=1,
                system_case_key=key,
                created_at=SEED_TIMESTAMP,
                updated_at=SEED_TIMESTAMP,
                version=1,
            )
        )


def normalize_llm_blocked_mail_importance(session: Session) -> None:
    blocked_states = session.scalars(
        select(MailAutoState).where(
            MailAutoState.llm_blocked == 1,
            MailAutoState.pending_reason.is_(None),
            MailAutoState.effective_importance != "pinned",
        )
    ).all()
    now = jst_iso()
    for auto_state in blocked_states:
        auto_state.effective_importance = "pinned"
        auto_state.updated_at = now
        auto_state.version += 1


def normalize_llm_skip_mail_importance(session: Session) -> None:
    skipped_states = session.scalars(
        select(MailAutoState).where(
            MailAutoState.llm_blocked == 0,
            MailAutoState.suggested_importance == "skip",
            MailAutoState.effective_importance == "pinned",
        )
    ).all()
    now = jst_iso()
    for auto_state in skipped_states:
        auto_state.effective_importance = "skip"
        auto_state.updated_at = now
        auto_state.version += 1


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
