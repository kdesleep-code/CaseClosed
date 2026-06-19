from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
BACKEND_SRC = BACKEND_ROOT / "src"
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"

TEST_PASSWORD = "caseclosed-phase-1-password"
TEST_CERTIFICATE_FINGERPRINT = "SHA256:caseclosed-phase-1-test-device"

PHASE_1_TABLES = {
    "app_settings",
    "audit_logs",
    "case_events",
    "cases",
    "client_certificates",
    "sessions",
    "system_logs",
}

PHASE_2_TABLES = {
    "external_operations",
    "jobs",
    "llm_instruction_rules",
    "llm_runs",
    "prompt_versions",
    "schema_versions",
    "write_requests",
}

PHASE_3_TABLES = {
    "contact_context_versions",
    "contact_email_addresses",
    "contact_merge_history",
    "contact_registration_suggestions",
    "contact_tags",
    "contacts",
}

PHASE_4_TABLES = {
    "gmail_messages",
    "gmail_threads",
    "mail_llm_block_filters",
    "mail_summaries",
    "mail_thread_summaries",
    "mail_send_requests",
    "mail_auto_state",
    "mail_user_state",
}

PHASE_6_TABLES = {
    "file_links",
    "file_version_diffs",
    "file_summaries",
    "gmail_message_attachments",
    "storage_locations",
    "storage_objects",
}

PHASE_9_TABLES = {
    "academic_calendar_days",
    "academic_periods",
    "academic_semesters",
    "academic_years",
    "calendar_event_links",
    "calendar_events",
}

EXTENSION_TABLES = {
    "extension_definitions",
    "extension_instances",
}


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "caseclosed-test.sqlite3"


@pytest.fixture
def database_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.as_posix()}"


@pytest.fixture
def migrated_database(database_path: Path, database_url: str) -> Path:
    assert ALEMBIC_INI.exists(), "Phase 0 requires backend/alembic.ini."

    env = os.environ.copy()
    env["CASECLOSED_DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Alembic must upgrade a new SQLite database.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return database_path


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, database_url: str):
    monkeypatch.syspath_prepend(str(BACKEND_SRC))
    monkeypatch.setenv("CASECLOSED_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "CASECLOSED_STORAGE_ROOT",
        str(Path(database_url.removeprefix("sqlite:///")).parent / "storage"),
    )
    monkeypatch.setenv("CASECLOSED_BOOTSTRAP_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("CASECLOSED_BACKGROUND_WORKER_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CASECLOSED_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CASECLOSED_LLM_PROFILE_MAIL_IMPORTANCE_CLASSIFICATION", raising=False)
    monkeypatch.delenv("CASECLOSED_LLM_MODEL_PROFILES_DIR", raising=False)
    monkeypatch.setenv(
        "CASECLOSED_TEST_CERTIFICATE_FINGERPRINT",
        TEST_CERTIFICATE_FINGERPRINT,
    )

    importlib.invalidate_caches()
    module = importlib.import_module("caseclosed.main")
    module = importlib.reload(module)
    fastapi_app = getattr(module, "app", None)

    assert fastapi_app is not None, "caseclosed.main must expose a FastAPI app."
    return fastapi_app


@pytest.fixture
def client(app) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def certificate_headers() -> dict[str, str]:
    return {"X-Client-Cert-Fingerprint": TEST_CERTIFICATE_FINGERPRINT}


def sqlite_table_names(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def insert_phase_2_job(
    database_path: Path,
    *,
    job_id: str,
    status: str,
    job_type: str = "gmail_sync",
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, job_type, priority, status, payload_json, retry_count,
                max_retries, created_at, updated_at
            ) VALUES (?, ?, 100, ?, '{}', 0, 3, ?, ?)
            """,
            (
                job_id,
                job_type,
                status,
                "2026-05-22T10:00:00+09:00",
                "2026-05-22T10:00:00+09:00",
            ),
        )
        connection.commit()


def insert_phase_2_external_operation(
    database_path: Path,
    *,
    operation_id: str,
    status: str,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO external_operations (
                id, operation_type, status, idempotency_key,
                request_payload_hash, request_payload_json, external_service,
                unknown_at, unknown_reason, manual_resolution_required,
                created_at, updated_at
            ) VALUES (?, 'gmail_send', ?, ?, 'payload-hash', '{}', 'gmail',
                ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                status,
                f"gmail_send:{operation_id}",
                "2026-05-22T10:00:00+09:00" if status == "unknown" else None,
                "network result unknown" if status == "unknown" else None,
                1 if status == "unknown" else 0,
                "2026-05-22T10:00:00+09:00",
                "2026-05-22T10:00:00+09:00",
            ),
        )
        connection.commit()


def insert_unresolved_contact_email(
    database_path: Path,
    *,
    email_address: str,
    email_address_id: str = "email_unresolved",
) -> None:
    normalized_email_address = email_address.strip().lower()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO contact_email_addresses (
                id, contact_id, email_address, normalized_email_address,
                resolution_status, status, has_inbound_message_history,
                is_primary, source, first_seen_at,
                last_seen_at, created_at, updated_at, version
            ) VALUES (?, NULL, ?, ?, 'unresolved', 'active', 1, 0, 'gmail', ?, ?, ?, ?, 1)
            """,
            (
                email_address_id,
                email_address,
                normalized_email_address,
                "2026-05-23T09:00:00+09:00",
                "2026-05-23T10:00:00+09:00",
                "2026-05-23T09:00:00+09:00",
                "2026-05-23T10:00:00+09:00",
            ),
        )
        connection.commit()
