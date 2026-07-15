"""Add future importance rule to mail threads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0059"
down_revision = "20260627_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gmail_threads",
        sa.Column("future_importance_rule", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gmail_threads", "future_importance_rule")
