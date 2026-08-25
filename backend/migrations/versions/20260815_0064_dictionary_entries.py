"""Add dictionary entries, aliases, and related-entry links."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260815_0064"
down_revision = "20260730_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dictionary_entries",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("headword", sa.Text(), nullable=False),
        sa.Column("normalized_headword", sa.Text(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=False),
        sa.Column("examples", sa.Text(), nullable=True),
        sa.Column("source_urls_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_headword"),
    )
    op.create_table(
        "dictionary_entry_aliases",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["dictionary_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_alias"),
    )
    op.create_index(
        "ix_dictionary_entry_aliases_entry_id",
        "dictionary_entry_aliases",
        ["entry_id"],
    )
    op.create_table(
        "dictionary_entry_links",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_entry_id", sa.Text(), nullable=False),
        sa.Column("target_entry_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["source_entry_id"], ["dictionary_entries.id"]),
        sa.ForeignKeyConstraint(["target_entry_id"], ["dictionary_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_entry_id", "target_entry_id"),
    )
    op.create_index(
        "ix_dictionary_entry_links_source",
        "dictionary_entry_links",
        ["source_entry_id"],
    )
    op.create_index(
        "ix_dictionary_entry_links_target",
        "dictionary_entry_links",
        ["target_entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dictionary_entry_links_target", table_name="dictionary_entry_links")
    op.drop_index("ix_dictionary_entry_links_source", table_name="dictionary_entry_links")
    op.drop_table("dictionary_entry_links")
    op.drop_index("ix_dictionary_entry_aliases_entry_id", table_name="dictionary_entry_aliases")
    op.drop_table("dictionary_entry_aliases")
    op.drop_table("dictionary_entries")
