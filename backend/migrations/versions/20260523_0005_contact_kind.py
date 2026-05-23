"""Add contact kind and sender resolution mode.

Revision ID: 20260523_0005
Revises: 20260523_0004
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0005"
down_revision = "20260523_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("kind", sa.Text(), nullable=False, server_default="person"),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "sender_resolution_mode",
            sa.Text(),
            nullable=False,
            server_default="self",
        ),
    )
    op.create_index("ix_contacts_kind", "contacts", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_contacts_kind", table_name="contacts")
    op.drop_column("contacts", "sender_resolution_mode")
    op.drop_column("contacts", "kind")
