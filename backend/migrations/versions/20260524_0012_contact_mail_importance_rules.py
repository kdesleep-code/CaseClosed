"""Add contact-level mail importance rules.

Revision ID: 20260524_0012
Revises: 20260524_0011
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0012"
down_revision = "20260524_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column(
            "mail_importance_rule_action",
            sa.Text(),
            nullable=False,
            server_default="llm",
        ),
    )
    op.add_column(
        "contacts",
        sa.Column("mail_importance_rule_importance", sa.Text(), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("mail_importance_rule_instruction", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "mail_importance_rule_instruction")
    op.drop_column("contacts", "mail_importance_rule_importance")
    op.drop_column("contacts", "mail_importance_rule_action")
