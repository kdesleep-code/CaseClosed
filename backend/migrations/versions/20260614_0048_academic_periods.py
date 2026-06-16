"""Add academic period table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0048"
down_revision = "20260614_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_periods",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "academic_year_id",
            sa.Text(),
            sa.ForeignKey("academic_years.id"),
            nullable=False,
        ),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("ends_at", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "academic_year_id",
            "period_no",
            name="uq_academic_periods_year_period_no",
        ),
    )
    op.create_index(
        "ix_academic_periods_year_order",
        "academic_periods",
        ["academic_year_id", "sort_order", "period_no"],
    )


def downgrade() -> None:
    op.drop_index("ix_academic_periods_year_order", table_name="academic_periods")
    op.drop_table("academic_periods")
