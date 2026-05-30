"""Add storage operation history."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0027"
down_revision = "20260530_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_operation_history",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("storage_object_id", sa.Text(), nullable=True),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False, server_default="system"),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_message_id", sa.Text(), nullable=True),
        sa.Column("directory_id", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_operation_history_created_at",
        "storage_operation_history",
        ["created_at"],
    )
    op.create_index(
        "ix_storage_operation_history_storage_object_id",
        "storage_operation_history",
        ["storage_object_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storage_operation_history_storage_object_id",
        table_name="storage_operation_history",
    )
    op.drop_index(
        "ix_storage_operation_history_created_at",
        table_name="storage_operation_history",
    )
    op.drop_table("storage_operation_history")
