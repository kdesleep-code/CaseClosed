"""Add contact latest received timestamp."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260530_0026"
down_revision = "20260530_0025"
branch_labels = None
depends_on = None


CONTACT_INBOUND_STATS_SQL = """
UPDATE contacts
SET
    inbound_message_count = (
        SELECT COUNT(DISTINCT gmail_messages.id)
        FROM gmail_messages
        JOIN contact_email_addresses
            ON contact_email_addresses.normalized_email_address
                IN (gmail_messages.from_address, gmail_messages.reply_to_address)
        WHERE contact_email_addresses.contact_id = contacts.id
          AND contact_email_addresses.deleted_at IS NULL
          AND COALESCE(gmail_messages.gmail_labels_json, '') NOT LIKE '%"SENT"%'
    ),
    latest_received_at = (
        SELECT MAX(gmail_messages.received_at)
        FROM gmail_messages
        JOIN contact_email_addresses
            ON contact_email_addresses.normalized_email_address
                IN (gmail_messages.from_address, gmail_messages.reply_to_address)
        WHERE contact_email_addresses.contact_id = contacts.id
          AND contact_email_addresses.deleted_at IS NULL
          AND COALESCE(gmail_messages.gmail_labels_json, '') NOT LIKE '%"SENT"%'
    )
"""


def upgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.add_column(sa.Column("latest_received_at", sa.Text(), nullable=True))
    op.execute(CONTACT_INBOUND_STATS_SQL)


def downgrade() -> None:
    with op.batch_alter_table("contacts") as batch_op:
        batch_op.drop_column("latest_received_at")
