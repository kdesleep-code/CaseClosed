"""Add case template extension links to genres."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260624_0054"
down_revision = "20260618_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("case_genres", sa.Column("template_extension_id", sa.Text(), nullable=True))
    op.add_column("case_genres", sa.Column("template_context_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("case_genres", "template_context_json")
    op.drop_column("case_genres", "template_extension_id")
