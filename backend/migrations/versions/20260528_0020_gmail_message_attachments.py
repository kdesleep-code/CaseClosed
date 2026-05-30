"""Add Gmail message attachment metadata.

Revision ID: 20260528_0020
Revises: 20260528_0019
Create Date: 2026-05-28 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260528_0020"
down_revision = "20260528_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_message_attachments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("gmail_message_id", sa.Text(), nullable=False),
        sa.Column("gmail_attachment_id", sa.Text(), nullable=False),
        sa.Column("part_id", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_object_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["message_id"], ["gmail_messages.id"]),
        sa.ForeignKeyConstraint(["storage_object_id"], ["storage_objects.id"]),
    )
    op.create_index(
        "ix_gmail_message_attachments_message_id",
        "gmail_message_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_gmail_message_attachments_gmail_message_id",
        "gmail_message_attachments",
        ["gmail_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gmail_message_attachments_gmail_message_id",
        table_name="gmail_message_attachments",
    )
    op.drop_index(
        "ix_gmail_message_attachments_message_id",
        table_name="gmail_message_attachments",
    )
    op.drop_table("gmail_message_attachments")
