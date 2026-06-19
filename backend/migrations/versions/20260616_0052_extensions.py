"""Add extension registry and instance tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260616_0052"
down_revision = "20260616_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extension_definitions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("command_json", sa.Text(), nullable=False),
        sa.Column("url_path", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="enabled"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "extension_instances",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("extension_id", sa.Text(), sa.ForeignKey("extension_definitions.id"), nullable=False),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="starting"),
        sa.Column("host", sa.Text(), nullable=False, server_default="127.0.0.1"),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("launch_context_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("stopped_at", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_extension_instances_status",
        "extension_instances",
        ["status"],
    )
    op.create_index(
        "ix_extension_instances_case",
        "extension_instances",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extension_instances_case", table_name="extension_instances")
    op.drop_index("ix_extension_instances_status", table_name="extension_instances")
    op.drop_table("extension_instances")
    op.drop_table("extension_definitions")
