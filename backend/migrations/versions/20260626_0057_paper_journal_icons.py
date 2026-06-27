"""Add paper journal icon settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_0057"
down_revision = "20260626_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_journal_icon_settings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("match_journal", sa.Text(), nullable=False),
        sa.Column("icon_filename", sa.Text()),
        sa.Column("icon_content_type", sa.Text(), nullable=False),
        sa.Column("icon_data_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("paper_journal_icon_settings")
