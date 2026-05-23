from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import ExternalOperation
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/external-operations", tags=["external-operations"])


class ExternalOperationResolution(BaseModel):
    resolution: str
    external_id: str | None = None
    note: str | None = None


def external_operation_data(operation: ExternalOperation) -> dict[str, object]:
    return {
        "id": operation.id,
        "operation_type": operation.operation_type,
        "status": operation.status,
        "external_service": operation.external_service,
        "external_id": operation.external_id,
        "unknown_reason": operation.unknown_reason,
        "manual_resolution_required": bool(operation.manual_resolution_required),
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
    }


@router.get("")
def list_external_operations(
    status: str = "all",
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = select(ExternalOperation).order_by(
        ExternalOperation.created_at,
        ExternalOperation.id,
    )
    if status != "all":
        statement = statement.where(ExternalOperation.status == status)

    operations = session.scalars(statement).all()
    return {
        "ok": True,
        "data": {"items": [external_operation_data(operation) for operation in operations]},
    }


@router.post("/{operation_id}/resolve")
def resolve_external_operation(
    operation_id: str,
    payload: ExternalOperationResolution,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    operation = session.get(ExternalOperation, operation_id)
    if operation is None:
        raise json_error(404, "NOT_FOUND", "External operation not found.")
    if operation.status != "unknown":
        raise json_error(
            409,
            "CONFLICT",
            "Only unknown external operations require manual resolution.",
        )

    resolved_at = jst_iso()
    if payload.resolution == "mark_succeeded":
        operation.status = "succeeded"
        operation.external_id = payload.external_id
        operation.succeeded_at = resolved_at
    elif payload.resolution == "mark_failed":
        operation.status = "failed"
        operation.failed_at = resolved_at
    elif payload.resolution == "mark_canceled":
        operation.status = "canceled"
    else:
        raise json_error(422, "VALIDATION_ERROR", "Invalid resolution.")

    operation.manual_resolution_required = 0
    operation.updated_at = resolved_at
    session.commit()
    return {"ok": True, "data": external_operation_data(operation)}
