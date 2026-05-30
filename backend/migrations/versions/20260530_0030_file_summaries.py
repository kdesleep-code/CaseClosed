"""Add file summaries for LLM digest preparation."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0030"
down_revision = "20260530_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_summaries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "storage_object_id",
            sa.Text(),
            sa.ForeignKey("storage_objects.id"),
            nullable=False,
        ),
        sa.Column(
            "storage_object_version_id",
            sa.Text(),
            sa.ForeignKey("storage_object_versions.id"),
            nullable=True,
        ),
        sa.Column("source_sha256_hex", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("source_content_type", sa.Text(), nullable=True),
        sa.Column("source_byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_type", sa.Text(), nullable=False, server_default="llm_digest"),
        sa.Column("file_description", sa.Text(), nullable=False),
        sa.Column("summary_points_json", sa.Text(), nullable=False),
        sa.Column("llm_digest", sa.Text(), nullable=False),
        sa.Column("structured_digest_json", sa.Text(), nullable=False),
        sa.Column("coverage_json", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=True),
        sa.Column("llm_run_id", sa.Text(), sa.ForeignKey("llm_runs.id"), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_file_summaries_storage_object",
        "file_summaries",
        ["storage_object_id", "storage_object_version_id", "source_sha256_hex"],
    )


def downgrade() -> None:
    op.drop_index("ix_file_summaries_storage_object", table_name="file_summaries")
    op.drop_table("file_summaries")
