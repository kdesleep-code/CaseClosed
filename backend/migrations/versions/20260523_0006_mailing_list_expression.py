"""Add mailing list recipient expression.

Revision ID: 20260523_0006
Revises: 20260523_0005
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0006"
down_revision = "20260523_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("mailing_list_recipient_expression", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "mailing_list_recipient_expression")
