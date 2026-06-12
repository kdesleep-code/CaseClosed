"""Add tags to cases."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260601_0041"
down_revision = "20260601_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("cases")}
    if "tags_json" not in columns:
        op.add_column("cases", sa.Column("tags_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "tags_json")
