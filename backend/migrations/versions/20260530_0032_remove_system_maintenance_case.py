"""Remove the seeded system maintenance case."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0032"
down_revision = "20260530_0031"
branch_labels = None
depends_on = None

SEED_TIMESTAMP = "2026-05-22T00:00:00+09:00"


def upgrade() -> None:
    op.execute(
        "DELETE FROM case_events "
        "WHERE case_id IN (SELECT id FROM cases WHERE system_case_key = 'system_maintenance')"
    )
    op.execute(
        "UPDATE audit_logs SET case_id = NULL "
        "WHERE case_id IN (SELECT id FROM cases WHERE system_case_key = 'system_maintenance')"
    )
    op.execute(
        "UPDATE storage_directories SET case_id = NULL "
        "WHERE case_id IN (SELECT id FROM cases WHERE system_case_key = 'system_maintenance')"
    )
    op.execute("DELETE FROM cases WHERE system_case_key = 'system_maintenance'")


def downgrade() -> None:
    cases_table = sa.table(
        "cases",
        sa.column("id", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("progress_status", sa.Text()),
        sa.column("ball_status", sa.Text()),
        sa.column("is_system_case", sa.Integer()),
        sa.column("system_case_key", sa.Text()),
        sa.column("created_at", sa.Text()),
        sa.column("updated_at", sa.Text()),
        sa.column("version", sa.Integer()),
    )
    op.bulk_insert(
        cases_table,
        [
            {
                "id": "case_system_maintenance",
                "name": "システムメンテナンス",
                "progress_status": "not_started",
                "ball_status": "none",
                "is_system_case": 1,
                "system_case_key": "system_maintenance",
                "created_at": SEED_TIMESTAMP,
                "updated_at": SEED_TIMESTAMP,
                "version": 1,
            }
        ],
    )
