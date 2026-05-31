"""Add case genres."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0033"
down_revision = "20260530_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_genres",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, unique=True),
        sa.Column("color_hex", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("cases", sa.Column("genre_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "genre_id")
    op.drop_table("case_genres")
