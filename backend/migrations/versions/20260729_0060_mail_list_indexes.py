"""Add indexes used by the mail list and related batch lookups."""

from __future__ import annotations

from alembic import op

revision = "20260729_0060"
down_revision = "20260714_0059"
branch_labels = None
depends_on = None


INDEXES = [
    ("ix_gmail_messages_received_at_id", "gmail_messages", ["received_at", "id"]),
    ("ix_gmail_messages_thread_received", "gmail_messages", ["thread_id", "received_at", "id"]),
    ("ix_gmail_message_attachments_message", "gmail_message_attachments", ["message_id"]),
    ("ix_mail_send_requests_sent_message", "mail_send_requests", ["sent_message_id"]),
    ("ix_mail_send_requests_visible", "mail_send_requests", ["reply_to_message_id", "sent_message_id", "status", "scheduled_at"]),
    ("ix_case_mail_links_message", "case_mail_links", ["message_id"]),
    ("ix_contact_tags_contact", "contact_tags", ["contact_id", "tag"]),
]


def upgrade() -> None:
    for name, table_name, columns in INDEXES:
        op.create_index(name, table_name, columns, unique=False)


def downgrade() -> None:
    for name, table_name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table_name)
