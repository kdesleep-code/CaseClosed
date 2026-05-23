from __future__ import annotations

import json
from uuid import uuid4

from caseclosed.db import runtime
from caseclosed.db.models import AuditLog


class AuditLogWriter:
    def write(
        self,
        *,
        action_type: str,
        target_type: str,
        target_id: str | None = None,
        session_id: str | None = None,
        case_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        occurred_at = runtime.jst_iso()
        audit_log_id = f"audit_{uuid4().hex}"
        with runtime.SessionLocal() as session:
            session.add(
                AuditLog(
                    id=audit_log_id,
                    session_id=session_id,
                    action_type=action_type,
                    target_type=target_type,
                    target_id=target_id,
                    case_id=case_id,
                    metadata_json=(
                        json.dumps(metadata) if metadata is not None else None
                    ),
                    occurred_at=occurred_at,
                    created_at=occurred_at,
                )
            )
            session.commit()
        return audit_log_id
