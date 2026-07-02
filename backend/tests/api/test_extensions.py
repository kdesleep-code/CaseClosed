from __future__ import annotations

import base64
import sys
from pathlib import Path


def create_case(client, name: str = "Extension Case") -> dict[str, object]:
    response = client.post(
        "/api/v1/cases",
        json={"name": name, "progress_status": "in_progress", "ball_status": "user"},
    )
    assert response.status_code == 200
    return response.json()["data"]["case"]


def ingest_mail(
    client,
    *,
    gmail_message_id: str,
    gmail_thread_id: str,
    from_address: str,
    subject: str,
    received_at: str,
    body_text: str,
) -> str:
    response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "message_id_header": f"<{gmail_message_id}@example.com>",
            "from_address": from_address,
            "subject": subject,
            "received_at": received_at,
            "body_text": body_text,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["message_id"]


def test_default_extension_template_is_registered(client) -> None:
    response = client.get("/api/v1/extensions")
    assert response.status_code == 200
    extensions = response.json()["data"]["items"]
    template = next(
        item for item in extensions if item["slug"] == "caseclosed-extension-template"
    )
    assert template["name"] == "CaseClosed Extension Template"
    assert template["source"] == "default"
    supervise_template = next(
        item for item in extensions if item["slug"] == "supervise-case-template"
    )
    assert supervise_template["name"] == "Supervise Case Template"
    assert supervise_template["source"] == "default"

    genres_response = client.get("/api/v1/cases/genres")
    assert genres_response.status_code == 200
    supervise_genre = next(
        item for item in genres_response.json()["data"]["items"] if item["title"] == "Supervise"
    )
    assert supervise_genre["template_extension_id"] == supervise_template["id"]


def test_case_template_extension_can_be_linked_to_genre(client, tmp_path: Path) -> None:
    manifest = {
        "slug": "genre-template-test",
        "name": "Genre Template Test",
        "command": [sys.executable, "-c", "import time; time.sleep(60)"],
        "tags": ["case-template"],
    }
    register_response = client.post(
        "/api/v1/extensions/register",
        json={"root_path": str(tmp_path), "manifest": manifest},
    )
    assert register_response.status_code == 200
    extension = register_response.json()["data"]["extension"]

    create_response = client.post(
        "/api/v1/cases/genres",
        json={
            "title": "Template Genre",
            "color_hex": "#88ccff",
            "template_extension_id": extension["id"],
            "template_context": {"mode": "case_template"},
        },
    )
    assert create_response.status_code == 200
    genre = create_response.json()["data"]["genre"]
    assert genre["template_extension_id"] == extension["id"]
    assert genre["template_context"] == {"mode": "case_template"}

    update_response = client.patch(
        f"/api/v1/cases/genres/{genre['id']}",
        json={"template_extension_id": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["genre"]["template_extension_id"] is None


def test_extension_can_register_start_use_case_api_and_stop(client, tmp_path: Path) -> None:
    case = create_case(client)
    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_extension_report_1",
        gmail_thread_id="thread_extension_report",
        from_address="student@example.com",
        subject="Report Submission",
        received_at="2026-06-10T10:00:00+09:00",
        body_text="This is a report body for extension search.",
    )
    ingest_mail(
        client,
        gmail_message_id="gmail_extension_report_2",
        gmail_thread_id="thread_extension_report_unlinked",
        from_address="student2@example.com",
        subject="Report Submission",
        received_at="2026-06-10T10:05:00+09:00",
        body_text="This is an unlinked report body for extension all-mail search.",
    )
    assign_response = client.post(
        f"/api/v1/mails/{message_id}/case-links",
        json={"case_id": case["id"]},
    )
    assert assign_response.status_code == 200
    manifest = {
        "slug": "mail-report-grader-test",
        "name": "Mail Report Grader Test",
        "description": "Test extension.",
        "command": [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
        "url_path": "/",
        "tags": ["grading"],
    }

    register_response = client.post(
        "/api/v1/extensions/register",
        json={"root_path": str(tmp_path), "manifest": manifest},
    )
    assert register_response.status_code == 200
    extension = register_response.json()["data"]["extension"]
    assert extension["slug"] == "mail-report-grader-test"
    assert extension["name"] == "Mail Report Grader Test"

    start_response = client.post(
        f"/api/v1/extensions/{extension['id']}/start",
        json={"case_id": case["id"], "context": {"assignment": "report-1"}},
    )
    assert start_response.status_code == 200
    start_data = start_response.json()["data"]
    instance = start_data["instance"]
    token = start_data["extension_token"]
    assert instance["case_id"] == case["id"]
    assert instance["status"] == "running"
    assert isinstance(instance["process_id"], int)
    assert start_data["open_url"] == (
        f"/api/v1/extensions/instances/{instance['id']}/proxy/"
    )
    assert instance["open_url"] == start_data["open_url"]
    assert "127.0.0.1" not in start_data["open_url"]

    reused_response = client.post(
        f"/api/v1/extensions/{extension['id']}/start",
        json={"case_id": case["id"], "idle_timeout_seconds": 1200},
    )
    assert reused_response.status_code == 200
    reused_data = reused_response.json()["data"]
    assert reused_data["reused"] is True
    assert reused_data["instance"]["id"] == instance["id"]
    assert reused_data["open_url"] == start_data["open_url"]
    assert reused_data["instance"]["idle_timeout_seconds"] == 1200

    headers = {"X-CaseClosed-Extension-Token": token}
    context_response = client.get("/api/v1/extension-api/context", headers=headers)
    assert context_response.status_code == 200
    assert context_response.json()["data"]["instance"]["launch_context"]["context"] == {
        "assignment": "report-1",
    }

    recontext_response = client.post(
        f"/api/v1/extensions/{extension['id']}/start",
        json={"case_id": case["id"], "context": {"assignment": "report-2"}},
    )
    assert recontext_response.status_code == 200
    assert recontext_response.json()["data"]["reused"] is True
    context_response = client.get("/api/v1/extension-api/context", headers=headers)
    assert context_response.status_code == 200
    assert context_response.json()["data"]["instance"]["launch_context"]["context"] == {
        "assignment": "report-2",
    }

    case_response = client.get("/api/v1/extension-api/case", headers=headers)
    assert case_response.status_code == 200
    assert case_response.json()["data"]["case"]["id"] == case["id"]

    mails_response = client.get(
        "/api/v1/extension-api/mails?q=report&include_body=true",
        headers=headers,
    )
    assert mails_response.status_code == 200
    mails = mails_response.json()["data"]["items"]
    assert [item["subject"] for item in mails] == ["Report Submission"]
    assert mails[0]["body_text"] == "This is a report body for extension search."

    all_mails_response = client.get(
        "/api/v1/extension-api/mails?scope=all&q=report&include_body=true",
        headers=headers,
    )
    assert all_mails_response.status_code == 200
    all_mails = all_mails_response.json()["data"]["items"]
    assert len(all_mails) == 2
    assert {item["from_address"] for item in all_mails} == {
        "student@example.com",
        "student2@example.com",
    }

    upload_response = client.post(
        "/api/v1/extension-api/case/files",
        headers=headers,
        json={
            "filename": "grading-result.csv",
            "content_type": "text/csv",
            "data_base64": base64.b64encode(b"student,score\nA,90\n").decode("ascii"),
        },
    )
    assert upload_response.status_code == 200
    storage_object = upload_response.json()["data"]["storage_object"]
    assert storage_object["original_filename"] == "grading-result.csv"
    assert storage_object["source_type"] == "extension"

    version_upload_response = client.post(
        "/api/v1/extension-api/case/files",
        headers=headers,
        json={
            "filename": "grading-result.csv",
            "content_type": "text/csv",
            "data_base64": base64.b64encode(b"student,score\nA,95\n").decode("ascii"),
        },
    )
    assert version_upload_response.status_code == 200
    version_upload_data = version_upload_response.json()["data"]
    assert version_upload_data["storage_object"]["id"] == storage_object["id"]
    assert version_upload_data["version"]["version_number"] == 1
    assert version_upload_data["skipped"] is False

    duplicate_upload_response = client.post(
        "/api/v1/extension-api/case/files",
        headers=headers,
        json={
            "filename": "grading-result.csv",
            "content_type": "text/csv",
            "data_base64": base64.b64encode(b"student,score\nA,95\n").decode("ascii"),
        },
    )
    assert duplicate_upload_response.status_code == 200
    duplicate_upload_data = duplicate_upload_response.json()["data"]
    assert duplicate_upload_data["storage_object"]["id"] == storage_object["id"]
    assert duplicate_upload_data["version"] is None
    assert duplicate_upload_data["skipped"] is True
    assert duplicate_upload_data["skip_reason"] == "duplicate_content"

    files_response = client.get("/api/v1/extension-api/case/files", headers=headers)
    assert files_response.status_code == 200
    files = files_response.json()["data"]["items"]
    filenames = {item["original_filename"] for item in files}
    assert "grading-result.csv" in filenames
    assert sum(1 for item in files if item["original_filename"] == "grading-result.csv") == 1

    stop_response = client.post(f"/api/v1/extensions/instances/{instance['id']}/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["data"]["instance"]["status"] == "stopped"

    logs_response = client.get("/api/v1/logs?q=extension&types=audit")
    assert logs_response.status_code == 200
    action_types = {
        item["category"]
        for item in logs_response.json()["data"]["items"]
    }
    assert {
        "extension.registered",
        "extension.started",
        "extension.reused",
        "extension.case_context_read",
        "extension.mails_listed",
        "extension.case_files_listed",
        "extension.case_file_uploaded",
        "extension.case_file_version_added",
        "extension.case_file_upload_skipped",
        "extension.stopped",
    } <= action_types


def test_extension_api_can_create_cases_and_search_contacts_without_case_context(client, tmp_path: Path) -> None:
    genre_response = client.post(
        "/api/v1/cases/genres",
        json={"title": "Template Genre", "color_hex": "#88ccff"},
    )
    assert genre_response.status_code == 200
    genre = genre_response.json()["data"]["genre"]

    contact_response = client.post(
        "/api/v1/contacts",
        json={
            "display_name": "Ada Lovelace",
            "kind": "person",
            "status": "active",
            "tags": ["template-contact"],
            "email_addresses": [
                {"email_address": "ada@example.com", "is_primary": True},
            ],
        },
    )
    assert contact_response.status_code == 200

    manifest = {
        "slug": "case-template-extension-test",
        "name": "Case Template Extension Test",
        "description": "Test extension for case template APIs.",
        "command": [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
        "url_path": "/",
        "tags": ["templates"],
    }
    register_response = client.post(
        "/api/v1/extensions/register",
        json={"root_path": str(tmp_path), "manifest": manifest},
    )
    assert register_response.status_code == 200
    extension = register_response.json()["data"]["extension"]

    start_response = client.post(
        f"/api/v1/extensions/{extension['id']}/start",
        json={"context": {"mode": "case-template"}},
    )
    assert start_response.status_code == 200
    start_data = start_response.json()["data"]
    instance = start_data["instance"]
    token = start_data["extension_token"]
    assert instance["case_id"] is None
    headers = {"X-CaseClosed-Extension-Token": token}

    genres_response = client.get("/api/v1/extension-api/cases/genres", headers=headers)
    assert genres_response.status_code == 200
    assert any(item["id"] == genre["id"] for item in genres_response.json()["data"]["items"])

    create_response = client.post(
        "/api/v1/extension-api/cases",
        headers=headers,
        json={
            "name": "Generated Case From Template",
            "description": "Created through the background extension API.",
            "genre_id": genre["id"],
            "progress_status": "not_started",
            "tags": ["from-template"],
        },
    )
    assert create_response.status_code == 200
    created_case = create_response.json()["data"]["case"]
    assert created_case["name"] == "Generated Case From Template"
    assert created_case["genre_id"] == genre["id"]
    assert created_case["tags"] == ["from-template"]

    cases_response = client.get(
        "/api/v1/extension-api/cases?q=Generated&tag=from-template",
        headers=headers,
    )
    assert cases_response.status_code == 200
    cases = cases_response.json()["data"]["items"]
    assert [item["id"] for item in cases] == [created_case["id"]]

    contacts_response = client.get(
        "/api/v1/extension-api/contacts?q=ada@example.com&tag=template-contact",
        headers=headers,
    )
    assert contacts_response.status_code == 200
    contacts = contacts_response.json()["data"]["items"]
    assert len(contacts) == 1
    assert contacts[0]["display_name"] == "Ada Lovelace"
    assert contacts[0]["email_addresses"][0]["email_address"] == "ada@example.com"

    stakeholder_response = client.post(
        f"/api/v1/extension-api/cases/{created_case['id']}/stakeholders",
        headers=headers,
        json={"contact_id": contacts[0]["id"], "role": "student"},
    )
    assert stakeholder_response.status_code == 200
    assert stakeholder_response.json()["data"]["stakeholder"]["role"] == "student"
    stakeholders_response = client.get(
        f"/api/v1/extension-api/cases/{created_case['id']}/stakeholders",
        headers=headers,
    )
    assert stakeholders_response.status_code == 200
    assert [
        item["contact_display_name"]
        for item in stakeholders_response.json()["data"]["items"]
    ] == ["Ada Lovelace"]
    assert stakeholders_response.json()["data"]["items"][0]["contact_tags"] == [
        "template-contact",
    ]

    auto_rule_response = client.post(
        f"/api/v1/extension-api/cases/{created_case['id']}/auto-assign-rules",
        headers=headers,
        json={"sender_email": "Ada@Example.com", "label": "Ada Lovelace"},
    )
    assert auto_rule_response.status_code == 200
    auto_rule_data = auto_rule_response.json()["data"]
    assert auto_rule_data["created"] is True
    assert auto_rule_data["rule"]["rule_value"] == "ada@example.com"
    duplicate_rule_response = client.post(
        f"/api/v1/extension-api/cases/{created_case['id']}/auto-assign-rules",
        headers=headers,
        json={"sender_email": "ada@example.com"},
    )
    assert duplicate_rule_response.status_code == 200
    assert duplicate_rule_response.json()["data"]["created"] is False

    no_context_case_response = client.get("/api/v1/extension-api/case", headers=headers)
    assert no_context_case_response.status_code == 409

    stop_response = client.post(f"/api/v1/extensions/instances/{instance['id']}/stop")
    assert stop_response.status_code == 200

    logs_response = client.get("/api/v1/logs?q=extension&types=audit")
    assert logs_response.status_code == 200
    action_types = {item["category"] for item in logs_response.json()["data"]["items"]}
    assert {
        "extension.case_genres_listed",
        "extension.case_created",
        "extension.cases_listed",
        "extension.contacts_searched",
        "extension.case_stakeholder_created",
        "extension.case_stakeholders_listed",
        "extension.case_auto_assign_rule_created",
        "extension.case_auto_assign_rule_reused",
    } <= action_types
