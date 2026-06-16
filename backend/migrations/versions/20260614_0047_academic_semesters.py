"""Add academic semester table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0047"
down_revision = "20260614_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_semesters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "academic_year_id",
            sa.Text(),
            sa.ForeignKey("academic_years.id"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.Text(), nullable=False),
        sa.Column("ends_on", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "academic_year_id",
            "label",
            name="uq_academic_semesters_year_label",
        ),
    )
    op.create_index(
        "ix_academic_semesters_year_dates",
        "academic_semesters",
        ["academic_year_id", "starts_on", "ends_on"],
    )


def downgrade() -> None:
    op.drop_index("ix_academic_semesters_year_dates", table_name="academic_semesters")
    op.drop_table("academic_semesters")
