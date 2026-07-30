"""Add indexes used by Storage list queries."""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "20260730_0063"
down_revision = "20260730_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table_names = set(inspect(op.get_bind()).get_table_names())
    if "storage_objects" in table_names:
        op.create_index(
            "ix_storage_objects_list_directory",
            "storage_objects",
            ["scope", "status", "directory_id", "created_at"],
        )
    if "storage_directories" in table_names:
        op.create_index(
            "ix_storage_directories_children",
            "storage_directories",
            ["parent_id", "status", "directory_kind", "name"],
        )


def downgrade() -> None:
    table_names = set(inspect(op.get_bind()).get_table_names())
    if "storage_directories" in table_names:
        op.drop_index(
            "ix_storage_directories_children",
            table_name="storage_directories",
        )
    if "storage_objects" in table_names:
        op.drop_index(
            "ix_storage_objects_list_directory",
            table_name="storage_objects",
        )
