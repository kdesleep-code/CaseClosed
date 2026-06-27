"""Add PaperShelf metadata."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260626_0055"
down_revision = "20260624_0054"
branch_labels = None
depends_on = None

PAPERS_STORAGE_DIRECTORY_ID = "storage_directory_papers"
SEED_TIMESTAMP = "2026-05-22T00:00:00+09:00"


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("storage_object_id", sa.Text(), sa.ForeignKey("storage_objects.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("bibtex", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("storage_object_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO storage_directories (
                id, parent_id, directory_kind, case_id, name, status, created_at, updated_at, version
            ) VALUES (
                :id, NULL, 'normal', NULL, 'Papers', 'active', :timestamp, :timestamp, 1
            )
            """
        ).bindparams(id=PAPERS_STORAGE_DIRECTORY_ID, timestamp=SEED_TIMESTAMP)
    )
    op.create_table(
        "paper_bibtex_entries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("paper_id", sa.Text(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False, server_default=""),
        sa.Column("entry_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("authors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("journal", sa.Text(), nullable=False, server_default=""),
        sa.Column("year", sa.Text(), nullable=False, server_default=""),
        sa.Column("doi", sa.Text(), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_bibtex", sa.Text(), nullable=False, server_default=""),
        sa.Column("fields_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("paper_id"),
    )


def downgrade() -> None:
    op.drop_table("paper_bibtex_entries")
    op.drop_table("papers")
    op.execute(
        sa.text("DELETE FROM storage_directories WHERE id = :id").bindparams(
            id=PAPERS_STORAGE_DIRECTORY_ID
        )
    )
