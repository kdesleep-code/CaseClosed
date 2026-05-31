"""Add case tool links."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0038"
down_revision = "20260531_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_tool_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("icon_label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("case_tool_links")
