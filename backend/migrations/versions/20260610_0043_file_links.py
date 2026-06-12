"""Add file links table to the Alembic chain."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260610_0043"
down_revision = "20260601_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    table_names = set(sa.inspect(bind).get_table_names())
    if "file_links" in table_names:
        return
    op.create_table(
        "file_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "storage_object_id",
            sa.Text(),
            sa.ForeignKey("storage_objects.id"),
            nullable=False,
        ),
        sa.Column("linked_type", sa.Text(), nullable=False),
        sa.Column("linked_id", sa.Text(), nullable=False),
        sa.Column("directory_id", sa.Text()),
        sa.Column("label", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_table("file_links")
