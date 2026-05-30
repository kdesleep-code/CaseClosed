"""Add storage object file updated timestamp."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260530_0029"
down_revision = "20260530_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "storage_objects",
        sa.Column("file_updated_at", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE storage_objects
        SET file_updated_at = COALESCE(
            (
                SELECT MAX(storage_operation_history.created_at)
                FROM storage_operation_history
                WHERE storage_operation_history.storage_object_id = storage_objects.id
                  AND storage_operation_history.operation_type IN ('created', 'uploaded', 'updated')
            ),
            storage_objects.created_at
        )
        """
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, storage_object_id, version_number, created_at
            FROM storage_object_versions
            ORDER BY storage_object_id, version_number
            """
        )
    ).mappings().all()
    object_ids = sorted({row["storage_object_id"] for row in rows})
    for object_id in object_ids:
        object_row = connection.execute(
            sa.text(
                """
                SELECT created_at
                FROM storage_objects
                WHERE id = :object_id
                """
            ),
            {"object_id": object_id},
        ).mappings().first()
        if object_row is None:
            continue
        timestamps: dict[int, str] = {1: object_row["created_at"]}
        operations = connection.execute(
            sa.text(
                """
                SELECT operation_type, created_at, details_json
                FROM storage_operation_history
                WHERE storage_object_id = :object_id
                  AND operation_type IN ('created', 'uploaded', 'updated')
                ORDER BY created_at, id
                """
            ),
            {"object_id": object_id},
        ).mappings().all()
        for operation in operations:
            if operation["operation_type"] in {"created", "uploaded"}:
                timestamps[1] = operation["created_at"]
                continue
            details_text = operation["details_json"]
            if details_text is None:
                continue
            try:
                details = json.loads(details_text)
            except json.JSONDecodeError:
                continue
            previous_version_number = details.get("previous_version_number")
            if isinstance(previous_version_number, int):
                timestamps[previous_version_number + 1] = operation["created_at"]

        for row in [candidate for candidate in rows if candidate["storage_object_id"] == object_id]:
            timestamp = timestamps.get(row["version_number"])
            if timestamp is None:
                continue
            connection.execute(
                sa.text(
                    """
                    UPDATE storage_object_versions
                    SET created_at = :created_at
                    WHERE id = :version_id
                    """
                ),
                {"created_at": timestamp, "version_id": row["id"]},
            )

    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.alter_column("file_updated_at", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("storage_objects") as batch_op:
        batch_op.drop_column("file_updated_at")
