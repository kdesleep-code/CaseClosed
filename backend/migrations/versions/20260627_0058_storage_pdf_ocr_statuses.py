"""Add PDF OCR status tracking."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260627_0058"
down_revision = "20260626_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_pdf_ocr_statuses",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("storage_object_id", sa.Text(), sa.ForeignKey("storage_objects.id"), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("text_quality", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("page_count", sa.Integer()),
        sa.Column("native_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ocr_engine", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("details_json", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("storage_pdf_ocr_statuses")
