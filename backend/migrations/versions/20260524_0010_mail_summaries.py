"""Add mail summary persistence.

Revision ID: 20260524_0010
Revises: 20260524_0009
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0010"
down_revision = "20260524_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_summaries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Text(),
            sa.ForeignKey("gmail_messages.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("action_required", sa.Integer(), nullable=True),
        sa.Column("deadline_text", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False, server_default="ja"),
        sa.Column("llm_run_id", sa.Text(), sa.ForeignKey("llm_runs.id"), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mail_summaries")
