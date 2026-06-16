"""Add academic calendar tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0046"
down_revision = "20260612_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_years",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("year_label", sa.Text(), nullable=False, unique=True),
        sa.Column("starts_on", sa.Text(), nullable=False),
        sa.Column("ends_on", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "academic_calendar_days",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "academic_year_id",
            sa.Text(),
            sa.ForeignKey("academic_years.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("day_type", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("is_teaching_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("effective_weekday", sa.Integer()),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "academic_year_id",
            "date",
            name="uq_academic_calendar_days_year_date",
        ),
    )
    op.create_index(
        "ix_academic_calendar_days_date",
        "academic_calendar_days",
        ["date"],
    )
    op.create_index(
        "ix_academic_calendar_days_year_date",
        "academic_calendar_days",
        ["academic_year_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_academic_calendar_days_year_date", table_name="academic_calendar_days")
    op.drop_index("ix_academic_calendar_days_date", table_name="academic_calendar_days")
    op.drop_table("academic_calendar_days")
    op.drop_table("academic_years")
