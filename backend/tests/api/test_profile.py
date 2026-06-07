from __future__ import annotations

import json
import sqlite3
from pathlib import Path


PROFILE_URL = "/api/v1/profile"


def test_profile_can_be_saved_in_app_settings(client, database_path: Path) -> None:
    initial_response = client.get(PROFILE_URL)

    assert initial_response.status_code == 200
    assert initial_response.json()["data"]["display_name"] == ""
    assert initial_response.json()["data"]["email_aliases"] == []

    update_response = client.patch(
        PROFILE_URL,
        json={
            "display_name": "Kazumasa Horie",
            "primary_email": "HORIE@example.edu",
            "email_aliases": [
                "alias@example.edu",
                "horie@example.edu",
                "alias@example.edu",
            ],
            "affiliation": "Biomedical Engineering Department",
            "academic_title": "Associate Professor",
            "lab_or_group": "BIPL",
            "research_fields": "Biomechanics, biomedical AI",
            "teaching_responsibilities": "Graduate seminar",
            "committee_roles": "Admissions committee",
            "administrative_roles": "Program coordinator",
            "supervised_people": "Graduate students",
            "collaborators": "Clinical collaborators",
            "important_projects": "Journal reviews",
            "priority_keywords": "deadline, review invitation",
            "low_priority_keywords": "newsletter",
            "important_senders_or_domains": "ieee.org",
            "expected_response_policy": "Reply to student questions quickly.",
            "unavailable_times": "During lectures.",
            "default_reply_language": "english",
            "llm_self_description": "University faculty member.",
            "mail_importance_notes": "Prioritize student, committee, and review requests.",
        },
    )

    assert update_response.status_code == 200
    data = update_response.json()["data"]
    assert data["display_name"] == "Kazumasa Horie"
    assert data["primary_email"] == "horie@example.edu"
    assert data["email_aliases"] == ["alias@example.edu"]
    assert data["default_reply_language"] == "english"
    assert data["updated_at"] is not None

    read_response = client.get(PROFILE_URL)
    assert read_response.status_code == 200
    assert read_response.json()["data"] == data

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = 'user_profile'"
        ).fetchone()
    assert row is not None
    stored = json.loads(row[0])
    assert stored["primary_email"] == "horie@example.edu"
    assert stored["email_aliases"] == ["alias@example.edu"]


def test_profile_rejects_invalid_email_address(client) -> None:
    response = client.patch(
        PROFILE_URL,
        json={
            "display_name": "User",
            "primary_email": "not-an-email",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
