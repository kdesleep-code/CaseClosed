"""Add persistent mail LLM block filters.

Revision ID: 20260525_0016
Revises: 20260525_0015
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0016"
down_revision = "20260525_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_llm_block_filters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("mail_llm_block_filters")
