from __future__ import annotations

import base64
import binascii
import asyncio
from io import BytesIO
from contextlib import suppress
from datetime import datetime
import hashlib
import json
import secrets
import socket
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from caseclosed.auth import json_error
from caseclosed.cases import case_root_visible_storage_objects
from caseclosed.cases import case_storage_directory_ids
from caseclosed.cases import ensure_case_exists
from caseclosed.db.models import AuditLog
from caseclosed.db.models import CaseGenre
from caseclosed.db.models import CaseMailLink
from caseclosed.db.models import ExtensionDefinition
from caseclosed.db.models import ExtensionInstance
from caseclosed.db.models import GmailMessage
from caseclosed.db.models import MailAutoState
from caseclosed.db.models import MailUserState
from caseclosed.db.models import StorageDirectory
from caseclosed.db.models import StorageObject
from caseclosed.db.runtime import case_storage_directory_id
from caseclosed.db.runtime import get_session
from caseclosed.db.runtime import jst_iso
from caseclosed.db import runtime as db_runtime
from caseclosed.storage import save_storage_object
from caseclosed.storage import storage_directory_data
from caseclosed.storage import storage_directory_path
from caseclosed.storage import storage_object_absolute_path
from caseclosed.storage import storage_object_data
from caseclosed.storage import storage_object_version_data
from caseclosed.storage import update_storage_object_from_upload

router = APIRouter(prefix="/api/v1/extensions", tags=["extensions"])
extension_api_router = APIRouter(prefix="/api/v1/extension-api", tags=["extension-api"])

RUNNING_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}
ALLOWED_EXTENSION_STATUSES = {"enabled", "disabled"}
ALLOWED_INSTANCE_STATUSES = {"starting", "running", "stopped", "failed"}
DEFAULT_EXTENSION_MANIFESTS = [
    Path(__file__).resolve().parents[3]
    / "extensions"
    / "caseclosed-extension-template"
    / "caseclosed-extension.json",
]


class ExtensionManifestRegistration(BaseModel):
    manifest_path: str | None = None
    root_path: str | None = None
    manifest: dict[str, object] | None = None


class ExtensionStartRequest(BaseModel):
    case_id: str | None = None
    context: dict[str, object] | None = None
    idle_timeout_seconds: int = 1800


class ExtensionOutputUpload(BaseModel):
    filename: str
    content_type: str | None = None
    data_base64: str
    directory_id: str | None = None


class BytesUpload:
    def __init__(self, *, filename: str, content_type: str, data: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._handle = BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)

    async def close(self) -> None:
        self._handle.close()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def write_extension_audit_log(
    session: DatabaseSession,
    *,
    action_type: str,
    target_type: str,
    target_id: str | None,
    case_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    now = jst_iso()
    session.add(
        AuditLog(
            id=new_id("audit"),
            session_id=None,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            case_id=case_id,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
            occurred_at=now,
            created_at=now,
        )
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_slug(value: object) -> str:
    slug = str(value or "").strip()
    if slug == "":
        raise json_error(422, "VALIDATION_ERROR", "Extension slug is required.")
    if len(slug) > 80:
        raise json_error(422, "VALIDATION_ERROR", "Extension slug is too long.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(character not in allowed for character in slug):
        raise json_error(422, "VALIDATION_ERROR", "Extension slug contains invalid characters.")
    return slug


def normalize_text(value: object, *, field_name: str, max_length: int) -> str:
    text = str(value or "").strip()
    if text == "":
        raise json_error(422, "VALIDATION_ERROR", f"{field_name} is required.")
    if len(text) > max_length:
        raise json_error(422, "VALIDATION_ERROR", f"{field_name} is too long.")
    return text


def normalize_optional_text(value: object, *, max_length: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if len(text) > max_length:
        raise json_error(422, "VALIDATION_ERROR", "Text value is too long.")
    return text


def normalize_command(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) == 0:
        raise json_error(422, "VALIDATION_ERROR", "Extension command must be a non-empty list.")
    command = [str(item).strip() for item in value if str(item).strip() != ""]
    if len(command) == 0:
        raise json_error(422, "VALIDATION_ERROR", "Extension command is required.")
    return command


def normalize_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = str(item).strip()
        if tag == "":
            continue
        if len(tag) > 48:
            raise json_error(422, "VALIDATION_ERROR", "Extension tag is too long.")
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


def load_manifest(payload: ExtensionManifestRegistration) -> tuple[dict[str, object], Path]:
    if payload.manifest is not None:
        if payload.root_path is None:
            raise json_error(422, "VALIDATION_ERROR", "root_path is required with inline manifest.")
        return payload.manifest, Path(payload.root_path).expanduser().resolve()
    if payload.manifest_path is None:
        raise json_error(422, "VALIDATION_ERROR", "manifest_path or manifest is required.")
    manifest_path = Path(payload.manifest_path).expanduser().resolve()
    if not manifest_path.is_file():
        raise json_error(404, "NOT_FOUND", "Extension manifest not found.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise json_error(422, "VALIDATION_ERROR", "Extension manifest is invalid JSON.") from error
    if not isinstance(manifest, dict):
        raise json_error(422, "VALIDATION_ERROR", "Extension manifest must be an object.")
    return manifest, manifest_path.parent


def upsert_extension_from_manifest(
    session: DatabaseSession,
    manifest: dict[str, object],
    root_path: Path,
    *,
    source: str,
    write_audit_log: bool,
) -> ExtensionDefinition:
    if not root_path.exists() or not root_path.is_dir():
        raise json_error(404, "NOT_FOUND", "Extension root path not found.")
    slug = normalize_slug(manifest.get("slug"))
    name = normalize_text(manifest.get("name"), field_name="Extension name", max_length=160)
    command = normalize_command(manifest.get("command"))
    description = normalize_optional_text(manifest.get("description"))
    url_path = normalize_optional_text(manifest.get("url_path"), max_length=256)
    tags = normalize_tags(manifest.get("tags"))
    manifest_with_source = {**manifest, "caseclosed_source": source}
    now = jst_iso()
    existing = session.scalar(select(ExtensionDefinition).where(ExtensionDefinition.slug == slug))
    if existing is None:
        extension = ExtensionDefinition(
            id=new_id("extension"),
            slug=slug,
            name=name,
            description=description,
            root_path=str(root_path),
            command_json=json.dumps(command, ensure_ascii=True),
            url_path=url_path,
            tags_json=json.dumps(tags, ensure_ascii=True),
            manifest_json=json.dumps(manifest_with_source, ensure_ascii=False),
            status="enabled",
            created_at=now,
            updated_at=now,
            version=1,
        )
        session.add(extension)
    else:
        extension = existing
        extension.name = name
        extension.description = description
        extension.root_path = str(root_path)
        extension.command_json = json.dumps(command, ensure_ascii=True)
        extension.url_path = url_path
        extension.tags_json = json.dumps(tags, ensure_ascii=True)
        extension.manifest_json = json.dumps(manifest_with_source, ensure_ascii=False)
        extension.status = "enabled"
        extension.updated_at = now
        extension.version += 1
    if write_audit_log:
        write_extension_audit_log(
            session,
            action_type="extension.registered",
            target_type="extension",
            target_id=extension.id,
            metadata={
                "slug": extension.slug,
                "name": extension.name,
                "root_path": extension.root_path,
                "updated_existing": existing is not None,
                "source": source,
            },
        )
    return extension


def bootstrap_default_extensions(session: DatabaseSession) -> None:
    bootstrapped = False
    for manifest_path in DEFAULT_EXTENSION_MANIFESTS:
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            continue
        upsert_extension_from_manifest(
            session,
            manifest,
            manifest_path.parent,
            source="default",
            write_audit_log=False,
        )
        bootstrapped = True
    if bootstrapped:
        session.commit()


def extension_data(extension: ExtensionDefinition) -> dict[str, object]:
    manifest = json.loads(extension.manifest_json)
    return {
        "id": extension.id,
        "slug": extension.slug,
        "name": extension.name,
        "description": extension.description,
        "root_path": extension.root_path,
        "command": json.loads(extension.command_json),
        "url_path": extension.url_path,
        "tags": json.loads(extension.tags_json),
        "status": extension.status,
        "source": manifest.get("caseclosed_source", "user") if isinstance(manifest, dict) else "user",
        "created_at": extension.created_at,
        "updated_at": extension.updated_at,
        "version": extension.version,
    }


def instance_data(instance: ExtensionInstance) -> dict[str, object]:
    return {
        "id": instance.id,
        "extension_id": instance.extension_id,
        "case_id": instance.case_id,
        "status": instance.status,
        "host": instance.host,
        "port": instance.port,
        "base_url": instance.base_url,
        "process_id": instance.process_id,
        "launch_context": json.loads(instance.launch_context_json),
        "started_at": instance.started_at,
        "last_seen_at": instance.last_seen_at,
        "idle_timeout_seconds": instance.idle_timeout_seconds,
        "stopped_at": instance.stopped_at,
        "error_message": instance.error_message,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
        "version": instance.version,
    }


def allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def stop_instance_process(instance: ExtensionInstance) -> None:
    process = RUNNING_PROCESSES.pop(instance.id, None)
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def mark_instance_stopped(
    session: DatabaseSession,
    instance: ExtensionInstance,
    *,
    error_message: str | None = None,
) -> ExtensionInstance:
    stop_instance_process(instance)
    now = jst_iso()
    instance.status = "failed" if error_message is not None else "stopped"
    instance.error_message = error_message
    instance.stopped_at = now
    instance.updated_at = now
    instance.version += 1
    return instance


def stop_idle_extension_instances(session: DatabaseSession) -> int:
    instances = session.scalars(
        select(ExtensionInstance).where(ExtensionInstance.status.in_(["starting", "running"]))
    ).all()
    now = datetime.fromisoformat(jst_iso())
    stopped_count = 0
    for instance in instances:
        try:
            last_seen = datetime.fromisoformat(instance.last_seen_at)
        except ValueError:
            last_seen = now
        idle_seconds = (now - last_seen).total_seconds()
        if idle_seconds < instance.idle_timeout_seconds:
            continue
        extension = session.get(ExtensionDefinition, instance.extension_id)
        mark_instance_stopped(session, instance)
        write_extension_audit_log(
            session,
            action_type="extension.auto_stopped",
            target_type="extension_instance",
            target_id=instance.id,
            case_id=instance.case_id,
            metadata={
                "extension_id": instance.extension_id,
                "slug": extension.slug if extension is not None else None,
                "idle_seconds": idle_seconds,
                "idle_timeout_seconds": instance.idle_timeout_seconds,
            },
        )
        stopped_count += 1
    if stopped_count > 0:
        session.commit()
    return stopped_count


class ExtensionIdleSupervisor:
    def __init__(self, *, interval_seconds: float = 30.0) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.interval_seconds)
            with db_runtime.SessionLocal() as session:
                stop_idle_extension_instances(session)


def decode_base64_payload(value: str) -> bytes:
    raw_value = value.strip()
    if "," in raw_value and raw_value.lower().startswith("data:"):
        raw_value = raw_value.split(",", maxsplit=1)[1]
    try:
        return base64.b64decode(raw_value, validate=True)
    except binascii.Error as error:
        raise json_error(422, "VALIDATION_ERROR", "Invalid base64 data.") from error


def json_list(value: str | None) -> list[object]:
    if value is None:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def extension_mail_data(
    message: GmailMessage,
    user_state: MailUserState | None,
    auto_state: MailAutoState | None,
    *,
    include_body: bool,
) -> dict[str, object]:
    data: dict[str, object] = {
        "id": message.id,
        "gmail_message_id": message.gmail_message_id,
        "gmail_thread_id": message.gmail_thread_id,
        "thread_id": message.thread_id,
        "received_at": message.received_at,
        "subject": message.subject,
        "from_address": message.from_address,
        "from_name": message.from_name,
        "sender_address": message.sender_address,
        "reply_to_address": message.reply_to_address,
        "to_addresses": json_list(message.to_addresses_json),
        "cc_addresses": json_list(message.cc_addresses_json),
        "bcc_addresses": json_list(message.bcc_addresses_json),
        "snippet": message.snippet,
        "gmail_link": message.gmail_link,
        "gmail_labels": json_list(message.gmail_labels_json),
        "external_starred": bool(message.external_starred),
        "user_importance": user_state.user_importance if user_state is not None else None,
        "effective_importance": auto_state.effective_importance if auto_state is not None else None,
        "processed_status": user_state.processed_status if user_state is not None else None,
        "read_status": user_state.read_status if user_state is not None else None,
    }
    if include_body:
        data["body_text"] = message.body_text
    return data


def instance_from_token(
    session: DatabaseSession,
    authorization: str | None,
    x_caseclosed_extension_token: str | None,
) -> ExtensionInstance:
    token = x_caseclosed_extension_token
    if token is None and authorization is not None:
        prefix = "Bearer "
        if authorization.startswith(prefix):
            token = authorization[len(prefix) :].strip()
    if token is None or token.strip() == "":
        raise json_error(401, "UNAUTHORIZED", "Extension token is required.")
    instance = session.scalar(
        select(ExtensionInstance).where(ExtensionInstance.token_hash == token_hash(token.strip()))
    )
    if instance is None or instance.status not in {"starting", "running"}:
        raise json_error(401, "UNAUTHORIZED", "Extension token is invalid.")
    now = jst_iso()
    instance.last_seen_at = now
    instance.updated_at = now
    instance.version += 1
    return instance


def require_extension_instance(
    session: DatabaseSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_caseclosed_extension_token: str | None = Header(default=None),
) -> ExtensionInstance:
    return instance_from_token(session, authorization, x_caseclosed_extension_token)


@router.get("")
def list_extensions(session: DatabaseSession = Depends(get_session)) -> dict[str, object]:
    stop_idle_extension_instances(session)
    extensions = session.scalars(
        select(ExtensionDefinition).order_by(
            ExtensionDefinition.name.asc(),
            ExtensionDefinition.slug.asc(),
        )
    ).all()
    instances = session.scalars(
        select(ExtensionInstance)
        .where(ExtensionInstance.status.in_(["starting", "running"]))
        .order_by(ExtensionInstance.started_at.desc())
    ).all()
    return {
        "ok": True,
        "data": {
            "items": [extension_data(extension) for extension in extensions],
            "running_instances": [instance_data(instance) for instance in instances],
        },
    }


@router.post("/register")
def register_extension(
    payload: ExtensionManifestRegistration,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    manifest, root_path = load_manifest(payload)
    extension = upsert_extension_from_manifest(
        session,
        manifest,
        root_path,
        source="user",
        write_audit_log=True,
    )
    session.commit()
    return {"ok": True, "data": {"extension": extension_data(extension)}}


@router.post("/{extension_id}/start")
def start_extension(
    extension_id: str,
    payload: ExtensionStartRequest,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    stop_idle_extension_instances(session)
    extension = session.get(ExtensionDefinition, extension_id)
    if extension is None:
        raise json_error(404, "NOT_FOUND", "Extension not found.")
    if extension.status != "enabled":
        raise json_error(409, "EXTENSION_DISABLED", "Extension is disabled.")
    if payload.case_id is not None:
        ensure_case_exists(session, payload.case_id)
    idle_timeout = max(60, min(payload.idle_timeout_seconds, 24 * 60 * 60))
    existing_instance = session.scalar(
        select(ExtensionInstance)
        .where(ExtensionInstance.extension_id == extension.id)
        .where(ExtensionInstance.case_id == payload.case_id)
        .where(ExtensionInstance.status.in_(["starting", "running"]))
        .order_by(ExtensionInstance.started_at.desc())
    )
    if existing_instance is not None:
        now = jst_iso()
        existing_instance.last_seen_at = now
        existing_instance.updated_at = now
        existing_instance.idle_timeout_seconds = idle_timeout
        existing_instance.version += 1
        write_extension_audit_log(
            session,
            action_type="extension.reused",
            target_type="extension_instance",
            target_id=existing_instance.id,
            case_id=payload.case_id,
            metadata={
                "extension_id": extension.id,
                "slug": extension.slug,
                "name": extension.name,
                "base_url": existing_instance.base_url,
                "idle_timeout_seconds": idle_timeout,
            },
        )
        session.commit()
        return {
            "ok": True,
            "data": {
                "instance": instance_data(existing_instance),
                "open_url": existing_instance.base_url,
                "extension_token": None,
                "reused": True,
            },
        }
    port = allocate_port()
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}{extension.url_path or ''}"
    token = secrets.token_urlsafe(32)
    now = jst_iso()
    launch_context = {
        "case_id": payload.case_id,
        "context": payload.context or {},
    }
    instance = ExtensionInstance(
        id=new_id("extension_instance"),
        extension_id=extension.id,
        case_id=payload.case_id,
        status="starting",
        host=host,
        port=port,
        base_url=base_url,
        process_id=None,
        token_hash=token_hash(token),
        launch_context_json=json.dumps(launch_context, ensure_ascii=False),
        started_at=now,
        last_seen_at=now,
        idle_timeout_seconds=idle_timeout,
        stopped_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        version=1,
    )
    session.add(instance)
    session.flush()
    command = json.loads(extension.command_json)
    env = {
        **dict(__import__("os").environ),
        "CASECLOSED_EXTENSION_TOKEN": token,
        "CASECLOSED_EXTENSION_INSTANCE_ID": instance.id,
        "CASECLOSED_API_BASE_URL": "http://127.0.0.1:8000",
        "CASECLOSED_EXTENSION_PORT": str(port),
        "CASECLOSED_CASE_ID": payload.case_id or "",
    }
    try:
        process = subprocess.Popen(
            command,
            cwd=extension.root_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        instance.status = "failed"
        instance.error_message = str(error)
        instance.stopped_at = jst_iso()
        instance.updated_at = instance.stopped_at
        instance.version += 1
        write_extension_audit_log(
            session,
            action_type="extension.start_failed",
            target_type="extension",
            target_id=extension.id,
            case_id=payload.case_id,
            metadata={
                "extension_instance_id": instance.id,
                "slug": extension.slug,
                "error_message": str(error),
            },
        )
        session.commit()
        raise json_error(500, "EXTENSION_START_FAILED", str(error)) from error
    instance.process_id = process.pid
    instance.status = "running"
    instance.updated_at = jst_iso()
    instance.version += 1
    RUNNING_PROCESSES[instance.id] = process
    write_extension_audit_log(
        session,
        action_type="extension.started",
        target_type="extension_instance",
        target_id=instance.id,
        case_id=payload.case_id,
        metadata={
            "extension_id": extension.id,
            "slug": extension.slug,
            "name": extension.name,
            "process_id": process.pid,
            "base_url": base_url,
            "idle_timeout_seconds": idle_timeout,
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "instance": instance_data(instance),
            "open_url": base_url,
            "extension_token": token,
        },
    }


@router.post("/instances/{instance_id}/stop")
def stop_extension_instance(
    instance_id: str,
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    instance = session.get(ExtensionInstance, instance_id)
    if instance is None:
        raise json_error(404, "NOT_FOUND", "Extension instance not found.")
    extension = session.get(ExtensionDefinition, instance.extension_id)
    mark_instance_stopped(session, instance)
    write_extension_audit_log(
        session,
        action_type="extension.stopped",
        target_type="extension_instance",
        target_id=instance.id,
        case_id=instance.case_id,
        metadata={
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "process_id": instance.process_id,
        },
    )
    session.commit()
    return {"ok": True, "data": {"instance": instance_data(instance)}}


@extension_api_router.get("/context")
def get_extension_context(
    instance: ExtensionInstance = Depends(require_extension_instance),
) -> dict[str, object]:
    return {
        "ok": True,
        "data": {
            "instance": instance_data(instance),
        },
    }


@extension_api_router.get("/case")
def get_extension_case(
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if instance.case_id is None:
        raise json_error(409, "NO_CASE_CONTEXT", "Extension was not started with a Case.")
    case = ensure_case_exists(session, instance.case_id)
    genre = session.get(CaseGenre, case.genre_id) if case.genre_id is not None else None
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type="extension.case_context_read",
        target_type="case",
        target_id=case.id,
        case_id=case.id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "case": {
                "id": case.id,
                "genre_id": case.genre_id,
                "genre": {
                    "id": genre.id,
                    "title": genre.title,
                    "color_hex": genre.color_hex,
                    "sort_order": genre.sort_order,
                }
                if genre is not None
                else None,
                "name": case.name,
                "description": case.description,
                "open_when_text": case.open_when_text,
                "open_when_date": case.open_when_date,
                "closed_when_text": case.closed_when_text,
                "progress_status": case.progress_status,
                "tags": json.loads(case.tags_json) if case.tags_json else [],
                "updated_at": case.updated_at,
            },
        },
    }


@extension_api_router.get("/case/files")
def list_extension_case_files(
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if instance.case_id is None:
        raise json_error(409, "NO_CASE_CONTEXT", "Extension was not started with a Case.")
    case = ensure_case_exists(session, instance.case_id)
    storage_objects = case_root_visible_storage_objects(session, case, limit=500)
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type="extension.case_files_listed",
        target_type="case",
        target_id=case.id,
        case_id=case.id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "file_count": len(storage_objects),
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "items": [storage_object_data(storage_object, session) for storage_object in storage_objects],
        },
    }


@extension_api_router.get("/case/storage-tree")
def list_extension_case_storage_tree(
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if instance.case_id is None:
        raise json_error(409, "NO_CASE_CONTEXT", "Extension was not started with a Case.")
    case = ensure_case_exists(session, instance.case_id)
    directory_ids = case_storage_directory_ids(session, case)
    directories = session.scalars(
        select(StorageDirectory)
        .where(StorageDirectory.status == "active")
        .where(StorageDirectory.id.in_(directory_ids))
        .order_by(StorageDirectory.name.asc(), StorageDirectory.id.asc())
    ).all()
    storage_objects = session.scalars(
        select(StorageObject)
        .where(StorageObject.scope == "managed")
        .where(StorageObject.status == "active")
        .where(StorageObject.directory_id.in_(directory_ids))
        .order_by(StorageObject.original_filename.asc(), StorageObject.id.asc())
    ).all()
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type="extension.case_storage_tree_listed",
        target_type="case",
        target_id=case.id,
        case_id=case.id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "directory_count": len(directories),
            "file_count": len(storage_objects),
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "root_directory_id": case_storage_directory_id(case.id),
            "directories": [
                {
                    **storage_directory_data(directory),
                    "path": storage_directory_path(session, directory.id),
                }
                for directory in directories
            ],
            "files": [storage_object_data(storage_object, session) for storage_object in storage_objects],
        },
    }


@extension_api_router.get("/case/files/{storage_object_id}/content")
def get_extension_case_file_content(
    storage_object_id: str,
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if instance.case_id is None:
        raise json_error(409, "NO_CASE_CONTEXT", "Extension was not started with a Case.")
    case = ensure_case_exists(session, instance.case_id)
    directory_ids = case_storage_directory_ids(session, case)
    storage_object = session.get(StorageObject, storage_object_id)
    if (
        storage_object is None
        or storage_object.status != "active"
        or storage_object.scope != "managed"
        or storage_object.directory_id not in directory_ids
    ):
        raise json_error(404, "NOT_FOUND", "Storage object not found.")
    object_path = storage_object_absolute_path(storage_object, session)
    if not object_path.is_file():
        raise json_error(404, "NOT_FOUND", "Storage object file not found.")
    data = object_path.read_bytes()
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type="extension.case_file_content_read",
        target_type="storage_object",
        target_id=storage_object.id,
        case_id=case.id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "filename": storage_object.original_filename,
            "byte_size": storage_object.byte_size,
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "storage_object": storage_object_data(storage_object, session),
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    }


@extension_api_router.get("/mails")
def list_extension_mails(
    q: str | None = Query(default=None),
    from_address: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    received_from: str | None = Query(default=None),
    received_to: str | None = Query(default=None),
    case_id: str | None = Query(default=None),
    scope: str = Query(default="launch_case"),
    include_body: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    normalized_scope = scope.strip().casefold()
    if normalized_scope not in {"launch_case", "all"}:
        raise json_error(422, "VALIDATION_ERROR", "Mail scope must be launch_case or all.")
    target_case_id = case_id or (instance.case_id if normalized_scope == "launch_case" else None)
    if normalized_scope == "launch_case" and instance.case_id is not None and target_case_id != instance.case_id:
        raise json_error(403, "FORBIDDEN", "Extension can only read mails for its launch Case.")
    statement = (
        select(GmailMessage, MailUserState, MailAutoState)
        .join(MailUserState, MailUserState.message_id == GmailMessage.id, isouter=True)
        .join(MailAutoState, MailAutoState.message_id == GmailMessage.id, isouter=True)
    )
    if target_case_id is not None:
        ensure_case_exists(session, target_case_id)
        statement = statement.join(CaseMailLink, CaseMailLink.message_id == GmailMessage.id).where(
            CaseMailLink.case_id == target_case_id
        )
    if from_address is not None and from_address.strip() != "":
        pattern = f"%{from_address.strip()}%"
        statement = statement.where(GmailMessage.from_address.ilike(pattern))
    if subject is not None and subject.strip() != "":
        pattern = f"%{subject.strip()}%"
        statement = statement.where(GmailMessage.subject.ilike(pattern))
    if q is not None and q.strip() != "":
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            GmailMessage.subject.ilike(pattern)
            | GmailMessage.snippet.ilike(pattern)
            | GmailMessage.body_text.ilike(pattern)
            | GmailMessage.from_address.ilike(pattern)
        )
    if received_from is not None and received_from.strip() != "":
        statement = statement.where(GmailMessage.received_at >= received_from.strip())
    if received_to is not None and received_to.strip() != "":
        statement = statement.where(GmailMessage.received_at <= received_to.strip())
    rows = session.execute(
        statement.order_by(GmailMessage.received_at.desc(), GmailMessage.id.desc()).limit(limit)
    ).all()
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type="extension.mails_listed",
        target_type="gmail_messages",
        target_id=None,
        case_id=target_case_id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "case_id": target_case_id,
            "scope": normalized_scope,
            "q": q,
            "from_address": from_address,
            "subject": subject,
            "received_from": received_from,
            "received_to": received_to,
            "include_body": include_body,
            "limit": limit,
            "result_count": len(rows),
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "items": [
                extension_mail_data(message, user_state, auto_state, include_body=include_body)
                for message, user_state, auto_state in rows
            ],
            "filters": {
                "case_id": target_case_id,
                "scope": normalized_scope,
                "q": q,
                "from_address": from_address,
                "subject": subject,
                "received_from": received_from,
                "received_to": received_to,
                "include_body": include_body,
                "limit": limit,
            },
        },
    }


@extension_api_router.post("/case/files")
async def upload_extension_case_file(
    payload: ExtensionOutputUpload,
    instance: ExtensionInstance = Depends(require_extension_instance),
    session: DatabaseSession = Depends(get_session),
) -> dict[str, object]:
    if instance.case_id is None:
        raise json_error(409, "NO_CASE_CONTEXT", "Extension was not started with a Case.")
    ensure_case_exists(session, instance.case_id)
    data = decode_base64_payload(payload.data_base64)
    if len(data) == 0:
        raise json_error(422, "VALIDATION_ERROR", "Uploaded file is empty.")
    now = jst_iso()
    content_type = payload.content_type or "application/octet-stream"
    case = ensure_case_exists(session, instance.case_id)
    case_directory_ids = case_storage_directory_ids(session, case)
    directory_id = payload.directory_id or case_storage_directory_id(instance.case_id)
    if directory_id not in case_directory_ids:
        raise json_error(403, "FORBIDDEN", "Extension can only upload files to its launch Case storage.")
    storage_object = session.scalar(
        select(StorageObject)
        .where(StorageObject.scope == "managed")
        .where(StorageObject.status == "active")
        .where(StorageObject.directory_id == directory_id)
        .where(StorageObject.original_filename == payload.filename)
        .order_by(StorageObject.updated_at.desc(), StorageObject.id.desc())
    )
    version = None
    skipped = False
    action_type = "extension.case_file_uploaded"
    if storage_object is None:
        storage_object = save_storage_object(
            session,
            scope="managed",
            filename=payload.filename,
            content_type=content_type,
            data=data,
            now=now,
            directory_id=directory_id,
            source_type="extension",
        )
    else:
        version = await update_storage_object_from_upload(
            session,
            storage_object,
            upload=BytesUpload(filename=payload.filename, content_type=content_type, data=data),
            now=now,
        )
        skipped = version is None
        action_type = "extension.case_file_version_added" if version is not None else "extension.case_file_upload_skipped"
    extension = session.get(ExtensionDefinition, instance.extension_id)
    write_extension_audit_log(
        session,
        action_type=action_type,
        target_type="storage_object",
        target_id=storage_object.id,
        case_id=instance.case_id,
        metadata={
            "extension_instance_id": instance.id,
            "extension_id": instance.extension_id,
            "slug": extension.slug if extension is not None else None,
            "filename": storage_object.original_filename,
            "content_type": storage_object.content_type,
            "byte_size": storage_object.byte_size,
            "version_id": version.id if version is not None else None,
            "skipped": skipped,
        },
    )
    session.commit()
    return {
        "ok": True,
        "data": {
            "storage_object": storage_object_data(storage_object, session),
            "version": storage_object_version_data(version) if version is not None else None,
            "skipped": skipped,
            "skip_reason": "duplicate_content" if skipped else None,
        },
    }
