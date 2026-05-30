"""Add LLM input permission to storage objects."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_0022"
down_revision = "20260529_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "llm_input_allowed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.drop_column("llm_input_allowed")
