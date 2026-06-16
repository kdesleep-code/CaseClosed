from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.db.models import AppSetting
from caseclosed.db.models import ExternalOperation
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import Job
from caseclosed.db.models import LlmRun
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailSendRequest
from caseclosed.db.models import StorageObject
from caseclosed.db.models import StorageOperationHistory
from caseclosed.db.models import WriteRequest
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.db.runtime import jst_now

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

LLM_MONTHLY_LIMIT_KEY = "llm_cost_limit_monthly"


class LlmCostSettingsPayload(BaseModel):
    monthly_budget: float | None = None


@router.get("/status")
def maintenance_status(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    llm_cost = llm_cost_summary(session)
    dashboard = maintenance_dashboard_summary(session, llm_cost)
    return {
        "ok": True,
        "data": {
            "job_accepting": True,
            "running_jobs": count_rows(session, Job, Job.status == "running"),
            "action_required_jobs": count_rows(
                session,
                Job,
                or_(Job.status == "failed", Job.status == "stale"),
            ),
            "pending_write_requests": count_rows(
                session,
                WriteRequest,
                WriteRequest.status == "pending",
            ),
            "external_unknown_count": count_rows(
                session,
                ExternalOperation,
                ExternalOperation.status == "unknown",
            ),
            "llm_cost_month_used": llm_cost["month_used"],
            "llm_cost_month_remaining": llm_cost["month_remaining"],
            "backup_status": "not_configured",
            **dashboard,
        },
    }


@router.get("/llm-cost-history")
def get_llm_cost_history(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {"ok": True, "data": llm_cost_history_data(session)}


@router.patch("/llm-cost-settings")
def update_llm_cost_settings(
    payload: LlmCostSettingsPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    monthly_budget = payload.monthly_budget
    if monthly_budget is not None and monthly_budget < 0:
        monthly_budget = 0
    write_setting(session, LLM_MONTHLY_LIMIT_KEY, monthly_budget)
    session.commit()
    return {"ok": True, "data": llm_cost_history_data(session)}


@router.get("/storage-operation-history")
def get_storage_operation_history(
    limit: int = 50,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    safe_limit = max(1, min(limit, 200))
    rows = session.scalars(
        select(StorageOperationHistory)
        .where(StorageOperationHistory.scope == "managed")
        .order_by(
            StorageOperationHistory.created_at.desc(),
            StorageOperationHistory.id.desc(),
        )
        .limit(safe_limit)
    ).all()
    return {
        "ok": True,
        "data": {"items": [storage_operation_history_data(row) for row in rows]},
    }


def count_rows(session: DatabaseSession, model, condition) -> int:
    return session.scalar(select(func.count()).select_from(model).where(condition)) or 0


def storage_operation_history_data(
    history: StorageOperationHistory,
) -> dict[str, object]:
    try:
        details = (
            json.loads(history.details_json)
            if history.details_json is not None
            else None
        )
    except json.JSONDecodeError:
        details = None
    return {
        "id": history.id,
        "storage_object_id": history.storage_object_id,
        "operation_type": history.operation_type,
        "actor": history.actor,
        "scope": history.scope,
        "original_filename": history.original_filename,
        "content_type": history.content_type,
        "byte_size": history.byte_size,
        "storage_path": history.storage_path,
        "source_type": history.source_type,
        "source_message_id": history.source_message_id,
        "directory_id": history.directory_id,
        "details": details,
        "created_at": history.created_at,
    }


def read_float_setting(session: DatabaseSession, key: str) -> float | None:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        return None
    try:
        value = json.loads(setting.value_json)
    except json.JSONDecodeError:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_setting(session: DatabaseSession, key: str, value: object) -> None:
    now = jst_iso()
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    value_json = json.dumps(value, ensure_ascii=True)
    if setting is None:
        setting = AppSetting(
            id=f"setting_{key}",
            key=key,
            value_json=value_json,
            updated_at=now,
        )
        session.add(setting)
        return
    setting.value_json = value_json
    setting.updated_at = now


def llm_cost_summary(session: DatabaseSession) -> dict[str, object]:
    now = jst_now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_used = sum_llm_cost(session, jst_iso(month_start), None)
    monthly_budget = read_float_setting(session, LLM_MONTHLY_LIMIT_KEY)
    month_remaining = (
        None if monthly_budget is None else max(0.0, monthly_budget - month_used)
    )
    return {
        "month_used": round(month_used, 6),
        "monthly_budget": monthly_budget,
        "month_remaining": None if month_remaining is None else round(month_remaining, 6),
    }


def maintenance_dashboard_summary(
    session: DatabaseSession,
    llm_cost: dict[str, object],
) -> dict[str, object]:
    now = jst_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = today_start - timedelta(days=7)
    thirty_days_ago = today_start - timedelta(days=30)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elapsed_days = max(1.0, (now - month_start).total_seconds() / 86400)
    month_used = float(llm_cost.get("month_used") or 0.0)
    month_projected = month_used / elapsed_days * 31

    importance_counts = {
        str(row[0] or "unclassified"): int(row[1] or 0)
        for row in session.execute(
            select(MailAutoState.effective_importance, func.count())
            .group_by(MailAutoState.effective_importance)
        ).all()
    }
    received_30d = count_rows(
        session,
        GmailMessage,
        GmailMessage.received_at >= jst_iso(thirty_days_ago),
    )
    return {
        "storage_active_bytes": int(
            session.scalar(
                select(func.coalesce(func.sum(StorageObject.byte_size), 0)).where(
                    StorageObject.status == "active",
                    StorageObject.scope == "managed",
                )
            )
            or 0
        ),
        "storage_active_objects": count_rows(
            session,
            StorageObject,
            (StorageObject.status == "active") & (StorageObject.scope == "managed"),
        ),
        "mail_total": count_rows(session, GmailMessage, GmailMessage.id.is_not(None)),
        "mail_received_7d": count_rows(
            session,
            GmailMessage,
            GmailMessage.received_at >= jst_iso(seven_days_ago),
        ),
        "mail_sent_7d": count_rows(
            session,
            MailSendRequest,
            (MailSendRequest.updated_at >= jst_iso(seven_days_ago))
            & (
                (MailSendRequest.status == "sent")
                | (MailSendRequest.status == "sent_mock")
                | MailSendRequest.sent_message_id.is_not(None)
            ),
        ),
        "mail_daily_average_30d": round(received_30d / 30, 2),
        "mail_importance_high": importance_counts.get("high", 0),
        "mail_importance_middle": importance_counts.get("middle", 0),
        "mail_importance_low": importance_counts.get("low", 0),
        "mail_importance_sent": importance_counts.get("sent", 0),
        "mail_importance_unclassified": importance_counts.get("unclassified", 0),
        "llm_cost_month_projected": round(month_projected, 6),
    }


def sum_llm_cost(
    session: DatabaseSession,
    start_at: str | None,
    end_at: str | None,
) -> float:
    statement = (
        select(func.coalesce(func.sum(LlmRun.estimated_cost), 0.0))
        .where(LlmRun.status == "succeeded")
        .where(LlmRun.estimated_cost.is_not(None))
    )
    if start_at is not None:
        statement = statement.where(LlmRun.finished_at >= start_at)
    if end_at is not None:
        statement = statement.where(LlmRun.finished_at < end_at)
    return float(session.scalar(statement) or 0.0)


def llm_cost_history_data(session: DatabaseSession) -> dict[str, object]:
    now = jst_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_used = sum_llm_cost(session, jst_iso(today_start), None)
    month_used = sum_llm_cost(session, jst_iso(month_start), None)
    total_used = sum_llm_cost(session, None, None)
    monthly_budget = read_float_setting(session, LLM_MONTHLY_LIMIT_KEY)
    month_remaining = (
        None if monthly_budget is None else max(0.0, monthly_budget - month_used)
    )

    function_rows = session.execute(
        select(
            LlmRun.function_type,
            func.count(),
            func.coalesce(func.sum(LlmRun.prompt_tokens), 0),
            func.coalesce(func.sum(LlmRun.completion_tokens), 0),
            func.coalesce(func.sum(LlmRun.total_tokens), 0),
            func.coalesce(func.sum(LlmRun.estimated_cost), 0.0),
        )
        .where(LlmRun.status == "succeeded")
        .group_by(LlmRun.function_type)
        .order_by(func.coalesce(func.sum(LlmRun.estimated_cost), 0.0).desc())
    ).all()
    daily_items = []
    for day_offset in range(29, -1, -1):
        day_start = today_start - timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        start_iso = jst_iso(day_start)
        daily_items.append(
            {
                "date": day_start.date().isoformat(),
                "run_count": count_llm_runs(session, start_iso, jst_iso(day_end)),
                "estimated_cost": round(
                    sum_llm_cost(session, start_iso, jst_iso(day_end)),
                    6,
                ),
            }
        )
    recent_runs = session.scalars(
        select(LlmRun)
        .order_by(LlmRun.created_at.desc(), LlmRun.id.desc())
        .limit(50)
    ).all()
    return {
        "currency": "usd",
        "source": "local_estimate",
        "monthly_budget": monthly_budget,
        "month_used": round(month_used, 6),
        "month_remaining": None if month_remaining is None else round(month_remaining, 6),
        "today_used": round(today_used, 6),
        "total_used": round(total_used, 6),
        "by_function": [
            {
                "function_type": row[0],
                "run_count": row[1],
                "prompt_tokens": row[2],
                "completion_tokens": row[3],
                "total_tokens": row[4],
                "estimated_cost": round(float(row[5] or 0.0), 6),
            }
            for row in function_rows
        ],
        "daily": daily_items,
        "recent_runs": [
            {
                "id": run.id,
                "function_type": run.function_type,
                "provider_name": run.provider_name,
                "model_name": run.model_name,
                "status": run.status,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "total_tokens": run.total_tokens,
                "estimated_cost": run.estimated_cost,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
            }
            for run in recent_runs
        ],
    }


def count_llm_runs(
    session: DatabaseSession,
    start_at: str,
    end_at: str,
) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(LlmRun)
            .where(LlmRun.status == "succeeded")
            .where(LlmRun.finished_at >= start_at)
            .where(LlmRun.finished_at < end_at)
        )
        or 0
    )
