"""Make academic periods global."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260614_0049"
down_revision = "20260614_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_periods_global",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("period_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("ends_at", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("period_no", name="uq_academic_periods_period_no"),
    )
    op.execute(
        """
        INSERT INTO academic_periods_global (
            id,
            period_no,
            label,
            starts_at,
            ends_at,
            sort_order,
            note,
            created_at,
            updated_at,
            version
        )
        SELECT
            id,
            period_no,
            label,
            starts_at,
            ends_at,
            sort_order,
            note,
            created_at,
            updated_at,
            version
        FROM academic_periods
        WHERE rowid IN (
            SELECT MIN(rowid)
            FROM academic_periods
            GROUP BY period_no
        )
        """
    )
    op.drop_index("ix_academic_periods_year_order", table_name="academic_periods")
    op.drop_table("academic_periods")
    op.rename_table("academic_periods_global", "academic_periods")
    op.create_index(
        "ix_academic_periods_order",
        "academic_periods",
        ["sort_order", "period_no"],
    )


def downgrade() -> None:
    op.create_table(
        "academic_periods_year_scoped",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("academic_year_id", sa.Text(), sa.ForeignKey("academic_years.id"), nullable=False),
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
    op.execute(
        """
        INSERT INTO academic_periods_year_scoped (
            id,
            academic_year_id,
            period_no,
            label,
            starts_at,
            ends_at,
            sort_order,
            note,
            created_at,
            updated_at,
            version
        )
        SELECT
            'academic_period_' || lower(hex(randomblob(16))),
            academic_years.id,
            academic_periods.period_no,
            academic_periods.label,
            academic_periods.starts_at,
            academic_periods.ends_at,
            academic_periods.sort_order,
            academic_periods.note,
            academic_periods.created_at,
            academic_periods.updated_at,
            academic_periods.version
        FROM academic_periods
        CROSS JOIN academic_years
        """
    )
    op.drop_index("ix_academic_periods_order", table_name="academic_periods")
    op.drop_table("academic_periods")
    op.rename_table("academic_periods_year_scoped", "academic_periods")
    op.create_index(
        "ix_academic_periods_year_order",
        "academic_periods",
        ["academic_year_id", "sort_order", "period_no"],
    )
