"""Add file icon settings."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0039"
down_revision = "20260531_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_icon_settings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("icon_filename", sa.Text(), nullable=True),
        sa.Column("icon_content_type", sa.Text(), nullable=False),
        sa.Column("icon_data_url", sa.Text(), nullable=False),
        sa.Column("extensions_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("file_icon_settings")
