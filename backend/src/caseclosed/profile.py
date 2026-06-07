from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import AppSetting
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.email_addressing import normalize_email_address

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])

USER_PROFILE_KEY = "user_profile"


class UserProfilePayload(BaseModel):
    display_name: str = ""
    primary_email: str = ""
    email_aliases: list[str] = []
    affiliation: str = ""
    academic_title: str = ""
    lab_or_group: str = ""
    research_fields: str = ""
    teaching_responsibilities: str = ""
    committee_roles: str = ""
    administrative_roles: str = ""
    supervised_people: str = ""
    collaborators: str = ""
    important_projects: str = ""
    priority_keywords: str = ""
    low_priority_keywords: str = ""
    important_senders_or_domains: str = ""
    expected_response_policy: str = ""
    unavailable_times: str = ""
    default_reply_language: str = "japanese"
    llm_self_description: str = ""
    mail_importance_notes: str = ""


PROFILE_TEXT_FIELDS = [
    "display_name",
    "primary_email",
    "affiliation",
    "academic_title",
    "lab_or_group",
    "research_fields",
    "teaching_responsibilities",
    "committee_roles",
    "administrative_roles",
    "supervised_people",
    "collaborators",
    "important_projects",
    "priority_keywords",
    "low_priority_keywords",
    "important_senders_or_domains",
    "expected_response_policy",
    "unavailable_times",
    "llm_self_description",
    "mail_importance_notes",
]

PROFILE_LANGUAGE_VALUES = {"japanese", "english"}


def default_profile_data() -> dict[str, object]:
    return {
        "display_name": "",
        "primary_email": "",
        "email_aliases": [],
        "affiliation": "",
        "academic_title": "",
        "lab_or_group": "",
        "research_fields": "",
        "teaching_responsibilities": "",
        "committee_roles": "",
        "administrative_roles": "",
        "supervised_people": "",
        "collaborators": "",
        "important_projects": "",
        "priority_keywords": "",
        "low_priority_keywords": "",
        "important_senders_or_domains": "",
        "expected_response_policy": "",
        "unavailable_times": "",
        "default_reply_language": "japanese",
        "llm_self_description": "",
        "mail_importance_notes": "",
        "updated_at": None,
    }


def normalize_optional_email_address(value: str) -> str:
    stripped = value.strip()
    if stripped == "":
        return ""
    normalized = normalize_email_address(stripped)
    if normalized == "" or "@" not in normalized:
        raise json_error(422, "VALIDATION_ERROR", "Invalid email address.")
    return normalized


def normalized_email_aliases(values: list[str], primary_email: str) -> list[str]:
    aliases: list[str] = []
    seen = {primary_email} if primary_email != "" else set()
    for value in values:
        normalized = normalize_optional_email_address(value)
        if normalized == "" or normalized in seen:
            continue
        aliases.append(normalized)
        seen.add(normalized)
    return aliases


def profile_data_from_setting(setting: AppSetting | None) -> dict[str, object]:
    data = default_profile_data()
    if setting is None:
        return data
    try:
        stored = json.loads(setting.value_json)
    except json.JSONDecodeError:
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    for field in PROFILE_TEXT_FIELDS:
        value = stored.get(field)
        data[field] = value if isinstance(value, str) else ""
    aliases = stored.get("email_aliases")
    data["email_aliases"] = [
        value for value in aliases if isinstance(value, str)
    ] if isinstance(aliases, list) else []
    language = stored.get("default_reply_language")
    data["default_reply_language"] = (
        language if isinstance(language, str) and language in PROFILE_LANGUAGE_VALUES else "japanese"
    )
    data["updated_at"] = setting.updated_at
    return data


def read_profile(session: DatabaseSession) -> dict[str, object]:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == USER_PROFILE_KEY))
    return profile_data_from_setting(setting)


def profile_payload_data(payload: UserProfilePayload, now: str) -> dict[str, object]:
    primary_email = normalize_optional_email_address(payload.primary_email)
    data: dict[str, object] = {}
    for field in PROFILE_TEXT_FIELDS:
        data[field] = getattr(payload, field).strip()
    data["primary_email"] = primary_email
    data["email_aliases"] = normalized_email_aliases(payload.email_aliases, primary_email)
    data["default_reply_language"] = (
        payload.default_reply_language
        if payload.default_reply_language in PROFILE_LANGUAGE_VALUES
        else "japanese"
    )
    data["updated_at"] = now
    return data


@router.get("")
def get_profile(
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    return {"ok": True, "data": read_profile(session)}


@router.patch("")
def update_profile(
    payload: UserProfilePayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    data = profile_payload_data(payload, now)
    setting = session.scalar(select(AppSetting).where(AppSetting.key == USER_PROFILE_KEY))
    value_json = json.dumps(data, ensure_ascii=True)
    if setting is None:
        setting = AppSetting(
            id=f"setting_{USER_PROFILE_KEY}",
            key=USER_PROFILE_KEY,
            value_json=value_json,
            updated_at=now,
        )
        session.add(setting)
    else:
        setting.value_json = value_json
        setting.updated_at = now
    session.commit()
    return {"ok": True, "data": read_profile(session)}
