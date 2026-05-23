"""Add status columns to contact email addresses.

Revision ID: 20260523_0004
Revises: 20260523_0003
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0004"
down_revision = "20260523_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact_email_addresses",
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    )
    op.add_column(
        "contact_email_addresses",
        sa.Column(
            "has_inbound_message_history",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "contact_email_addresses",
        sa.Column("deactivated_at", sa.Text(), nullable=True),
    )
    op.add_column(
        "contact_email_addresses",
        sa.Column("deleted_at", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_contact_email_addresses_status",
        "contact_email_addresses",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_contact_email_addresses_status", table_name="contact_email_addresses")
    op.drop_column("contact_email_addresses", "deleted_at")
    op.drop_column("contact_email_addresses", "deactivated_at")
    op.drop_column("contact_email_addresses", "has_inbound_message_history")
    op.drop_column("contact_email_addresses", "status")
