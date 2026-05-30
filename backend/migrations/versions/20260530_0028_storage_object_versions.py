"""Add storage object versions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0028"
down_revision = "20260530_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_object_versions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("storage_object_id", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["storage_object_id"], ["storage_objects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
    )
    op.create_index(
        "ix_storage_object_versions_object_id",
        "storage_object_versions",
        ["storage_object_id"],
    )
    op.create_index(
        "ix_storage_object_versions_object_version",
        "storage_object_versions",
        ["storage_object_id", "version_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storage_object_versions_object_version",
        table_name="storage_object_versions",
    )
    op.drop_index(
        "ix_storage_object_versions_object_id",
        table_name="storage_object_versions",
    )
    op.drop_table("storage_object_versions")
