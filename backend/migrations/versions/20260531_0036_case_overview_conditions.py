"""Add Case overview condition text fields.

Revision ID: 20260531_0036
Revises: 20260531_0035
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0036"
down_revision = "20260531_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("open_when_text", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("closed_when_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "closed_when_text")
    op.drop_column("cases", "open_when_text")
