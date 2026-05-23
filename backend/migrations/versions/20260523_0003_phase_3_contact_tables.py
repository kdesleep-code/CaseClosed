"""Create the Phase 3 contact and pending contact tables.

Revision ID: 20260523_0003
Revises: 20260522_0002
Create Date: 2026-05-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260523_0003"
down_revision = "20260522_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_contacts_status", "contacts", ["status"])

    op.create_table(
        "contact_email_addresses",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("contact_id", sa.Text(), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("email_address", sa.Text(), nullable=False),
        sa.Column("normalized_email_address", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "resolution_status",
            sa.Text(),
            nullable=False,
            server_default="unresolved",
        ),
        sa.Column("is_primary", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_contact_email_addresses_contact_id",
        "contact_email_addresses",
        ["contact_id"],
    )
    op.create_index(
        "ix_contact_email_addresses_resolution_status",
        "contact_email_addresses",
        ["resolution_status"],
    )

    op.create_table(
        "contact_tags",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("contact_id", sa.Text(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("contact_id", "tag"),
    )

    op.create_table(
        "contact_registration_suggestions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "email_address_id",
            sa.Text(),
            sa.ForeignKey("contact_email_addresses.id"),
            nullable=False,
        ),
        sa.Column("source_message_id", sa.Text(), nullable=True),
        sa.Column("suggested_display_name", sa.Text(), nullable=True),
        sa.Column("suggested_organization", sa.Text(), nullable=True),
        sa.Column("suggested_role", sa.Text(), nullable=True),
        sa.Column("suggested_tags_json", sa.Text(), nullable=True),
        sa.Column("suggested_memo", sa.Text(), nullable=True),
        sa.Column("suggested_skip_reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("llm_run_id", sa.Text(), sa.ForeignKey("llm_runs.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="suggested"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_contact_registration_suggestions_email_status",
        "contact_registration_suggestions",
        ["email_address_id", "status"],
    )

    op.create_table(
        "contact_context_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("contact_id", sa.Text(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("context_markdown", sa.Text(), nullable=False),
        sa.Column("llm_run_id", sa.Text(), sa.ForeignKey("llm_runs.id"), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.UniqueConstraint("contact_id", "version_no"),
    )

    op.create_table(
        "contact_merge_history",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_contact_id", sa.Text(), nullable=False),
        sa.Column("target_contact_id", sa.Text(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("merged_at", sa.Text(), nullable=False),
        sa.Column("merged_by", sa.Text(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("contact_merge_history")
    op.drop_table("contact_context_versions")
    op.drop_index(
        "ix_contact_registration_suggestions_email_status",
        table_name="contact_registration_suggestions",
    )
    op.drop_table("contact_registration_suggestions")
    op.drop_table("contact_tags")
    op.drop_index(
        "ix_contact_email_addresses_resolution_status",
        table_name="contact_email_addresses",
    )
    op.drop_index(
        "ix_contact_email_addresses_contact_id",
        table_name="contact_email_addresses",
    )
    op.drop_table("contact_email_addresses")
    op.drop_index("ix_contacts_status", table_name="contacts")
    op.drop_table("contacts")
