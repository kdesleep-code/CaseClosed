"""Store mail send attachment payloads.

Revision ID: 20260525_0018
Revises: 20260525_0017
Create Date: 2026-05-25 00:18:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_0018"
down_revision = "20260525_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_send_requests",
        sa.Column("attachment_data_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mail_send_requests", "attachment_data_json")
