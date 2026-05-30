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
from caseclosed.db.models import StorageLocation
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
        seed_storage_locations(session)
        normalize_llm_blocked_mail_importance(session)
        normalize_llm_skip_mail_importance(session)
        session.commit()


def ensure_runtime_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
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


def seed_system_cases(session: Session) -> None:
    existing_keys = set(
        session.scalars(
            select(Case.system_case_key).where(Case.system_case_key.is_not(None))
        ).all()
    )
    seeds = (
        ("case_system_inbox", "Inbox / なんでも箱", "inbox"),
        (
            "case_system_maintenance",
            "システムメンテナンス",
            "system_maintenance",
        ),
    )
    for case_id, name, key in seeds:
        if key in existing_keys:
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
