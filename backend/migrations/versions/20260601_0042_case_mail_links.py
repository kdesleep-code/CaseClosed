"""Add case mail links."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260601_0042"
down_revision = "20260601_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_mail_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("message_id", sa.Text(), sa.ForeignKey("gmail_messages.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("case_mail_links")
