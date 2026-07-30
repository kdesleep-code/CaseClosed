"""Link scheduled outgoing mail requests to Cases."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260729_0061"
down_revision = "20260729_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_send_request_case_links",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "send_request_id",
            sa.Text(),
            sa.ForeignKey("mail_send_requests.id"),
            nullable=False,
        ),
        sa.Column("case_id", sa.Text(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("send_request_id", "case_id"),
    )
    op.create_index(
        "ix_mail_send_request_case_links_request",
        "mail_send_request_case_links",
        ["send_request_id"],
    )
    op.create_index(
        "ix_mail_send_request_case_links_case",
        "mail_send_request_case_links",
        ["case_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mail_send_request_case_links_case",
        table_name="mail_send_request_case_links",
    )
    op.drop_index(
        "ix_mail_send_request_case_links_request",
        table_name="mail_send_request_case_links",
    )
    op.drop_table("mail_send_request_case_links")
