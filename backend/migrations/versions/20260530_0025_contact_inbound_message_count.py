"""Add contact inbound message count."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0025"
down_revision = "20260530_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "inbound_message_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    op.execute(
        """
        UPDATE contacts
        SET inbound_message_count = (
            SELECT COUNT(*)
            FROM gmail_messages
            JOIN contact_email_addresses
                ON contact_email_addresses.normalized_email_address
                    = gmail_messages.from_address
            WHERE contact_email_addresses.contact_id = contacts.id
              AND COALESCE(gmail_messages.gmail_labels_json, '') NOT LIKE '%"SENT"%'
        )
        WHERE EXISTS (
            SELECT 1
            FROM contact_email_addresses
            WHERE contact_email_addresses.contact_id = contacts.id
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("inbound_message_count")
