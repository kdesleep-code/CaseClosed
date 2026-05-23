"""Add Phase 4 mail foundation tables.

Revision ID: 20260523_0007
Revises: 20260523_0006
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0007"
down_revision = "20260523_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_threads",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("gmail_thread_id", sa.Text(), nullable=False, unique=True),
        sa.Column("subject_snapshot", sa.Text(), nullable=True),
        sa.Column("first_message_at", sa.Text(), nullable=True),
        sa.Column("last_message_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "gmail_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("gmail_message_id", sa.Text(), nullable=False, unique=True),
        sa.Column("gmail_thread_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), sa.ForeignKey("gmail_threads.id"), nullable=False),
        sa.Column("internal_date", sa.Text(), nullable=True),
        sa.Column("received_at", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("from_name", sa.Text(), nullable=True),
        sa.Column("sender_address", sa.Text(), nullable=True),
        sa.Column("reply_to_address", sa.Text(), nullable=True),
        sa.Column("to_addresses_json", sa.Text(), nullable=True),
        sa.Column("cc_addresses_json", sa.Text(), nullable=True),
        sa.Column("bcc_addresses_json", sa.Text(), nullable=True),
        sa.Column("message_id_header", sa.Text(), nullable=True),
        sa.Column("in_reply_to_header", sa.Text(), nullable=True),
        sa.Column("references_header", sa.Text(), nullable=True),
        sa.Column("list_id", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("gmail_link", sa.Text(), nullable=True),
        sa.Column("gmail_labels_json", sa.Text(), nullable=True),
        sa.Column("external_starred", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "mail_user_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Text(),
            sa.ForeignKey("gmail_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("user_importance", sa.Text(), nullable=True),
        sa.Column(
            "processed_status",
            sa.Text(),
            nullable=False,
            server_default="unprocessed",
        ),
        sa.Column("processed_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "mail_auto_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Text(),
            sa.ForeignKey("gmail_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("external_importance", sa.Text(), nullable=True),
        sa.Column("suggested_importance", sa.Text(), nullable=True),
        sa.Column("effective_importance", sa.Text(), nullable=False),
        sa.Column("pending_reason", sa.Text(), nullable=True),
        sa.Column(
            "pending_from_address_id",
            sa.Text(),
            sa.ForeignKey("contact_email_addresses.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mail_auto_state")
    op.drop_table("mail_user_state")
    op.drop_table("gmail_messages")
    op.drop_table("gmail_threads")
