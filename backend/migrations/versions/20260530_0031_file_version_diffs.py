"""Add file version diffs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0031"
down_revision = "20260530_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_version_diffs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "storage_object_id",
            sa.Text(),
            sa.ForeignKey("storage_objects.id"),
            nullable=False,
        ),
        sa.Column(
            "previous_version_id",
            sa.Text(),
            sa.ForeignKey("storage_object_versions.id"),
            nullable=False,
        ),
        sa.Column("previous_sha256_hex", sa.Text(), nullable=False),
        sa.Column("current_sha256_hex", sa.Text(), nullable=False),
        sa.Column("diff_kind", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("added_lines_json", sa.Text(), nullable=False),
        sa.Column("removed_lines_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_file_version_diffs_storage_object",
        "file_version_diffs",
        ["storage_object_id", "previous_version_id", "current_sha256_hex"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_file_version_diffs_storage_object", table_name="file_version_diffs")
    op.drop_table("file_version_diffs")
