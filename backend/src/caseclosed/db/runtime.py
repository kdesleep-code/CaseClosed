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
from caseclosed.settings import get_database_url

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


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
