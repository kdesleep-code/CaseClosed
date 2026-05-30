"""Add storage locations.

Revision ID: 20260529_0021
Revises: 20260528_0020
Create Date: 2026-05-29 17:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260529_0021"
down_revision = "20260528_0020"
branch_labels = None
depends_on = None

INTERNAL_LOCATION_ID = "storage_location_internal"


def upgrade() -> None:
    op.create_table(
        "storage_locations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="internal"),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("mount_hint", sa.Text(), nullable=True),
        sa.Column("marker_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        """
        INSERT INTO storage_locations (
            id, label, kind, root_path, mount_hint, marker_id,
            status, created_at, updated_at, version
        )
        VALUES (
            'storage_location_internal', 'Internal Storage', 'internal',
            './data/storage', NULL, 'caseclosed-internal-storage',
            'active', '2026-05-22T00:00:00+09:00',
            '2026-05-22T00:00:00+09:00', 1
        )
        """
    )
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "location_id",
                sa.Text(),
                nullable=False,
                server_default=INTERNAL_LOCATION_ID,
            )
        )
        batch_op.create_foreign_key(
            "fk_storage_objects_location_id_storage_locations",
            "storage_locations",
            ["location_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.drop_constraint(
            "fk_storage_objects_location_id_storage_locations",
            type_="foreignkey",
        )
        batch_op.drop_column("location_id")
    op.drop_table("storage_locations")
