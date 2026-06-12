"""Add calendar event cache and link tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260610_0044"
down_revision = "20260610_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="google"),
        sa.Column("external_calendar_id", sa.Text()),
        sa.Column("external_event_id", sa.Text()),
        sa.Column("external_etag", sa.Text()),
        sa.Column("external_ical_uid", sa.Text()),
        sa.Column("external_html_link", sa.Text()),
        sa.Column("external_updated_at", sa.Text()),
        sa.Column("google_status", sa.Text()),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column("start_at", sa.Text(), nullable=False),
        sa.Column("end_at", sa.Text(), nullable=False),
        sa.Column("all_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_zone", sa.Text()),
        sa.Column("recurring_event_id", sa.Text()),
        sa.Column(
            "attendance_requirement",
            sa.Text(),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("tags_json", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("sync_status", sa.Text(), nullable=False, server_default="synced"),
        sa.Column("last_synced_at", sa.Text()),
        sa.Column("local_note", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "source",
            "external_calendar_id",
            "external_event_id",
            name="uq_calendar_events_external_event",
        ),
    )
    op.create_index(
        "ix_calendar_events_range",
        "calendar_events",
        ["start_at", "end_at"],
    )
    op.create_index(
        "ix_calendar_events_sync_status",
        "calendar_events",
        ["sync_status"],
    )
    op.create_table(
        "calendar_event_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "calendar_event_id",
            sa.Text(),
            sa.ForeignKey("calendar_events.id"),
            nullable=False,
        ),
        sa.Column("linked_type", sa.Text(), nullable=False),
        sa.Column("linked_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="related"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "calendar_event_id",
            "linked_type",
            "linked_id",
            "role",
            name="uq_calendar_event_links_target",
        ),
    )
    op.create_index(
        "ix_calendar_event_links_target",
        "calendar_event_links",
        ["linked_type", "linked_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_event_links_target", table_name="calendar_event_links")
    op.drop_table("calendar_event_links")
    op.drop_index("ix_calendar_events_sync_status", table_name="calendar_events")
    op.drop_index("ix_calendar_events_range", table_name="calendar_events")
    op.drop_table("calendar_events")
