"""Create the Phase 1 foundation tables and seed data.

Revision ID: 20260522_0001
Revises:
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260522_0001"
down_revision = None
branch_labels = None
depends_on = None

SEED_TIMESTAMP = "2026-05-22T00:00:00+09:00"


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "cases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("open_when_text", sa.Text(), nullable=True),
        sa.Column("closed_when_text", sa.Text(), nullable=True),
        sa.Column(
            "progress_status",
            sa.Text(),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column("ball_status", sa.Text(), nullable=False, server_default="none"),
        sa.Column("closed_at", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.Text(), nullable=True),
        sa.Column("is_system_case", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("system_case_key", sa.Text(), nullable=True, unique=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "case_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "client_certificates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("device_name", sa.Text(), nullable=False),
        sa.Column("certificate_fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("issued_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "client_certificate_id",
            sa.Text(),
            sa.ForeignKey("client_certificates.id"),
            nullable=True,
        ),
        sa.Column("session_token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("login_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("logout_at", sa.Text(), nullable=True),
        sa.Column("locked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("session_id", sa.Text(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "system_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("client_fingerprint", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempted_at", sa.Text(), nullable=False),
    )

    settings_table = sa.table(
        "app_settings",
        sa.column("id", sa.Text()),
        sa.column("key", sa.Text()),
        sa.column("value_json", sa.Text()),
        sa.column("updated_at", sa.Text()),
    )
    op.bulk_insert(
        settings_table,
        [
            {
                "id": "setting_default_follow_up_days",
                "key": "default_follow_up_days",
                "value_json": "7",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_session_lifetime_hours",
                "key": "session_lifetime_hours",
                "value_json": "24",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_login_failure_limit",
                "key": "login_failure_limit",
                "value_json": "5",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_llm_cost_limit_daily",
                "key": "llm_cost_limit_daily",
                "value_json": "null",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_llm_cost_limit_monthly",
                "key": "llm_cost_limit_monthly",
                "value_json": "null",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_worker_min_count",
                "key": "worker_min_count",
                "value_json": "1",
                "updated_at": SEED_TIMESTAMP,
            },
            {
                "id": "setting_worker_max_count",
                "key": "worker_max_count",
                "value_json": "4",
                "updated_at": SEED_TIMESTAMP,
            },
        ],
    )

    cases_table = sa.table(
        "cases",
        sa.column("id", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("progress_status", sa.Text()),
        sa.column("ball_status", sa.Text()),
        sa.column("is_system_case", sa.Integer()),
        sa.column("system_case_key", sa.Text()),
        sa.column("created_at", sa.Text()),
        sa.column("updated_at", sa.Text()),
        sa.column("version", sa.Integer()),
    )
    op.bulk_insert(
        cases_table,
        [
            {
                "id": "case_system_inbox",
                "name": "Bucket",
                "progress_status": "not_started",
                "ball_status": "none",
                "is_system_case": 1,
                "system_case_key": "inbox",
                "created_at": SEED_TIMESTAMP,
                "updated_at": SEED_TIMESTAMP,
                "version": 1,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("auth_login_attempts")
    op.drop_table("system_logs")
    op.drop_table("audit_logs")
    op.drop_table("sessions")
    op.drop_table("client_certificates")
    op.drop_table("case_events")
    op.drop_table("cases")
    op.drop_table("app_settings")
