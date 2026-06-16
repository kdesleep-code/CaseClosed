from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.cases import case_tool_icon_for_url
from caseclosed.cases import case_tool_icon_url
from caseclosed.cases import tool_icon_label_from_url
from caseclosed.db.models import AppSetting
from caseclosed.db.models import ExternalToolLink
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/external-tools", tags=["external-tools"])

EXTERNAL_TOOL_TAG_ORDER_KEY = "external_tool_tag_order"


class ExternalToolCreate(BaseModel):
    title: str
    url: str
    tags: list[str] = []
    note: str | None = None


class ExternalToolUpdate(BaseModel):
    title: str | None = None
    url: str | None = None
    tags: list[str] | None = None
    note: str | None = None


class ExternalToolReorder(BaseModel):
    tag_order: list[str] | None = None
    tool_ids: list[str] | None = None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalize_title(value: str) -> str:
    title = value.strip()
    if title == "":
        raise json_error(422, "VALIDATION_ERROR", "Title is required.")
    if len(title) > 160:
        raise json_error(422, "VALIDATION_ERROR", "Title is too long.")
    return title


def normalize_url(value: str) -> str:
    url = value.strip()
    if url == "":
        raise json_error(422, "VALIDATION_ERROR", "URL is required.")
    if len(url) > 2048:
        raise json_error(422, "VALIDATION_ERROR", "URL is too long.")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise json_error(422, "VALIDATION_ERROR", "URL must start with http:// or https://.")
    return url


def normalize_tags(values: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip()
        if tag == "":
            continue
        if len(tag) > 48:
            raise json_error(422, "VALIDATION_ERROR", "Tag is too long.")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags or ["General"]


def read_json_setting(session: DatabaseSession, key: str) -> object | None:
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        return None
    try:
        return json.loads(setting.value_json)
    except json.JSONDecodeError:
        return None


def write_json_setting(session: DatabaseSession, key: str, value: object, now: str) -> None:
    value_json = json.dumps(value, ensure_ascii=True)
    setting = session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        session.add(AppSetting(id=f"setting_{key}", key=key, value_json=value_json, updated_at=now))
        return
    setting.value_json = value_json
    setting.updated_at = now


def read_tag_order(session: DatabaseSession) -> list[str]:
    value = read_json_setting(session, EXTERNAL_TOOL_TAG_ORDER_KEY)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip() != ""]
    return []


def external_tool_data(session: DatabaseSession, tool: ExternalToolLink) -> dict[str, object]:
    try:
        tags = json.loads(tool.tags_json)
    except json.JSONDecodeError:
        tags = []
    if not isinstance(tags, list):
        tags = []
    normalized_tags = [tag for tag in tags if isinstance(tag, str)]
    icon_setting = case_tool_icon_for_url(session, tool.url)
    return {
        "id": tool.id,
        "title": tool.title,
        "url": tool.url,
        "tags": normalized_tags,
        "note": tool.note,
        "icon_label": tool_icon_label_from_url(tool.url),
        "icon_setting_id": icon_setting.id if icon_setting is not None else None,
        "icon_url": case_tool_icon_url(icon_setting),
        "sort_order": tool.sort_order,
        "created_at": tool.created_at,
        "updated_at": tool.updated_at,
        "version": tool.version,
    }


def ordered_tools(session: DatabaseSession) -> list[ExternalToolLink]:
    return session.scalars(
        select(ExternalToolLink).order_by(
            ExternalToolLink.sort_order.asc(),
            ExternalToolLink.title.asc(),
            ExternalToolLink.created_at.asc(),
        )
    ).all()


def tool_tags(tool: ExternalToolLink) -> list[str]:
    try:
        values = json.loads(tool.tags_json)
    except json.JSONDecodeError:
        return ["General"]
    return (
        normalize_tags([item for item in values if isinstance(item, str)])
        if isinstance(values, list)
        else ["General"]
    )


@router.get("")
def list_external_tools(session: DatabaseSession = Depends(get_session)) -> dict[str, object]:
    tools = ordered_tools(session)
    known_tags: list[str] = []
    seen: set[str] = set()
    for tag in read_tag_order(session):
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            known_tags.append(tag)
    for tool in tools:
        for tag in tool_tags(tool):
            key = tag.casefold()
            if key not in seen:
                seen.add(key)
                known_tags.append(tag)
    return {
        "ok": True,
        "data": {
            "items": [external_tool_data(session, tool) for tool in tools],
            "tag_order": known_tags,
        },
    }


@router.post("")
def create_external_tool(
    payload: ExternalToolCreate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    max_sort_order = session.scalar(
        select(ExternalToolLink.sort_order).order_by(ExternalToolLink.sort_order.desc())
    )
    tool = ExternalToolLink(
        id=new_id("external_tool"),
        title=normalize_title(payload.title),
        url=normalize_url(payload.url),
        tags_json=json.dumps(normalize_tags(payload.tags), ensure_ascii=True),
        note=None if payload.note is None or payload.note.strip() == "" else payload.note.strip(),
        sort_order=(max_sort_order if max_sort_order is not None else -1) + 1,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(tool)
    tag_order = read_tag_order(session)
    for tag in normalize_tags(payload.tags):
        if tag.casefold() not in {item.casefold() for item in tag_order}:
            tag_order.append(tag)
    write_json_setting(session, EXTERNAL_TOOL_TAG_ORDER_KEY, tag_order, now)
    session.commit()
    return {"ok": True, "data": {"tool": external_tool_data(session, tool)}}


@router.patch("/reorder")
def reorder_external_tools(
    payload: ExternalToolReorder,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    tools = ordered_tools(session)
    tools_by_id = {tool.id: tool for tool in tools}
    if payload.tool_ids is not None:
        ordered_ids: list[str] = []
        seen: set[str] = set()
        for tool_id in payload.tool_ids:
            if tool_id in seen:
                continue
            if tool_id not in tools_by_id:
                raise json_error(404, "NOT_FOUND", "External tool not found.")
            seen.add(tool_id)
            ordered_ids.append(tool_id)
        ordered_ids.extend(tool.id for tool in tools if tool.id not in seen)
        for index, tool_id in enumerate(ordered_ids):
            tool = tools_by_id[tool_id]
            tool.sort_order = index
            tool.updated_at = now
            tool.version += 1
    if payload.tag_order is not None:
        write_json_setting(session, EXTERNAL_TOOL_TAG_ORDER_KEY, normalize_tags(payload.tag_order), now)
    session.commit()
    return {
        "ok": True,
        "data": {
            "items": [external_tool_data(session, tool) for tool in ordered_tools(session)],
            "tag_order": read_tag_order(session),
        },
    }


@router.patch("/{tool_id}")
def update_external_tool(
    tool_id: str,
    payload: ExternalToolUpdate,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    tool = session.get(ExternalToolLink, tool_id)
    if tool is None:
        raise json_error(404, "NOT_FOUND", "External tool not found.")
    now = jst_iso()
    if payload.title is not None:
        tool.title = normalize_title(payload.title)
    if payload.url is not None:
        tool.url = normalize_url(payload.url)
    if payload.tags is not None:
        tags = normalize_tags(payload.tags)
        tool.tags_json = json.dumps(tags, ensure_ascii=True)
        tag_order = read_tag_order(session)
        for tag in tags:
            if tag.casefold() not in {item.casefold() for item in tag_order}:
                tag_order.append(tag)
        write_json_setting(session, EXTERNAL_TOOL_TAG_ORDER_KEY, tag_order, now)
    if payload.note is not None:
        tool.note = None if payload.note.strip() == "" else payload.note.strip()
    tool.updated_at = now
    tool.version += 1
    session.commit()
    return {"ok": True, "data": {"tool": external_tool_data(session, tool)}}


@router.delete("/{tool_id}")
def delete_external_tool(
    tool_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    tool = session.get(ExternalToolLink, tool_id)
    if tool is None:
        raise json_error(404, "NOT_FOUND", "External tool not found.")
    session.delete(tool)
    session.commit()
    return {"ok": True, "data": {"deleted": True}}
