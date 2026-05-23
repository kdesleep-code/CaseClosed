"""Create the Phase 2 job, writer, external operation, and LLM foundation tables.

Revision ID: 20260522_0002
Revises: 20260522_0001
Create Date: 2026-05-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260522_0002"
down_revision = "20260522_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.Text(), nullable=True),
        sa.Column("available_at", sa.Text(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_jobs_status_priority_available", "jobs", ["status", "priority", "available_at"])
    op.create_table(
        "write_requests",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("applied_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_write_requests_status_priority_created", "write_requests", ["status", "priority", "created_at"])
    op.create_table(
        "external_operations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("request_payload_hash", sa.Text(), nullable=False),
        sa.Column("request_payload_json", sa.Text(), nullable=False),
        sa.Column("external_service", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.Text(), nullable=True),
        sa.Column("succeeded_at", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.Text(), nullable=True),
        sa.Column("unknown_at", sa.Text(), nullable=True),
        sa.Column("unknown_reason", sa.Text(), nullable=True),
        sa.Column("manual_resolution_required", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_external_operations_status", "external_operations", ["status"])
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("function_type", sa.Text(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("system_prompt_template", sa.Text(), nullable=True),
        sa.Column("user_prompt_template", sa.Text(), nullable=True),
        sa.Column("retry_prompt_template", sa.Text(), nullable=True),
        sa.Column("output_schema_json", sa.Text(), nullable=True),
        sa.Column("default_model_name", sa.Text(), nullable=True),
        sa.Column("default_provider_name", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("function_type", "version_no"),
    )
    op.create_table(
        "llm_instruction_rules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("condition_json", sa.Text(), nullable=False),
        sa.Column("instruction_text", sa.Text(), nullable=False),
        sa.Column("function_types_json", sa.Text(), nullable=True),
        sa.Column("priority_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "llm_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("function_type", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.Text(), sa.ForeignKey("prompt_versions.id"), nullable=True),
        sa.Column("input_hash", sa.Text(), nullable=True),
        sa.Column("input_source_json", sa.Text(), nullable=False),
        sa.Column("input_diagnostic_json", sa.Text(), nullable=True),
        sa.Column("applied_instruction_rule_ids_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("output_text_preview", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retry_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "schema_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("component", sa.Text(), nullable=False, unique=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schema_versions")
    op.drop_table("llm_runs")
    op.drop_table("llm_instruction_rules")
    op.drop_table("prompt_versions")
    op.drop_index("ix_external_operations_status", table_name="external_operations")
    op.drop_table("external_operations")
    op.drop_index("ix_write_requests_status_priority_created", table_name="write_requests")
    op.drop_table("write_requests")
    op.drop_index("ix_jobs_status_priority_available", table_name="jobs")
    op.drop_table("jobs")
