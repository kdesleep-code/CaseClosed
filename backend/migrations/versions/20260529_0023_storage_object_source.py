"""Add source metadata to storage objects."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_0023"
down_revision = "20260529_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.add_column(sa.Column("source_type", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_message_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_storage_objects_source_message_id_gmail_messages",
            "gmail_messages",
            ["source_message_id"],
            ["id"],
        )

    op.execute(
        """
        UPDATE storage_objects
        SET source_type = 'direct_upload'
        WHERE source_type IS NULL AND scope = 'managed'
        """
    )
    op.execute(
        """
        UPDATE storage_objects
        SET
            source_type = 'mail_attachment',
            source_message_id = (
                SELECT gmail_message_attachments.message_id
                FROM gmail_message_attachments
                WHERE gmail_message_attachments.storage_object_id = storage_objects.id
                LIMIT 1
            )
        WHERE id IN (
            SELECT storage_object_id
            FROM gmail_message_attachments
            WHERE storage_object_id IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.drop_constraint(
            "fk_storage_objects_source_message_id_gmail_messages",
            type_="foreignkey",
        )
        batch_op.drop_column("source_message_id")
        batch_op.drop_column("source_type")
