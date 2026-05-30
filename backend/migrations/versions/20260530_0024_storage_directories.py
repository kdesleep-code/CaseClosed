"""Add storage directories."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0024"
down_revision = "20260529_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_directories",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("directory_kind", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["parent_id"], ["storage_directories.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
    )
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.add_column(sa.Column("directory_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_storage_objects_directory_id_storage_directories",
            "storage_directories",
            ["directory_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.drop_constraint(
            "fk_storage_objects_directory_id_storage_directories",
            type_="foreignkey",
        )
        batch_op.drop_column("directory_id")
    op.drop_table("storage_directories")
