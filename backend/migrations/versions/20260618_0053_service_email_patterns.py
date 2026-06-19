"""Add service email matching patterns."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260618_0053"
down_revision = "20260616_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("service_email_patterns", sa.Text()))


def downgrade() -> None:
    op.drop_column("contacts", "service_email_patterns")
