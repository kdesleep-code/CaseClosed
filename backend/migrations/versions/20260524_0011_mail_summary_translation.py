"""Add optional mail summary translation text.

Revision ID: 20260524_0011
Revises: 20260524_0010
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0011"
down_revision = "20260524_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mail_summaries",
        sa.Column("translation_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mail_summaries", "translation_text")
