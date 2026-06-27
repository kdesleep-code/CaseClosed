"""Add paper user summaries."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_0056"
down_revision = "20260626_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("summary", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("papers", "summary")
