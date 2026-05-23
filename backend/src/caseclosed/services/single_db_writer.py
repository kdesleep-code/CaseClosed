from __future__ import annotations

import json

from sqlalchemy import select

from caseclosed.db import runtime
from caseclosed.db.models import CaseEvent
from caseclosed.db.models import WriteRequest


def apply_next_write_request() -> str | None:
    with runtime.SessionLocal() as session:
        write_request = session.scalar(
            select(WriteRequest)
            .where(WriteRequest.status == "pending")
            .order_by(WriteRequest.priority, WriteRequest.created_at, WriteRequest.id)
        )
        if write_request is None:
            return None

        try:
            apply_write_request(session, write_request)
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            write_request.status = "failed"
            write_request.error_type = type(error).__name__
            write_request.error_message = str(error)
        else:
            write_request.status = "applied"
            write_request.applied_at = runtime.jst_iso()

        session.commit()
        return write_request.id


def apply_write_request(session, write_request: WriteRequest) -> None:
    if write_request.operation_type != "case_event.append":
        raise ValueError(f"Unsupported write operation: {write_request.operation_type}")

    payload = json.loads(write_request.payload_json)
    event_id = write_request.entity_id
    if event_id is None:
        raise ValueError("case_event.append requires entity_id.")

    session.add(
        CaseEvent(
            id=event_id,
            case_id=payload["case_id"],
            event_type=payload["event_type"],
            title=payload["title"],
            summary=payload.get("summary"),
            source_type=payload.get("source_type"),
            source_id=payload.get("source_id"),
            occurred_at=payload["occurred_at"],
            created_at=runtime.jst_iso(),
            metadata_json=payload.get("metadata_json"),
        )
    )
