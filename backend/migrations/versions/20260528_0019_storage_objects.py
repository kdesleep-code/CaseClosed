"""Add storage objects.

Revision ID: 20260528_0019
Revises: 20260525_0018
Create Date: 2026-05-28 16:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260528_0019"
down_revision = "20260525_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("storage_objects")
