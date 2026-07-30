"""Add indexes used by Task and Calendar list queries."""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "20260730_0062"
down_revision = "20260729_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table_names = set(inspect(op.get_bind()).get_table_names())
    if "tasks" in table_names:
        op.create_index(
            "ix_tasks_list_status_due",
            "tasks",
            ["deleted_at", "status", "due_at", "updated_at"],
        )
        op.create_index(
            "ix_tasks_case_id",
            "tasks",
            ["case_id"],
        )
    if "calendar_events" in table_names:
        op.create_index(
            "ix_calendar_events_source_range",
            "calendar_events",
            ["external_calendar_id", "start_at", "end_at"],
        )


def downgrade() -> None:
    table_names = set(inspect(op.get_bind()).get_table_names())
    if "calendar_events" in table_names:
        op.drop_index(
            "ix_calendar_events_source_range",
            table_name="calendar_events",
        )
    if "tasks" in table_names:
        op.drop_index("ix_tasks_case_id", table_name="tasks")
        op.drop_index("ix_tasks_list_status_due", table_name="tasks")
