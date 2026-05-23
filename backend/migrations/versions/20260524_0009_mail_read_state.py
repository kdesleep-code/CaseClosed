"""Add app read state to mail user state.

Revision ID: 20260524_0009
Revises: 20260523_0008
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0009"
down_revision = "20260523_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_user_state",
        sa.Column(
            "read_status",
            sa.Text(),
            nullable=False,
            server_default="unread",
        ),
    )
    op.add_column(
        "mail_user_state",
        sa.Column("read_at", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mail_user_state", "read_at")
    op.drop_column("mail_user_state", "read_status")
