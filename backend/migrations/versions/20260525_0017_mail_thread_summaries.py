"""Add mail thread summaries.

Revision ID: 20260525_0017
Revises: 20260525_0016
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0017"
down_revision = "20260525_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_thread_summaries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("gmail_threads.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("action_required", sa.Integer(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("translation_text", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False, server_default="ja"),
        sa.Column("llm_run_id", sa.Text(), sa.ForeignKey("llm_runs.id"), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mail_thread_summaries")
