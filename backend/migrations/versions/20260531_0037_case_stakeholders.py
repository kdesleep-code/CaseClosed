"""Add Case stakeholders.

Revision ID: 20260531_0037
Revises: 20260531_0036
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260531_0037"
down_revision = "20260531_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_stakeholders",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("contact_id", sa.Text(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="stakeholder"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("case_stakeholders")
