"""Add per-mail LLM block flags.

Revision ID: 20260525_0015
Revises: 20260525_0014
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0015"
down_revision = "20260525_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_auto_state",
        sa.Column("llm_blocked", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("mail_auto_state", sa.Column("llm_block_reason", sa.Text()))
    op.add_column("mail_auto_state", sa.Column("llm_blocked_at", sa.Text()))


def downgrade() -> None:
    op.drop_column("mail_auto_state", "llm_blocked_at")
    op.drop_column("mail_auto_state", "llm_block_reason")
    op.drop_column("mail_auto_state", "llm_blocked")
