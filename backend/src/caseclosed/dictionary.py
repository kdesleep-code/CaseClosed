from __future__ import annotations

import json
import unicodedata
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.db.models import DictionaryEntry
from caseclosed.db.models import DictionaryEntryAlias
from caseclosed.db.models import DictionaryEntryLink
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso

router = APIRouter(prefix="/api/v1/dictionary", tags=["dictionary"])


class DictionaryEntryPayload(BaseModel):
    headword: str
    aliases: list[str] = Field(default_factory=list)
    interpretation: str
    examples: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    related_entry_ids: list[str] = Field(default_factory=list)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def normalized_term(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def required_text(value: str, label: str, max_length: int) -> str:
    text = value.strip()
    if text == "":
        raise json_error(422, "VALIDATION_ERROR", f"{label} is required.")
    if len(text) > max_length:
        raise json_error(422, "VALIDATION_ERROR", f"{label} is too long.")
    return text


def optional_text(value: str | None, max_length: int) -> str | None:
    if value is None or value.strip() == "":
        return None
    text = value.strip()
    if len(text) > max_length:
        raise json_error(422, "VALIDATION_ERROR", "Text is too long.")
    return text


def normalized_aliases(values: list[str], headword_key: str) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    seen = {headword_key}
    for value in values:
        alias = value.strip()
        if alias == "":
            continue
        if len(alias) > 160:
            raise json_error(422, "VALIDATION_ERROR", "Alias is too long.")
        key = normalized_term(alias)
        if key not in seen:
            seen.add(key)
            aliases.append((alias, key))
    return aliases


def normalized_urls(values: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = value.strip()
        if url == "":
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
            raise json_error(422, "VALIDATION_ERROR", "Reference URLs must use http or https.")
        if len(url) > 2048:
            raise json_error(422, "VALIDATION_ERROR", "Reference URL is too long.")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def unique_ids(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = value.strip()
        if item_id != "" and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result


def validate_terms_available(
    session: DatabaseSession,
    headword_key: str,
    aliases: list[tuple[str, str]],
    excluded_entry_id: str | None = None,
) -> None:
    keys = [headword_key, *(key for _, key in aliases)]
    entry_statement = select(DictionaryEntry).where(DictionaryEntry.normalized_headword.in_(keys))
    alias_statement = select(DictionaryEntryAlias).where(DictionaryEntryAlias.normalized_alias.in_(keys))
    if excluded_entry_id is not None:
        entry_statement = entry_statement.where(DictionaryEntry.id != excluded_entry_id)
        alias_statement = alias_statement.where(DictionaryEntryAlias.entry_id != excluded_entry_id)
    if session.scalar(entry_statement) is not None or session.scalar(alias_statement) is not None:
        raise json_error(409, "DUPLICATE_TERM", "A headword or alias already uses this term.")


def validate_related_entries(
    session: DatabaseSession,
    entry_id: str,
    related_entry_ids: list[str],
) -> list[str]:
    related_ids = unique_ids(related_entry_ids)
    if entry_id in related_ids:
        raise json_error(422, "VALIDATION_ERROR", "An entry cannot link to itself.")
    if related_ids:
        found_ids = set(
            session.scalars(select(DictionaryEntry.id).where(DictionaryEntry.id.in_(related_ids))).all()
        )
        if found_ids != set(related_ids):
            raise json_error(404, "NOT_FOUND", "A related dictionary entry was not found.")
    return related_ids


def aliases_by_entry(session: DatabaseSession) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for alias in session.scalars(
        select(DictionaryEntryAlias).order_by(DictionaryEntryAlias.alias.asc())
    ).all():
        result.setdefault(alias.entry_id, []).append(alias.alias)
    return result


def links_by_entry(session: DatabaseSession) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for link in session.scalars(select(DictionaryEntryLink)).all():
        result.setdefault(link.source_entry_id, []).append(link.target_entry_id)
    return result


def entry_data(
    entry: DictionaryEntry,
    aliases: list[str],
    related_entry_ids: list[str],
) -> dict[str, object]:
    try:
        source_urls = json.loads(entry.source_urls_json)
    except json.JSONDecodeError:
        source_urls = []
    if not isinstance(source_urls, list):
        source_urls = []
    return {
        "id": entry.id,
        "headword": entry.headword,
        "aliases": aliases,
        "interpretation": entry.interpretation,
        "examples": entry.examples,
        "source_urls": [url for url in source_urls if isinstance(url, str)],
        "related_entry_ids": related_entry_ids,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "version": entry.version,
    }


def replace_entry_details(
    session: DatabaseSession,
    entry: DictionaryEntry,
    aliases: list[tuple[str, str]],
    related_entry_ids: list[str],
    now: str,
) -> None:
    session.execute(delete(DictionaryEntryAlias).where(DictionaryEntryAlias.entry_id == entry.id))
    session.execute(delete(DictionaryEntryLink).where(DictionaryEntryLink.source_entry_id == entry.id))
    session.add_all(
        DictionaryEntryAlias(
            id=new_id("dictionary_alias"),
            entry_id=entry.id,
            alias=alias,
            normalized_alias=key,
            created_at=now,
        )
        for alias, key in aliases
    )
    session.add_all(
        DictionaryEntryLink(
            id=new_id("dictionary_link"),
            source_entry_id=entry.id,
            target_entry_id=target_id,
            created_at=now,
        )
        for target_id in related_entry_ids
    )


@router.get("")
def list_dictionary_entries(
    query: str | None = None,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    statement = select(DictionaryEntry)
    normalized_query = (query or "").strip()
    if normalized_query != "":
        matching_alias_entry_ids = select(DictionaryEntryAlias.entry_id).where(
            DictionaryEntryAlias.alias.ilike(f"%{normalized_query}%")
        )
        statement = statement.where(
            or_(
                DictionaryEntry.headword.ilike(f"%{normalized_query}%"),
                DictionaryEntry.interpretation.ilike(f"%{normalized_query}%"),
                DictionaryEntry.examples.ilike(f"%{normalized_query}%"),
                DictionaryEntry.id.in_(matching_alias_entry_ids),
            )
        )
    entries = session.scalars(
        statement.order_by(DictionaryEntry.normalized_headword.asc(), DictionaryEntry.created_at.asc())
    ).all()
    alias_map = aliases_by_entry(session)
    link_map = links_by_entry(session)
    return {
        "ok": True,
        "data": {
            "items": [
                entry_data(entry, alias_map.get(entry.id, []), link_map.get(entry.id, []))
                for entry in entries
            ]
        },
    }


@router.get("/{entry_id}")
def get_dictionary_entry(
    entry_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    entry = session.get(DictionaryEntry, entry_id)
    if entry is None:
        raise json_error(404, "NOT_FOUND", "Dictionary entry was not found.")
    return {
        "ok": True,
        "data": entry_data(
            entry,
            aliases_by_entry(session).get(entry.id, []),
            links_by_entry(session).get(entry.id, []),
        ),
    }


@router.post("")
def create_dictionary_entry(
    payload: DictionaryEntryPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    now = jst_iso()
    headword = required_text(payload.headword, "Headword", 160)
    headword_key = normalized_term(headword)
    aliases = normalized_aliases(payload.aliases, headword_key)
    validate_terms_available(session, headword_key, aliases)
    entry = DictionaryEntry(
        id=new_id("dictionary_entry"),
        headword=headword,
        normalized_headword=headword_key,
        interpretation=required_text(payload.interpretation, "Interpretation", 20000),
        examples=optional_text(payload.examples, 20000),
        source_urls_json=json.dumps(normalized_urls(payload.source_urls), ensure_ascii=True),
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(entry)
    session.flush()
    related_ids = validate_related_entries(session, entry.id, payload.related_entry_ids)
    replace_entry_details(session, entry, aliases, related_ids, now)
    session.commit()
    return {"ok": True, "data": entry_data(entry, [item[0] for item in aliases], related_ids)}


@router.put("/{entry_id}")
def update_dictionary_entry(
    entry_id: str,
    payload: DictionaryEntryPayload,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    entry = session.get(DictionaryEntry, entry_id)
    if entry is None:
        raise json_error(404, "NOT_FOUND", "Dictionary entry was not found.")
    headword = required_text(payload.headword, "Headword", 160)
    headword_key = normalized_term(headword)
    aliases = normalized_aliases(payload.aliases, headword_key)
    validate_terms_available(session, headword_key, aliases, entry.id)
    related_ids = validate_related_entries(session, entry.id, payload.related_entry_ids)
    now = jst_iso()
    entry.headword = headword
    entry.normalized_headword = headword_key
    entry.interpretation = required_text(payload.interpretation, "Interpretation", 20000)
    entry.examples = optional_text(payload.examples, 20000)
    entry.source_urls_json = json.dumps(normalized_urls(payload.source_urls), ensure_ascii=True)
    entry.updated_at = now
    entry.version += 1
    replace_entry_details(session, entry, aliases, related_ids, now)
    session.commit()
    return {"ok": True, "data": entry_data(entry, [item[0] for item in aliases], related_ids)}


@router.delete("/{entry_id}")
def delete_dictionary_entry(
    entry_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    entry = session.get(DictionaryEntry, entry_id)
    if entry is None:
        raise json_error(404, "NOT_FOUND", "Dictionary entry was not found.")
    session.execute(
        delete(DictionaryEntryLink).where(
            or_(
                DictionaryEntryLink.source_entry_id == entry.id,
                DictionaryEntryLink.target_entry_id == entry.id,
            )
        )
    )
    session.execute(delete(DictionaryEntryAlias).where(DictionaryEntryAlias.entry_id == entry.id))
    session.delete(entry)
    session.commit()
    return {"ok": True, "data": {"id": entry_id}}
