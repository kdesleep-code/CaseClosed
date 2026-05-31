from __future__ import annotations

import base64
import json
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from caseclosed.storage import decoded_zip_info_path


def png_bytes(width: int, height: int) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), color=(128, 96, 64)).save(output, format="PNG")
    return output.getvalue()


def simple_pdf_bytes(text_lines: list[str]) -> bytes:
    content = "BT /F1 12 Tf 72 720 Td "
    content += " T* ".join(f"({line}) Tj" for line in text_lines)
    content += " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /Resources "
            b"<< /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] "
            b"/Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n"
            f"{content}\nendstream"
        ).encode("latin-1"),
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + payload + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


def test_file_icon_settings_can_be_managed(client, database_path: Path) -> None:
    svg_base64 = (
        "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
    )
    create_response = client.post(
        "/api/v1/storage/file-icons",
        json={
            "icon_filename": "doc.svg",
            "icon_content_type": "image/svg+xml",
            "icon_data_base64": svg_base64,
            "extensions": [".docx", "pdf, txt", "*.md"],
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()["data"]["file_icon"]
    assert created["icon_filename"] == "doc.svg"
    assert created["icon_content_type"] == "image/svg+xml"
    assert created["storage_object_id"].startswith("storage_object_")
    assert created["icon_url"] == f"/api/v1/storage/objects/{created['storage_object_id']}/content"
    assert created["extensions"] == [".docx", ".pdf", ".txt", ".md"]
    with sqlite3.connect(database_path) as connection:
        icon_row = connection.execute(
            "SELECT scope, storage_path FROM storage_objects WHERE id = ?",
            (created["storage_object_id"],),
        ).fetchone()
    assert icon_row == ("file-icons", f"file-icons/{created['storage_object_id'][15:17]}/{created['storage_object_id']}.svg")

    update_response = client.patch(
        f"/api/v1/storage/file-icons/{created['id']}",
        json={
            "icon_filename": "doc.png",
            "icon_content_type": "image/png",
            "icon_data_base64": base64.b64encode(png_bytes(96, 96)).decode("ascii"),
            "extensions": ["xlsx csv"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]["file_icon"]
    assert updated["icon_content_type"] == "image/webp"
    assert updated["storage_object_id"] != created["storage_object_id"]
    assert updated["extensions"] == [".xlsx", ".csv"]
    assert client.get(created["icon_url"]).status_code == 404

    list_response = client.get("/api/v1/storage/file-icons")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [
        created["id"]
    ]

    upload_response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "sheet.xlsx",
            "content_type": "application/octet-stream",
            "data_base64": base64.b64encode(b"file with custom icon").decode("ascii"),
        },
    )
    listed_objects = client.get("/api/v1/storage/objects").json()["data"]["items"]
    listed_object = next(
        item for item in listed_objects if item["id"] == upload_response.json()["data"]["storage_object"]["id"]
    )
    assert listed_object["file_icon_setting_id"] == created["id"]
    assert listed_object["file_icon_url"] == updated["icon_url"]

    delete_response = client.delete(f"/api/v1/storage/file-icons/{created['id']}")
    assert delete_response.status_code == 200
    assert client.get(updated["icon_url"]).status_code == 404
    assert client.get("/api/v1/storage/file-icons").json()["data"]["items"] == []


def test_temporary_object_upload_stores_file(
    client,
    database_path: Path,
) -> None:
    payload_bytes = b"temporary payload"

    response = client.post(
        "/api/v1/storage/tmp",
        json={
            "filename": "note.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(payload_bytes).decode("ascii"),
        },
    )

    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    assert storage_object["scope"] == "tmp"
    assert storage_object["location_id"] == "storage_location_internal"
    assert storage_object["original_filename"] == "note.txt"
    assert storage_object["content_type"] == "text/plain"
    assert storage_object["byte_size"] == len(payload_bytes)

    content_response = client.get(storage_object["url"])
    assert content_response.status_code == 200
    assert content_response.content == payload_bytes
    assert content_response.headers["content-type"].startswith("text/plain")
    assert "inline" in content_response.headers["content-disposition"]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()

    assert row[0].startswith("tmp/")


def test_storage_objects_can_be_listed_and_managed_object_uploaded(
    client,
    database_path: Path,
) -> None:
    client.post(
        "/api/v1/storage/tmp",
        json={
            "filename": "hidden.tmp",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"internal tmp").decode("ascii"),
        },
    )
    payload_bytes = b"storage managed content"

    response = client.post(
        "/api/v1/storage/objects",
        json={
            "filename": "managed.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(payload_bytes).decode("ascii"),
        },
    )

    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    assert storage_object["scope"] == "managed"
    assert storage_object["location_id"] == "storage_location_internal"
    assert storage_object["llm_input_allowed"] is False
    assert storage_object["source_type"] == "direct_upload"
    assert storage_object["file_updated_at"] == storage_object["updated_at"]
    assert storage_object["source_message_id"] is None

    objects_response = client.get("/api/v1/storage/objects")
    assert objects_response.status_code == 200
    assert [item["id"] for item in objects_response.json()["data"]["items"]] == [
        storage_object["id"]
    ]

    locations_response = client.get("/api/v1/storage/locations")
    assert locations_response.status_code == 200
    location = locations_response.json()["data"]["items"][0]
    assert location["id"] == "storage_location_internal"
    assert location["object_count"] == 1
    assert location["active_byte_size"] == len(payload_bytes)

    detail_response = client.get(f"/api/v1/storage/objects/{storage_object['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["storage_object"]["id"] == storage_object["id"]

    content_response = client.get(storage_object["url"])
    assert content_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM storage_operation_history
            WHERE storage_object_id = ?
              AND operation_type = 'viewed'
            """,
            (storage_object["id"],),
        ).fetchone() == (1,)
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM storage_operation_history
            WHERE storage_object_id = ?
              AND operation_type = 'downloaded'
            """,
            (storage_object["id"],),
        ).fetchone() == (0,)

    download_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/download"
    )
    assert download_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM storage_operation_history
            WHERE storage_object_id = ?
              AND operation_type = 'downloaded'
            """,
            (storage_object["id"],),
        ).fetchone() == (1,)

    patch_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-input",
        json={"llm_input_allowed": True},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["data"]["storage_object"]["llm_input_allowed"] is True

    objects_response = client.get("/api/v1/storage/objects")
    assert (
        objects_response.json()["data"]["items"][0]["llm_input_allowed"] is True
    )

    with sqlite3.connect(database_path) as connection:
        storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert (database_path.parent / "storage" / storage_path).is_file()

    delete_response = client.delete(f"/api/v1/storage/objects/{storage_object['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted_storage_object_id"] == storage_object["id"]
    assert delete_response.json()["data"]["restored_storage_object"] is None
    with sqlite3.connect(database_path) as connection:
        status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
        history_rows = connection.execute(
            """
            SELECT operation_type, original_filename, byte_size
            FROM storage_operation_history
            WHERE storage_object_id = ?
            ORDER BY created_at, id
            """,
            (storage_object["id"],),
        ).fetchall()
    assert status == "deleted"
    assert history_rows == [
        ("created", "managed.txt", len(payload_bytes)),
        ("viewed", "managed.txt", len(payload_bytes)),
        ("downloaded", "managed.txt", len(payload_bytes)),
        ("llm_input_updated", "managed.txt", len(payload_bytes)),
        ("deleted", "managed.txt", len(payload_bytes)),
    ]
    assert not (database_path.parent / "storage" / storage_path).exists()


def test_managed_object_upload_accepts_multipart_file(
    client,
    database_path: Path,
) -> None:
    payload_bytes = b"multipart managed content"

    response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("managed-upload.txt", payload_bytes, "text/plain")},
    )

    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    assert storage_object["scope"] == "managed"
    assert storage_object["original_filename"] == "managed-upload.txt"
    assert storage_object["content_type"] == "text/plain"
    assert storage_object["byte_size"] == len(payload_bytes)
    assert storage_object["source_type"] == "direct_upload"

    content_response = client.get(storage_object["url"])
    assert content_response.status_code == 200
    assert content_response.content == payload_bytes

    with sqlite3.connect(database_path) as connection:
        storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert (database_path.parent / "storage" / storage_path).is_file()


def test_managed_object_can_be_updated_with_version_history(
    client,
    database_path: Path,
) -> None:
    first_payload = b"first version"
    second_payload = b"second version"

    response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("paper.txt", first_payload, "text/plain")},
    )
    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    storage_object_id = storage_object["id"]

    update_response = client.post(
        f"/api/v1/storage/objects/{storage_object_id}/versions/upload",
        files={"file": ("paper-v2.txt", second_payload, "text/plain")},
    )
    assert update_response.status_code == 200
    data = update_response.json()["data"]
    updated_object = data["storage_object"]
    previous_version = data["version"]
    assert updated_object["id"] == storage_object_id
    assert updated_object["original_filename"] == "paper-v2.txt"
    assert updated_object["byte_size"] == len(second_payload)
    assert updated_object["file_updated_at"] == updated_object["updated_at"]
    assert previous_version["version_number"] == 1
    assert previous_version["original_filename"] == "paper.txt"
    assert previous_version["byte_size"] == len(first_payload)
    assert previous_version["created_at"] == storage_object["file_updated_at"]
    assert previous_version["url"].endswith(f"/versions/{previous_version['id']}/content")
    assert previous_version["download_url"].endswith(
        f"/versions/{previous_version['id']}/download"
    )

    content_response = client.get(updated_object["url"])
    assert content_response.status_code == 200
    assert content_response.content == second_payload

    versions_response = client.get(
        f"/api/v1/storage/objects/{storage_object_id}/versions"
    )
    assert versions_response.status_code == 200
    assert versions_response.json()["data"]["items"] == [previous_version]

    with sqlite3.connect(database_path) as connection:
        current_path, current_sha = connection.execute(
            "SELECT storage_path, sha256_hex FROM storage_objects WHERE id = ?",
            (storage_object_id,),
        ).fetchone()
        version_path, version_sha = connection.execute(
            """
            SELECT storage_path, sha256_hex
            FROM storage_object_versions
            WHERE storage_object_id = ?
            """,
            (storage_object_id,),
        ).fetchone()
        history_rows = connection.execute(
            """
            SELECT operation_type
            FROM storage_operation_history
            WHERE storage_object_id = ?
            ORDER BY created_at, id
            """,
            (storage_object_id,),
        ).fetchall()

    assert current_sha != version_sha
    assert (database_path.parent / "storage" / current_path).read_bytes() == second_payload
    assert (database_path.parent / "storage" / version_path).read_bytes() == first_payload
    assert history_rows == [("uploaded",), ("updated",), ("viewed",)]

    version_content_response = client.get(previous_version["url"])
    assert version_content_response.status_code == 200
    assert version_content_response.content == first_payload
    assert "inline" in version_content_response.headers["content-disposition"]

    version_download_response = client.get(previous_version["download_url"])
    assert version_download_response.status_code == 200
    assert version_download_response.content == first_payload
    assert "attachment" in version_download_response.headers["content-disposition"]

    delete_response = client.delete(f"/api/v1/storage/objects/{storage_object_id}")
    assert delete_response.status_code == 200
    assert not (database_path.parent / "storage" / current_path).exists()
    assert not (database_path.parent / "storage" / version_path).exists()


def test_managed_object_update_skips_duplicate_content(
    client,
    database_path: Path,
) -> None:
    payload = b"same payload"

    response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("paper.txt", payload, "text/plain")},
    )
    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    storage_object_id = storage_object["id"]

    update_response = client.post(
        f"/api/v1/storage/objects/{storage_object_id}/versions/upload",
        files={"file": ("paper-renamed.txt", payload, "text/plain")},
    )

    assert update_response.status_code == 200
    data = update_response.json()["data"]
    assert data["skipped"] is True
    assert data["skip_reason"] == "duplicate_content"
    assert data["version"] is None
    assert data["storage_object"]["original_filename"] == "paper.txt"
    assert data["storage_object"]["file_updated_at"] == storage_object["file_updated_at"]

    versions_response = client.get(
        f"/api/v1/storage/objects/{storage_object_id}/versions"
    )
    assert versions_response.status_code == 200
    assert versions_response.json()["data"]["items"] == []

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT original_filename, version
            FROM storage_objects
            WHERE id = ?
            """,
            (storage_object_id,),
        ).fetchone()
        version_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM storage_object_versions
            WHERE storage_object_id = ?
            """,
            (storage_object_id,),
        ).fetchone()[0]
        history_rows = connection.execute(
            """
            SELECT operation_type
            FROM storage_operation_history
            WHERE storage_object_id = ?
            ORDER BY created_at, id
            """,
            (storage_object_id,),
        ).fetchall()

    assert row == ("paper.txt", 1)
    assert version_count == 0
    assert history_rows == [("uploaded",), ("update_skipped",)]


def test_selected_and_older_storage_object_versions_can_be_deleted(
    client,
    database_path: Path,
) -> None:
    first_payload = b"first version"
    second_payload = b"second version"
    third_payload = b"third version"

    response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("paper.txt", first_payload, "text/plain")},
    )
    assert response.status_code == 200
    storage_object_id = response.json()["data"]["storage_object"]["id"]

    first_update_response = client.post(
        f"/api/v1/storage/objects/{storage_object_id}/versions/upload",
        files={"file": ("paper-v2.txt", second_payload, "text/plain")},
    )
    assert first_update_response.status_code == 200
    first_version = first_update_response.json()["data"]["version"]

    second_update_response = client.post(
        f"/api/v1/storage/objects/{storage_object_id}/versions/upload",
        files={"file": ("paper-v3.txt", third_payload, "text/plain")},
    )
    assert second_update_response.status_code == 200
    second_version = second_update_response.json()["data"]["version"]

    with sqlite3.connect(database_path) as connection:
        first_version_path = connection.execute(
            "SELECT storage_path FROM storage_object_versions WHERE id = ?",
            (first_version["id"],),
        ).fetchone()[0]
        second_version_path = connection.execute(
            "SELECT storage_path FROM storage_object_versions WHERE id = ?",
            (second_version["id"],),
        ).fetchone()[0]

    delete_response = client.delete(
        f"/api/v1/storage/objects/{storage_object_id}"
        f"/versions/{second_version['id']}/older"
    )

    assert delete_response.status_code == 200
    data = delete_response.json()["data"]
    assert data["deleted_version_ids"] == [first_version["id"], second_version["id"]]
    assert data["deleted_version_count"] == 2
    assert not (database_path.parent / "storage" / first_version_path).exists()
    assert not (database_path.parent / "storage" / second_version_path).exists()

    versions_response = client.get(
        f"/api/v1/storage/objects/{storage_object_id}/versions"
    )
    assert versions_response.status_code == 200
    assert versions_response.json()["data"]["items"] == []

    with sqlite3.connect(database_path) as connection:
        history_rows = connection.execute(
            """
            SELECT operation_type
            FROM storage_operation_history
            WHERE storage_object_id = ?
            ORDER BY created_at, id
            """,
            (storage_object_id,),
        ).fetchall()

    assert history_rows == [
        ("uploaded",),
        ("updated",),
        ("updated",),
        ("versions_deleted",),
    ]


def test_storage_object_llm_digest_can_be_prepared_and_read(
    client,
    database_path: Path,
    monkeypatch,
) -> None:
    import importlib

    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    storage_module = importlib.import_module("caseclosed.storage")

    class CapturingFileSummaryProvider:
        provider_name = "test"
        model_name = "file-summary-test"

        def __init__(self) -> None:
            self.calls = []

        def complete_json(self, *, function_type, input_payload):
            self.calls.append(dict(input_payload))
            output = {
                "schema_version": "1.0",
                "file_description": "会議メモの主要事項を圧縮したファイルです。",
                "summary_points": [
                    "2026年5月30日の会議メモ。",
                    "予算と締切の確認が含まれる。",
                ],
                "llm_digest": "会議メモ。予算は30万円。締切は2026-06-10。",
                "structured_digest": {
                    "document_type": "meeting_note",
                    "facts": ["予算は30万円。"],
                    "entities": ["CaseClosed"],
                    "dates": ["2026-06-10"],
                    "numbers": ["30万円"],
                    "action_items": ["締切までに確認する。"],
                    "structure_notes": ["plain text"],
                },
                "coverage": {
                    "source_kind": input_payload["source_kind"],
                    "read_scope": input_payload["read_scope"],
                    "truncated": input_payload["truncated"],
                    "limitations": input_payload["limitations"],
                },
                "token_estimate": 32,
                "reasoning_summary": "Test digest.",
                "warnings": [],
            }
            return provider_module.LlmProviderResponse(
                output=output,
                output_preview=output["file_description"],
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
                estimated_cost=0.01,
            )

    provider = CapturingFileSummaryProvider()
    monkeypatch.setattr(
        storage_module,
        "build_file_summary_provider",
        lambda: provider,
    )
    upload_response = client.post(
        "/api/v1/storage/objects/upload",
        files={
            "file": (
                "meeting.txt",
                "CaseClosed meeting\nBudget: 300000 yen\nDeadline: 2026-06-10".encode(),
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    allow_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-input",
        json={"llm_input_allowed": True},
    )
    assert allow_response.status_code == 200

    missing_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest"
    )
    assert missing_response.status_code == 200
    assert missing_response.json()["data"]["summary"] is None

    digest_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest",
        json={},
    )

    assert digest_response.status_code == 200
    summary = digest_response.json()["data"]["summary"]
    assert summary["file_description"] == "会議メモの主要事項を圧縮したファイルです。"
    assert summary["summary_points"] == [
        "2026年5月30日の会議メモ。",
        "予算と締切の確認が含まれる。",
    ]
    assert summary["llm_digest"] == "会議メモ。予算は30万円。締切は2026-06-10。"
    assert summary["token_estimate"] == 32
    assert provider.calls[0]["source_kind"] == "text"
    assert "Budget: 300000 yen" in provider.calls[0]["source_text"]

    read_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest"
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["summary"]["id"] == summary["id"]

    with sqlite3.connect(database_path) as connection:
        summary_row = connection.execute(
            """
            SELECT storage_object_id, source_sha256_hex, llm_digest, llm_run_id
            FROM file_summaries
            WHERE id = ?
            """,
            (summary["id"],),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT function_type, prompt_tokens, completion_tokens, total_tokens
            FROM llm_runs
            WHERE id = ?
            """,
            (summary_row[3],),
        ).fetchone()
        operation_detail = connection.execute(
            """
            SELECT details_json
            FROM storage_operation_history
            WHERE operation_type = 'llm_digest_prepared'
            """
        ).fetchone()[0]

    assert summary_row[0] == storage_object["id"]
    assert summary_row[2] == "会議メモ。予算は30万円。締切は2026-06-10。"
    assert llm_run_row == ("file_summary", 11, 7, 18)
    assert json.loads(operation_detail)["file_summary_id"] == summary["id"]


def test_storage_object_llm_digest_respects_llm_block(
    client,
) -> None:
    upload_response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("blocked.txt", b"blocked", "text/plain")},
    )
    storage_object = upload_response.json()["data"]["storage_object"]
    patch_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-input",
        json={"llm_input_allowed": False},
    )
    assert patch_response.status_code == 200

    digest_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest",
        json={},
    )

    assert digest_response.status_code == 409
    assert digest_response.json()["error"]["code"] == "LLM_INPUT_BLOCKED"


def test_storage_object_llm_digest_tracks_versions_and_diff(
    client,
    monkeypatch,
) -> None:
    import importlib

    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    storage_module = importlib.import_module("caseclosed.storage")

    class VersionedFileSummaryProvider:
        provider_name = "test"
        model_name = "versioned-file-summary-test"

        def __init__(self) -> None:
            self.calls = []

        def complete_json(self, *, function_type, input_payload):
            self.calls.append(dict(input_payload))
            if input_payload["generation_mode"] == "incremental_from_digest":
                marker = "second"
                assert input_payload["source_text"] == ""
                incremental_source = input_payload["incremental_source"]
                assert incremental_source["base_llm_digest"] == "first digest body"
                assert incremental_source["diffs"][0]["added_lines"] == ["new only"]
                assert incremental_source["diffs"][0]["removed_lines"] == ["old only"]
            else:
                marker = "first"
                assert "old only" in input_payload["source_text"]
            output = {
                "schema_version": "1.0",
                "file_description": f"{marker} digest",
                "summary_points": [f"{marker} point"],
                "llm_digest": f"{marker} digest body",
                "structured_digest": {},
                "coverage": {},
                "token_estimate": 12,
                "reasoning_summary": "Test digest.",
                "warnings": [],
            }
            return provider_module.LlmProviderResponse(
                output=output,
                output_preview=output["file_description"],
            )

    provider = VersionedFileSummaryProvider()
    monkeypatch.setattr(
        storage_module,
        "build_file_summary_provider",
        lambda: provider,
    )
    upload_response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("notes.txt", b"line one\nold only", "text/plain")},
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-input",
        json={"llm_input_allowed": True},
    )

    first_digest_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest",
        json={},
    )
    assert first_digest_response.status_code == 200
    first_summary = first_digest_response.json()["data"]["summary"]
    assert first_summary["file_description"] == "first digest"

    update_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/versions/upload",
        files={"file": ("notes.txt", b"line one\nnew only", "text/plain")},
    )
    assert update_response.status_code == 200
    previous_version = update_response.json()["data"]["version"]

    stale_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest"
    )
    assert stale_response.status_code == 200
    stale_data = stale_response.json()["data"]
    assert stale_data["is_stale"] is True
    assert stale_data["summary"]["id"] == first_summary["id"]
    assert stale_data["summary"]["storage_object_version_id"] == previous_version["id"]
    assert stale_data["diff"]["previous_version_id"] == previous_version["id"]
    assert "new only" in stale_data["diff"]["added_lines"]
    assert "old only" in stale_data["diff"]["removed_lines"]

    second_digest_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest",
        json={},
    )
    assert second_digest_response.status_code == 200
    second_summary = second_digest_response.json()["data"]["summary"]
    assert second_summary["file_description"] == "second digest"
    assert second_digest_response.json()["data"]["is_stale"] is False
    assert [call["generation_mode"] for call in provider.calls] == [
        "full_source",
        "incremental_from_digest",
    ]

    old_version_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest"
        f"?version_id={previous_version['id']}"
    )
    assert old_version_response.status_code == 200
    old_version_data = old_version_response.json()["data"]
    assert old_version_data["is_stale"] is False
    assert old_version_data["summary"]["id"] == first_summary["id"]
    assert old_version_data["summary"]["id"] != second_summary["id"]
    assert old_version_data["diff"] is None


def test_storage_object_llm_digest_extracts_pdf_text(
    client,
    monkeypatch,
) -> None:
    import importlib

    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    storage_module = importlib.import_module("caseclosed.storage")

    captured_payloads = []

    class CapturingFileSummaryProvider:
        provider_name = "test"
        model_name = "pdf-summary-test"

        def complete_json(self, *, function_type, input_payload):
            captured_payloads.append(dict(input_payload))
            output = {
                "schema_version": "1.0",
                "file_description": "PDFから抽出した本文を圧縮したファイルです。",
                "summary_points": ["PDF本文に予算と締切が含まれる。"],
                "llm_digest": "PDF本文: Budget 300000 yen / Deadline 2026-06-10.",
                "structured_digest": {
                    "document_type": "pdf",
                    "facts": ["Budget 300000 yen"],
                    "entities": [],
                    "dates": ["2026-06-10"],
                    "numbers": ["300000 yen"],
                    "action_items": [],
                    "structure_notes": ["PDF text extraction"],
                },
                "coverage": {
                    "source_kind": input_payload["source_kind"],
                    "read_scope": input_payload["read_scope"],
                    "truncated": input_payload["truncated"],
                    "limitations": input_payload["limitations"],
                },
                "token_estimate": 24,
                "reasoning_summary": "PDF digest.",
                "warnings": [],
            }
            return provider_module.LlmProviderResponse(
                output=output,
                output_preview=output["file_description"],
            )

    monkeypatch.setattr(
        storage_module,
        "build_file_summary_provider",
        lambda: CapturingFileSummaryProvider(),
    )
    upload_response = client.post(
        "/api/v1/storage/objects/upload",
        files={
            "file": (
                "budget.pdf",
                simple_pdf_bytes(
                    [
                        "CaseClosed PDF Budget 300000 yen",
                        "Deadline 2026-06-10",
                    ]
                ),
                "application/pdf",
            )
        },
    )
    storage_object = upload_response.json()["data"]["storage_object"]
    client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-input",
        json={"llm_input_allowed": True},
    )

    digest_response = client.post(
        f"/api/v1/storage/objects/{storage_object['id']}/llm-digest",
        json={},
    )

    assert digest_response.status_code == 200
    assert captured_payloads[0]["source_kind"] == "pdf_text"
    assert captured_payloads[0]["read_scope"].startswith("pdf_text_extraction:")
    assert "Budget 300000 yen" in captured_payloads[0]["source_text"]
    assert "Deadline 2026-06-10" in captured_payloads[0]["source_text"]


def test_storage_object_archive_tree_lists_zip_without_extracting(
    client,
) -> None:
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("paper/main.tex", "hello")
        archive.writestr("paper/figures/plot.png", b"image")
        archive.writestr("README.md", "# README")

    response = client.post(
        "/api/v1/storage/objects/upload",
        files={
            "file": (
                "paper.zip",
                zip_buffer.getvalue(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]

    tree_response = client.get(
        f"/api/v1/storage/objects/{storage_object['id']}/archive-tree"
    )

    assert tree_response.status_code == 200
    data = tree_response.json()["data"]
    assert data["file_count"] == 3
    assert data["directory_count"] == 2
    assert "paper/" in data["tree_text"]
    assert "figures/" in data["tree_text"]
    assert "plot.png" in data["tree_text"]
    assert "main.tex" in data["tree_text"]
    assert "README.md" in data["tree_text"]
    assert data["truncated"] is False


def test_storage_directories_scope_list_and_uploads(
    client,
) -> None:
    create_response = client.post(
        "/api/v1/storage/directories",
        json={"name": "Project A", "parent_id": None},
    )
    assert create_response.status_code == 200
    directory = create_response.json()["data"]["directory"]
    assert directory["name"] == "Project A"
    assert directory["directory_kind"] == "normal"

    child_response = client.post(
        "/api/v1/storage/directories",
        json={"name": "Papers", "parent_id": directory["id"]},
    )
    assert child_response.status_code == 200
    child = child_response.json()["data"]["directory"]

    root_directories = client.get("/api/v1/storage/directories")
    assert root_directories.status_code == 200
    root_items = root_directories.json()["data"]["items"]
    assert directory["id"] in [item["id"] for item in root_items]
    case_directories = [item for item in root_items if item["directory_kind"] == "case"]
    assert any(item["case_id"] == "case_system_inbox" for item in case_directories)

    child_directories = client.get(
        f"/api/v1/storage/directories?parent_id={directory['id']}"
    )
    assert child_directories.status_code == 200
    assert [item["id"] for item in child_directories.json()["data"]["items"]] == [
        child["id"]
    ]
    assert [
        item["name"] for item in child_directories.json()["data"]["breadcrumbs"]
    ] == ["Project A"]

    upload_response = client.post(
        f"/api/v1/storage/objects/upload?directory_id={child['id']}",
        files={"file": ("inside.txt", b"inside", "text/plain")},
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] == child["id"]

    root_objects = client.get("/api/v1/storage/objects")
    assert root_objects.status_code == 200
    assert storage_object["id"] not in [
        item["id"] for item in root_objects.json()["data"]["items"]
    ]

    child_objects = client.get(f"/api/v1/storage/objects?directory_id={child['id']}")
    assert child_objects.status_code == 200
    assert [item["id"] for item in child_objects.json()["data"]["items"]] == [
        storage_object["id"]
    ]


def test_case_storage_directory_is_listed_and_protected(
    client,
) -> None:
    root_directories = client.get("/api/v1/storage/directories")

    assert root_directories.status_code == 200
    case_directory = next(
        item
        for item in root_directories.json()["data"]["items"]
        if item["case_id"] == "case_system_inbox"
    )
    assert case_directory["name"] == "Bucket"
    assert case_directory["directory_kind"] == "case"

    upload_response = client.post(
        f"/api/v1/storage/objects/upload?directory_id={case_directory['id']}",
        files={"file": ("case-note.txt", b"case note", "text/plain")},
    )
    assert upload_response.status_code == 200
    assert (
        upload_response.json()["data"]["storage_object"]["directory_id"]
        == case_directory["id"]
    )

    delete_response = client.delete(f"/api/v1/storage/directories/{case_directory['id']}")
    assert delete_response.status_code == 409
    assert delete_response.json()["error"]["code"] == "CASE_DIRECTORY_PROTECTED"


def test_storage_object_can_move_between_directories(
    client,
) -> None:
    directory = client.post(
        "/api/v1/storage/directories",
        json={"name": "Move Target", "parent_id": None},
    ).json()["data"]["directory"]
    upload_response = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("move.txt", b"move", "text/plain")},
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["directory_id"] is None

    move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": directory["id"]},
    )

    assert move_response.status_code == 200
    moved_object = move_response.json()["data"]["storage_object"]
    assert moved_object["directory_id"] == directory["id"]

    root_objects = client.get("/api/v1/storage/objects")
    assert root_objects.status_code == 200
    assert moved_object["id"] not in [
        item["id"] for item in root_objects.json()["data"]["items"]
    ]

    directory_objects = client.get(
        f"/api/v1/storage/objects?directory_id={directory['id']}"
    )
    assert directory_objects.status_code == 200
    assert [item["id"] for item in directory_objects.json()["data"]["items"]] == [
        moved_object["id"]
    ]

    root_move_response = client.patch(
        f"/api/v1/storage/objects/{storage_object['id']}/directory",
        json={"directory_id": None},
    )

    assert root_move_response.status_code == 200
    assert root_move_response.json()["data"]["storage_object"]["directory_id"] is None


def test_storage_object_search_uses_recursive_scope_source_subject_and_extension(
    client,
    database_path: Path,
) -> None:
    parent = client.post(
        "/api/v1/storage/directories",
        json={"name": "Research", "parent_id": None},
    ).json()["data"]["directory"]
    child = client.post(
        "/api/v1/storage/directories",
        json={"name": "Papers", "parent_id": parent["id"]},
    ).json()["data"]["directory"]
    pdf_object = client.post(
        f"/api/v1/storage/objects/upload?directory_id={child['id']}",
        files={"file": ("alpha.pdf", b"pdf", "application/pdf")},
    ).json()["data"]["storage_object"]
    csv_object = client.post(
        f"/api/v1/storage/objects/upload?directory_id={child['id']}",
        files={"file": ("data.csv", b"a,b\n1,2", "text/csv")},
    ).json()["data"]["storage_object"]
    root_object = client.post(
        "/api/v1/storage/objects/upload",
        files={"file": ("root.txt", b"root", "text/plain")},
    ).json()["data"]["storage_object"]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO gmail_threads (
                id, gmail_thread_id, subject_snapshot, first_message_at, last_message_at,
                created_at, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "thread_storage_search",
                "gmail_thread_storage_search",
                "Budget source",
                "2026-05-30T10:00:00+09:00",
                "2026-05-30T10:00:00+09:00",
                "2026-05-30T10:00:00+09:00",
                "2026-05-30T10:00:00+09:00",
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO gmail_messages (
                id, gmail_message_id, gmail_thread_id, thread_id, internal_date,
                received_at, subject, from_address, from_name, sender_address,
                reply_to_address, to_addresses_json, cc_addresses_json, bcc_addresses_json,
                message_id_header, in_reply_to_header, references_header, list_id, snippet,
                body_text, body_html, gmail_link, gmail_labels_json, external_starred,
                created_at, updated_at, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "mail_storage_search",
                "gmail_message_storage_search",
                "gmail_thread_storage_search",
                "thread_storage_search",
                None,
                "2026-05-30T10:00:00+09:00",
                "Budget Plan Source Mail",
                "sender@example.com",
                None,
                None,
                None,
                "[]",
                "[]",
                "[]",
                None,
                None,
                None,
                None,
                None,
                "Body",
                None,
                None,
                "[]",
                0,
                "2026-05-30T10:00:00+09:00",
                "2026-05-30T10:00:00+09:00",
                1,
            ),
        )
        connection.execute(
            "UPDATE storage_objects SET source_message_id = ?, source_type = ? WHERE id = ?",
            ("mail_storage_search", "mail_attachment", csv_object["id"]),
        )
        connection.commit()

    subject_response = client.get(
        f"/api/v1/storage/search/objects?directory_id={parent['id']}&q=budget"
    )
    assert subject_response.status_code == 200
    subject_data = subject_response.json()["data"]
    assert [item["id"] for item in subject_data["items"]] == [csv_object["id"]]
    assert subject_data["items"][0]["directory_path"] == ["Research", "Papers"]
    assert "csv" in subject_data["extensions"]
    assert root_object["id"] not in [item["id"] for item in subject_data["items"]]

    pdf_response = client.get(
        f"/api/v1/storage/search/objects?directory_id={parent['id']}&extension=pdf"
    )
    assert pdf_response.status_code == 200
    assert [item["id"] for item in pdf_response.json()["data"]["items"]] == [
        pdf_object["id"]
    ]

    root_response = client.get("/api/v1/storage/search/objects?sort=name")
    assert root_response.status_code == 200
    root_names = [
        item["original_filename"] for item in root_response.json()["data"]["items"]
    ]
    assert root_names == sorted(root_names, key=str.lower)


def test_storage_directory_delete_removes_children_and_objects(
    client,
    database_path: Path,
) -> None:
    parent = client.post(
        "/api/v1/storage/directories",
        json={"name": "Delete Me", "parent_id": None},
    ).json()["data"]["directory"]
    child = client.post(
        "/api/v1/storage/directories",
        json={"name": "Nested", "parent_id": parent["id"]},
    ).json()["data"]["directory"]
    upload_response = client.post(
        f"/api/v1/storage/objects/upload?directory_id={child['id']}",
        files={"file": ("nested.txt", b"nested", "text/plain")},
    )
    storage_object = upload_response.json()["data"]["storage_object"]
    with sqlite3.connect(database_path) as connection:
        storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()[0]

    delete_response = client.delete(f"/api/v1/storage/directories/{parent['id']}")

    assert delete_response.status_code == 200
    data = delete_response.json()["data"]
    assert data["deleted_directory_count"] == 2
    assert data["deleted_object_count"] == 1
    with sqlite3.connect(database_path) as connection:
        directory_statuses = connection.execute(
            "SELECT status FROM storage_directories WHERE id IN (?, ?) ORDER BY id",
            (parent["id"], child["id"]),
        ).fetchall()
        object_status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (storage_object["id"],),
        ).fetchone()[0]
    assert {row[0] for row in directory_statuses} == {"deleted"}
    assert object_status == "deleted"
    assert not (database_path.parent / "storage" / storage_path).exists()


def test_zip_info_path_recovers_cp932_names() -> None:
    raw_name = "繝・せ繝・雉・侭.txt".encode("cp932")
    mojibake_name = raw_name.decode("cp437")
    info = zipfile.ZipInfo(mojibake_name)
    info.flag_bits = 0

    assert decoded_zip_info_path(info) == "繝・せ繝・雉・侭.txt"


def test_contact_image_upload_stores_file_and_updates_avatar(
    client,
    database_path: Path,
) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Image Contact",
            "status": "active",
            "email_addresses": [
                {"email_address": "image.contact@example.com", "is_primary": True}
            ],
        },
    )
    contact_id = contact_response.json()["data"]["id"]
    image_bytes = png_bytes(900, 300)

    response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "avatar.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(image_bytes).decode("ascii"),
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    storage_object = data["storage_object"]
    assert storage_object["scope"] == "contact-images"
    assert storage_object["original_filename"] == "avatar.png"
    assert storage_object["content_type"] == "image/webp"
    assert storage_object["byte_size"] < len(image_bytes)
    assert data["contact"]["avatar_url"] == storage_object["url"]

    content_response = client.get(storage_object["url"])
    assert content_response.status_code == 200
    assert content_response.headers["content-type"].startswith("image/webp")
    with Image.open(BytesIO(content_response.content)) as resized_image:
        assert max(resized_image.size) == 256

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT contacts.avatar_url, storage_objects.storage_path
            FROM contacts, storage_objects
            WHERE contacts.id = ? AND storage_objects.id = ?
            """,
            (contact_id, storage_object["id"]),
        ).fetchone()

    assert row[0] == storage_object["url"]
    assert row[1].startswith("contact-images/")


def test_contact_image_upload_deletes_previous_contact_image(
    client,
    database_path: Path,
) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Replace Image Contact",
            "status": "active",
            "email_addresses": [],
        },
    )
    contact_id = contact_response.json()["data"]["id"]

    first_response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "first.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(png_bytes(600, 300)).decode("ascii"),
        },
    )
    first_storage_object = first_response.json()["data"]["storage_object"]

    second_response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "second.svg",
            "content_type": "image/svg+xml",
            "data_base64": base64.b64encode(
                b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" />'
            ).decode("ascii"),
        },
    )

    assert second_response.status_code == 200
    assert client.get(first_storage_object["url"]).status_code == 404

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status, storage_path FROM storage_objects WHERE id = ?",
            (first_storage_object["id"],),
        ).fetchone()

    assert row[0] == "deleted"
    assert not (database_path.parent / "storage" / row[1]).exists()


def test_contact_image_upload_preserves_svg(
    client,
) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Svg Contact",
            "status": "active",
            "email_addresses": [],
        },
    )
    contact_id = contact_response.json()["data"]["id"]
    image_bytes = b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" />'

    response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "avatar.svg",
            "content_type": "image/svg+xml",
            "data_base64": base64.b64encode(image_bytes).decode("ascii"),
        },
    )

    assert response.status_code == 200
    storage_object = response.json()["data"]["storage_object"]
    assert storage_object["content_type"] == "image/svg+xml"
    assert storage_object["byte_size"] == len(image_bytes)


def test_contact_image_upload_rejects_non_image(
    client,
) -> None:
    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Image Reject Contact",
            "status": "active",
            "email_addresses": [],
        },
    )
    contact_id = contact_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/storage/contacts/{contact_id}/image",
        json={
            "filename": "avatar.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"not image").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert response.json()["ok"] is False
