"""Rename the inbox system case to bucket."""

from __future__ import annotations

from alembic import op


revision = "20260531_0035"
down_revision = "20260531_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE cases SET name = 'Bucket' "
        "WHERE id = 'case_system_inbox' AND system_case_key = 'inbox'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE cases SET name = 'Inbox / なんでも箱' "
        "WHERE id = 'case_system_inbox' AND system_case_key = 'inbox'"
    )
