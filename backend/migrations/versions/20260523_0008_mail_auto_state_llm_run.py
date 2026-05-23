"""Link mail auto state to LLM runs.

Revision ID: 20260523_0008
Revises: 20260523_0007
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0008"
down_revision = "20260523_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_auto_state",
        sa.Column("llm_run_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mail_auto_state", "llm_run_id")
