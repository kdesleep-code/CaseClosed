from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Float
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from caseclosed.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    progress_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="not_started",
    )
    ball_status: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    closed_at: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[str | None] = mapped_column(Text)
    is_system_case: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    system_case_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CaseEvent(Base):
    __tablename__ = "case_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text)


class ClientCertificate(Base):
    __tablename__ = "client_certificates"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    device_name: Mapped[str] = mapped_column(Text, nullable=False)
    certificate_fingerprint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    issued_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(Text)
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_certificate_id: Mapped[str | None] = mapped_column(
        ForeignKey("client_certificates.id"),
    )
    session_token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)
    login_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    logout_at: Mapped[str | None] = mapped_column(Text)
    locked_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"))
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class AuthLoginAttempt(Base):
    __tablename__ = "auth_login_attempts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_fingerprint: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    success: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[str] = mapped_column(Text, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class WriteRequest(Base):
    __tablename__ = "write_requests"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    operation_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    base_version: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[str | None] = mapped_column(Text)


class ExternalOperation(Base):
    __tablename__ = "external_operations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    operation_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    external_service: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_attempt_at: Mapped[str | None] = mapped_column(Text)
    succeeded_at: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[str | None] = mapped_column(Text)
    unknown_at: Mapped[str | None] = mapped_column(Text)
    unknown_reason: Mapped[str | None] = mapped_column(Text)
    manual_resolution_required: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    function_type: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt_template: Mapped[str | None] = mapped_column(Text)
    user_prompt_template: Mapped[str | None] = mapped_column(Text)
    retry_prompt_template: Mapped[str | None] = mapped_column(Text)
    output_schema_json: Mapped[str | None] = mapped_column(Text)
    default_model_name: Mapped[str | None] = mapped_column(Text)
    default_provider_name: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class LlmInstructionRule(Base):
    __tablename__ = "llm_instruction_rules"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    condition_json: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_text: Mapped[str] = mapped_column(Text, nullable=False)
    function_types_json: Mapped[str | None] = mapped_column(Text)
    priority_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LlmRun(Base):
    __tablename__ = "llm_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    function_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"))
    input_hash: Mapped[str | None] = mapped_column(Text)
    input_source_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_diagnostic_json: Mapped[str | None] = mapped_column(Text)
    applied_instruction_rule_ids_json: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text)
    output_text_preview: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class MailLlmBlockFilter(Base):
    __tablename__ = "mail_llm_block_filters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    component: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class StorageObject(Base):
    __tablename__ = "storage_objects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    directory_id: Mapped[str | None] = mapped_column(ForeignKey("storage_directories.id"))
    location_id: Mapped[str] = mapped_column(
        ForeignKey("storage_locations.id"),
        nullable=False,
        default="storage_location_internal",
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    llm_input_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_type: Mapped[str | None] = mapped_column(Text)
    source_message_id: Mapped[str | None] = mapped_column(ForeignKey("gmail_messages.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    file_updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StorageObjectVersion(Base):
    __tablename__ = "storage_object_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_object_id: Mapped[str] = mapped_column(
        ForeignKey("storage_objects.id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class FileSummary(Base):
    __tablename__ = "file_summaries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_object_id: Mapped[str] = mapped_column(
        ForeignKey("storage_objects.id"),
        nullable=False,
    )
    storage_object_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("storage_object_versions.id"),
    )
    source_sha256_hex: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text)
    source_content_type: Mapped[str | None] = mapped_column(Text)
    source_byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_type: Mapped[str] = mapped_column(Text, nullable=False, default="llm_digest")
    file_description: Mapped[str] = mapped_column(Text, nullable=False)
    summary_points_json: Mapped[str] = mapped_column(Text, nullable=False)
    llm_digest: Mapped[str] = mapped_column(Text, nullable=False)
    structured_digest_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class FileVersionDiff(Base):
    __tablename__ = "file_version_diffs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_object_id: Mapped[str] = mapped_column(
        ForeignKey("storage_objects.id"),
        nullable=False,
    )
    previous_version_id: Mapped[str] = mapped_column(
        ForeignKey("storage_object_versions.id"),
        nullable=False,
    )
    previous_sha256_hex: Mapped[str] = mapped_column(Text, nullable=False)
    current_sha256_hex: Mapped[str] = mapped_column(Text, nullable=False)
    diff_kind: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    added_lines_json: Mapped[str] = mapped_column(Text, nullable=False)
    removed_lines_json: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StorageOperationHistory(Base):
    __tablename__ = "storage_operation_history"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_object_id: Mapped[str | None] = mapped_column(Text)
    operation_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False, default="system")
    scope: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(Text)
    source_message_id: Mapped[str | None] = mapped_column(Text)
    directory_id: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class StorageDirectory(Base):
    __tablename__ = "storage_directories"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("storage_directories.id"))
    directory_kind: Mapped[str] = mapped_column(Text, nullable=False, default="normal")
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StorageLocation(Base):
    __tablename__ = "storage_locations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="internal")
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    mount_hint: Mapped[str | None] = mapped_column(Text)
    marker_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    user_memo: Mapped[str | None] = mapped_column(Text)
    ai_memo: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="person")
    sender_resolution_mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="self",
    )
    mailing_list_recipient_expression: Mapped[str | None] = mapped_column(Text)
    mail_importance_rule_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="llm",
    )
    mail_importance_rule_importance: Mapped[str | None] = mapped_column(Text)
    mail_importance_rule_instruction: Mapped[str | None] = mapped_column(Text)
    inbound_message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    latest_received_at: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContactEmailAddress(Base):
    __tablename__ = "contact_email_addresses"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"))
    email_address: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_email_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )
    resolution_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="unresolved",
    )
    is_primary: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    has_inbound_message_history: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    deactivated_at: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContactTag(Base):
    __tablename__ = "contact_tags"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class ContactRegistrationSuggestion(Base):
    __tablename__ = "contact_registration_suggestions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email_address_id: Mapped[str] = mapped_column(
        ForeignKey("contact_email_addresses.id"),
        nullable=False,
    )
    source_message_id: Mapped[str | None] = mapped_column(Text)
    suggested_display_name: Mapped[str | None] = mapped_column(Text)
    suggested_organization: Mapped[str | None] = mapped_column(Text)
    suggested_role: Mapped[str | None] = mapped_column(Text)
    suggested_tags_json: Mapped[str | None] = mapped_column(Text)
    suggested_memo: Mapped[str | None] = mapped_column(Text)
    suggested_skip_reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="suggested")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ContactContextVersion(Base):
    __tablename__ = "contact_context_versions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    context_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class ContactMergeHistory(Base):
    __tablename__ = "contact_merge_history"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_contact_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id"),
        nullable=False,
    )
    merged_at: Mapped[str] = mapped_column(Text, nullable=False)
    merged_by: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_json: Mapped[str | None] = mapped_column(Text)


class GmailThread(Base):
    __tablename__ = "gmail_threads"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    gmail_thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    subject_snapshot: Mapped[str | None] = mapped_column(Text)
    first_message_at: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class GmailMessage(Base):
    __tablename__ = "gmail_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[str] = mapped_column(ForeignKey("gmail_threads.id"), nullable=False)
    internal_date: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    from_address: Mapped[str] = mapped_column(Text, nullable=False)
    from_name: Mapped[str | None] = mapped_column(Text)
    sender_address: Mapped[str | None] = mapped_column(Text)
    reply_to_address: Mapped[str | None] = mapped_column(Text)
    to_addresses_json: Mapped[str | None] = mapped_column(Text)
    cc_addresses_json: Mapped[str | None] = mapped_column(Text)
    bcc_addresses_json: Mapped[str | None] = mapped_column(Text)
    message_id_header: Mapped[str | None] = mapped_column(Text)
    in_reply_to_header: Mapped[str | None] = mapped_column(Text)
    references_header: Mapped[str | None] = mapped_column(Text)
    list_id: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    gmail_link: Mapped[str | None] = mapped_column(Text)
    gmail_labels_json: Mapped[str | None] = mapped_column(Text)
    external_starred: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class GmailMessageAttachment(Base):
    __tablename__ = "gmail_message_attachments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_messages.id"),
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    gmail_attachment_id: Mapped[str] = mapped_column(Text, nullable=False)
    part_id: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("storage_objects.id"),
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MailUserState(Base):
    __tablename__ = "mail_user_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_messages.id"),
        nullable=False,
        unique=True,
    )
    user_importance: Mapped[str | None] = mapped_column(Text)
    processed_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="unprocessed",
    )
    processed_at: Mapped[str | None] = mapped_column(Text)
    read_status: Mapped[str] = mapped_column(Text, nullable=False, default="unread")
    read_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MailAutoState(Base):
    __tablename__ = "mail_auto_state"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_messages.id"),
        nullable=False,
        unique=True,
    )
    external_importance: Mapped[str | None] = mapped_column(Text)
    suggested_importance: Mapped[str | None] = mapped_column(Text)
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    effective_importance: Mapped[str] = mapped_column(Text, nullable=False)
    pending_reason: Mapped[str | None] = mapped_column(Text)
    pending_from_address_id: Mapped[str | None] = mapped_column(
        ForeignKey("contact_email_addresses.id")
    )
    llm_blocked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_block_reason: Mapped[str | None] = mapped_column(Text)
    llm_blocked_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MailSummary(Base):
    __tablename__ = "mail_summaries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_messages.id"),
        nullable=False,
        unique=True,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_required: Mapped[int | None] = mapped_column(Integer)
    deadline_text: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    key_points_json: Mapped[str | None] = mapped_column(Text)
    translation_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="ja")
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MailThreadSummary(Base):
    __tablename__ = "mail_thread_summaries"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_threads.id"),
        nullable=False,
        unique=True,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    action_required: Mapped[int | None] = mapped_column(Integer)
    next_action: Mapped[str | None] = mapped_column(Text)
    key_points_json: Mapped[str | None] = mapped_column(Text)
    translation_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="ja")
    llm_run_id: Mapped[str | None] = mapped_column(ForeignKey("llm_runs.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MailSendRequest(Base):
    __tablename__ = "mail_send_requests"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    to_addresses_json: Mapped[str] = mapped_column(Text, nullable=False)
    cc_addresses_json: Mapped[str | None] = mapped_column(Text)
    bcc_addresses_json: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_names_json: Mapped[str | None] = mapped_column(Text)
    attachment_data_json: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[str | None] = mapped_column(ForeignKey("gmail_messages.id"))
    sent_message_id: Mapped[str | None] = mapped_column(ForeignKey("gmail_messages.id"))
    scheduled_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
