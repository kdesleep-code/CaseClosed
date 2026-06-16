from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import AuthLoginAttempt
from caseclosed.db.models import AuditLog
from caseclosed.db.models import ExternalOperation
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import StorageOperationHistory
from caseclosed.db.models import SystemLog
from caseclosed.db.models import WriteRequest
from caseclosed.db.runtime import get_session

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

PAGE_SIZE = 100
EXPORT_LIMIT = 10000
LOG_TYPES = (
    "audit",
    "system",
    "auth",
    "job",
    "write",
    "external",
    "storage",
    "llm",
    "mail_send",
)


@dataclass(frozen=True)
class LogEntry:
    id: str
    source_type: str
    occurred_at: str
    level: str
    category: str
    summary: str
    detail: str | None
    status: str | None
    target_type: str | None
    target_id: str | None
    metadata: object | None


@router.get("")
def list_logs(
    page: int = 1,
    types: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    entries = filtered_logs(
        session=session,
        type_filter=parse_type_filter(types),
        query=q,
        date_from=date_from,
        date_to=date_to,
    )
    total = len(entries)
    safe_page = max(1, page)
    start = (safe_page - 1) * PAGE_SIZE
    page_items = entries[start : start + PAGE_SIZE]
    counts = Counter(entry.source_type for entry in entries)
    return {
        "ok": True,
        "data": {
            "items": [log_entry_data(entry) for entry in page_items],
            "page": safe_page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "types": [{"type": log_type, "count": counts[log_type]} for log_type in LOG_TYPES],
        },
    }


@router.get("/export")
def export_logs(
    types: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> Response:
    entries = filtered_logs(
        session=session,
        type_filter=parse_type_filter(types),
        query=q,
        date_from=date_from,
        date_to=date_to,
    )[:EXPORT_LIMIT]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "occurred_at",
            "source_type",
            "level",
            "category",
            "status",
            "summary",
            "target_type",
            "target_id",
            "detail",
            "metadata_json",
            "id",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry.occurred_at,
                entry.source_type,
                entry.level,
                entry.category,
                entry.status,
                entry.summary,
                entry.target_type,
                entry.target_id,
                entry.detail,
                json.dumps(entry.metadata, ensure_ascii=False)
                if entry.metadata is not None
                else "",
                entry.id,
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="caseclosed-logs.csv"'},
    )


def filtered_logs(
    *,
    session: DatabaseSession,
    type_filter: set[str],
    query: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[LogEntry]:
    entries = list(iter_log_entries(session, type_filter))
    if date_from:
        entries = [entry for entry in entries if entry.occurred_at >= date_from]
    if date_to:
        entries = [entry for entry in entries if entry.occurred_at <= date_to]
    normalized_query = (query or "").strip().lower()
    if normalized_query:
        entries = [
            entry
            for entry in entries
            if normalized_query in searchable_log_text(entry).lower()
        ]
    return sorted(entries, key=lambda entry: (entry.occurred_at, entry.id), reverse=True)


def iter_log_entries(
    session: DatabaseSession,
    type_filter: set[str],
) -> Iterable[LogEntry]:
    if "audit" in type_filter:
        for row in session.scalars(select(AuditLog)).all():
            yield LogEntry(
                id=row.id,
                source_type="audit",
                occurred_at=row.occurred_at,
                level="info",
                category=row.action_type,
                summary=f"{row.action_type} {row.target_type}",
                detail=None,
                status=None,
                target_type=row.target_type,
                target_id=row.target_id,
                metadata=parse_json_object(row.metadata_json),
            )
    if "system" in type_filter:
        for row in session.scalars(select(SystemLog)).all():
            yield LogEntry(
                id=row.id,
                source_type="system",
                occurred_at=row.occurred_at,
                level=row.level,
                category=row.component,
                summary=row.message,
                detail=None,
                status=None,
                target_type=row.component,
                target_id=None,
                metadata=parse_json_object(row.metadata_json),
            )
    if "auth" in type_filter:
        for row in session.scalars(select(AuthLoginAttempt)).all():
            yield LogEntry(
                id=row.id,
                source_type="auth",
                occurred_at=row.attempted_at,
                level="info" if row.success else "warning",
                category="login",
                summary="Login succeeded" if row.success else "Login failed",
                detail=row.failure_reason,
                status="succeeded" if row.success else "failed",
                target_type="client",
                target_id=row.client_fingerprint,
                metadata={
                    "ip_address": row.ip_address,
                    "user_agent": row.user_agent,
                },
            )
    if "job" in type_filter:
        for row in session.scalars(select(Job)).all():
            yield LogEntry(
                id=row.id,
                source_type="job",
                occurred_at=row.updated_at,
                level=level_for_status(row.status),
                category=row.job_type,
                summary=f"{row.job_type} {row.status}",
                detail=row.error_message,
                status=row.status,
                target_type="job",
                target_id=row.id,
                metadata={
                    "payload": parse_json_object(row.payload_json),
                    "result": parse_json_object(row.result_json),
                    "error_type": row.error_type,
                    "retry_count": row.retry_count,
                    "max_retries": row.max_retries,
                    "created_at": row.created_at,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                },
            )
    if "write" in type_filter:
        for row in session.scalars(select(WriteRequest)).all():
            yield LogEntry(
                id=row.id,
                source_type="write",
                occurred_at=row.applied_at or row.created_at,
                level=level_for_status(row.status),
                category=row.operation_type,
                summary=f"{row.operation_type} {row.status}",
                detail=row.error_message,
                status=row.status,
                target_type=row.entity_type,
                target_id=row.entity_id,
                metadata={
                    "source": row.source,
                    "payload": parse_json_object(row.payload_json),
                    "error_type": row.error_type,
                    "created_at": row.created_at,
                    "applied_at": row.applied_at,
                },
            )
    if "external" in type_filter:
        for row in session.scalars(select(ExternalOperation)).all():
            yield LogEntry(
                id=row.id,
                source_type="external",
                occurred_at=row.updated_at,
                level=level_for_status(row.status),
                category=f"{row.external_service}:{row.operation_type}",
                summary=f"{row.external_service} {row.operation_type} {row.status}",
                detail=row.unknown_reason,
                status=row.status,
                target_type=row.external_service,
                target_id=row.external_id,
                metadata={
                    "request_payload": parse_json_object(row.request_payload_json),
                    "attempt_count": row.attempt_count,
                    "last_attempt_at": row.last_attempt_at,
                    "succeeded_at": row.succeeded_at,
                    "failed_at": row.failed_at,
                    "unknown_at": row.unknown_at,
                    "manual_resolution_required": bool(row.manual_resolution_required),
                },
            )
    if "storage" in type_filter:
        storage_rows = session.scalars(
            select(StorageOperationHistory).where(
                StorageOperationHistory.scope == "managed"
            )
        ).all()
        for row in storage_rows:
            yield LogEntry(
                id=row.id,
                source_type="storage",
                occurred_at=row.created_at,
                level="info",
                category=row.operation_type,
                summary=storage_summary(row),
                detail=row.storage_path,
                status=None,
                target_type="storage_object",
                target_id=row.storage_object_id,
                metadata={
                    "actor": row.actor,
                    "scope": row.scope,
                    "content_type": row.content_type,
                    "byte_size": row.byte_size,
                    "source_type": row.source_type,
                    "source_message_id": row.source_message_id,
                    "directory_id": row.directory_id,
                    "details": parse_json_object(row.details_json),
                },
            )
    if "llm" in type_filter:
        for row in session.scalars(select(LlmRun)).all():
            yield LogEntry(
                id=row.id,
                source_type="llm",
                occurred_at=row.finished_at or row.started_at or row.created_at,
                level=level_for_status(row.status),
                category=row.function_type,
                summary=f"{row.function_type} {row.provider_name}/{row.model_name} {row.status}",
                detail=row.error_message or row.output_text_preview,
                status=row.status,
                target_type="llm_run",
                target_id=row.id,
                metadata={
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "total_tokens": row.total_tokens,
                    "estimated_cost": row.estimated_cost,
                    "error_type": row.error_type,
                    "retry_count": row.retry_count,
                    "created_at": row.created_at,
                },
            )
    if "mail_send" in type_filter:
        for row in session.scalars(select(MailSendRequest)).all():
            yield LogEntry(
                id=row.id,
                source_type="mail_send",
                occurred_at=row.updated_at,
                level=level_for_status(row.status),
                category="mail_send_request",
                summary=f"{row.subject or '(no subject)'} {row.status}",
                detail=row.body_text[:500],
                status=row.status,
                target_type="mail_send_request",
                target_id=row.id,
                metadata={
                    "to": parse_json_object(row.to_addresses_json),
                    "cc": parse_json_object(row.cc_addresses_json),
                    "bcc": parse_json_object(row.bcc_addresses_json),
                    "attachment_names": parse_json_object(row.attachment_names_json),
                    "reply_to_message_id": row.reply_to_message_id,
                    "sent_message_id": row.sent_message_id,
                    "scheduled_at": row.scheduled_at,
                    "created_at": row.created_at,
                },
            )


def log_entry_data(entry: LogEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "source_type": entry.source_type,
        "occurred_at": entry.occurred_at,
        "level": entry.level,
        "category": entry.category,
        "summary": entry.summary,
        "detail": entry.detail,
        "status": entry.status,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "metadata": entry.metadata,
    }


def parse_type_filter(types: str | None) -> set[str]:
    if not types:
        return set(LOG_TYPES)
    requested = {item.strip() for item in types.split(",") if item.strip()}
    selected = requested.intersection(LOG_TYPES)
    return selected or set(LOG_TYPES)


def parse_json_object(value: str | None) -> object | None:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def searchable_log_text(entry: LogEntry) -> str:
    return " ".join(
        [
            entry.id,
            entry.source_type,
            entry.level,
            entry.category,
            entry.summary,
            entry.detail or "",
            entry.status or "",
            entry.target_type or "",
            entry.target_id or "",
            json.dumps(entry.metadata, ensure_ascii=False)
            if entry.metadata is not None
            else "",
        ]
    )


def level_for_status(status: str) -> str:
    if status in {"failed", "stale", "unknown"}:
        return "error"
    if status in {"pending", "running"}:
        return "warning"
    return "info"


def storage_summary(row: StorageOperationHistory) -> str:
    filename = row.original_filename or row.storage_object_id or "storage object"
    return f"{row.operation_type} {filename}"
