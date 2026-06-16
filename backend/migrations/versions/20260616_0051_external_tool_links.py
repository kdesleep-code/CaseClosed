"""Add external tool links."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260616_0051"
down_revision = "20260616_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_tool_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("external_tool_links")
