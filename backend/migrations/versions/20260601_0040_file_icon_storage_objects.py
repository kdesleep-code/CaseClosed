"""Store file icon images as storage objects."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260601_0040"
down_revision = "20260531_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_icon_settings",
        sa.Column("storage_object_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("file_icon_settings", "storage_object_id")
