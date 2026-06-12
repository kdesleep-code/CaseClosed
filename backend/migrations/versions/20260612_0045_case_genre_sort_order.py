"""Add sort order to case genres."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260612_0045"
down_revision = "20260610_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "case_genres",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("case_genres", "sort_order")
