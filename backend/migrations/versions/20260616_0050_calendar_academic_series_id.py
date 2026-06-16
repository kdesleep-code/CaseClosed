"""Add academic series id to calendar events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260616_0050"
down_revision = "20260614_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("academic_series_id", sa.Text()))


def downgrade() -> None:
    op.drop_column("calendar_events", "academic_series_id")
