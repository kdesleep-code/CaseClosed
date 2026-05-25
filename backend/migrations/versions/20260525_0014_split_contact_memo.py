"""Split contact memo into user and AI memo.

Revision ID: 20260525_0014
Revises: 20260525_0013
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0014"
down_revision = "20260525_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("user_memo", sa.Text(), nullable=True))
    op.add_column("contacts", sa.Column("ai_memo", sa.Text(), nullable=True))
    op.execute("UPDATE contacts SET user_memo = memo WHERE user_memo IS NULL")


def downgrade() -> None:
    op.execute("UPDATE contacts SET memo = user_memo WHERE user_memo IS NOT NULL")
    op.drop_column("contacts", "ai_memo")
    op.drop_column("contacts", "user_memo")
