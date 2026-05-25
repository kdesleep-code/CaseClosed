"""Add mock mail send requests.

Revision ID: 20260525_0013
Revises: 20260524_0012
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0013"
down_revision = "20260524_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_send_requests",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("to_addresses_json", sa.Text(), nullable=False),
        sa.Column("cc_addresses_json", sa.Text(), nullable=True),
        sa.Column("bcc_addresses_json", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("attachment_names_json", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", sa.Text(), sa.ForeignKey("gmail_messages.id")),
        sa.Column("sent_message_id", sa.Text(), sa.ForeignKey("gmail_messages.id")),
        sa.Column("scheduled_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mail_send_requests")
