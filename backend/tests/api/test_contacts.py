from __future__ import annotations

from pathlib import Path

import sqlite3

from conftest import insert_unresolved_contact_email

CONTACTS_URL = "/api/v1/contacts"


def test_contact_can_be_created_and_listed(client, database_path: Path) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Example Student",
            "avatar_url": "https://example.com/student.png",
            "memo": "Phase 3 dummy contact.",
            "status": "active",
            "tags": ["student", "lab"],
            "email_addresses": [
                {"email_address": "Student@Example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["display_name"] == "Example Student"
    assert data["avatar_url"] == "https://example.com/student.png"
    assert data["status"] == "active"
    assert data["email_addresses"][0]["normalized_email_address"] == (
        "student@example.com"
    )
    assert data["tags"] == ["lab", "student"]

    list_response = client.get(CONTACTS_URL)

    assert list_response.status_code == 200
    assert [item["display_name"] for item in list_response.json()["data"]["items"]] == [
        "Example Student"
    ]
    assert list_response.json()["data"]["items"][0]["avatar_url"] == (
        "https://example.com/student.png"
    )

    detail_response = client.get(f"{CONTACTS_URL}/{data['id']}")

    assert detail_response.status_code == 200
    detail_data = detail_response.json()["data"]
    assert detail_data["contact"]["id"] == data["id"]
    assert detail_data["contact"]["display_name"] == "Example Student"
    assert detail_data["related_cases"] == []


def test_contact_creation_marks_source_suggestion_as_adopted(
    client,
    database_path: Path,
) -> None:
    insert_unresolved_contact_email(
        database_path,
        email_address="suggested.sender@example.com",
        email_address_id="email_suggested_sender",
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO contact_registration_suggestions (
                id, email_address_id, suggested_display_name,
                suggested_tags_json, confidence, status, created_at, updated_at
            ) VALUES (
                'suggestion_pending', 'email_suggested_sender', 'Suggested Sender',
                '[]', 0.8, 'suggested',
                '2026-05-23T09:00:00+09:00', '2026-05-23T09:00:00+09:00'
            )
            """
        )
        connection.commit()

    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Edited Sender",
            "status": "active",
            "source_suggestion_id": "suggestion_pending",
            "email_addresses": [
                {"email_address": "suggested.sender@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status
            FROM contact_registration_suggestions
            WHERE id = 'suggestion_pending'
            """
        ).fetchone()

    assert row == ("edited_and_adopted",)


def test_contact_status_changes_between_skipped_and_active(
    client,
    database_path: Path,
) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "No Reply",
            "status": "skipped",
            "email_addresses": [
                {"email_address": "no-reply@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    skip_response = client.post(f"{CONTACTS_URL}/{contact_id}/skip")
    assert skip_response.status_code == 200
    assert skip_response.json()["data"]["status"] == "skipped"

    activate_response = client.post(f"{CONTACTS_URL}/{contact_id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["data"]["status"] == "active"


def test_unresolved_from_address_can_be_linked_to_existing_contact(
    client,
    database_path: Path,
) -> None:
    insert_unresolved_contact_email(
        database_path,
        email_address="pending.sender@example.com",
        email_address_id="email_pending_sender",
    )
    contact_id = client.post(
        CONTACTS_URL,
        json={"display_name": "Pending Sender", "status": "active"},
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{contact_id}/email-addresses",
        json={"email_address": "Pending.Sender@Example.com", "is_primary": True},
    )

    assert response.status_code == 200
    email_data = response.json()["data"]["email_addresses"][0]
    assert email_data["normalized_email_address"] == "pending.sender@example.com"
    assert email_data["resolution_status"] == "linked"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT contact_id, resolution_status, is_primary
            FROM contact_email_addresses
            WHERE id = ?
            """,
            ("email_pending_sender",),
        ).fetchone()

    assert row == (contact_id, "linked", 1)


def test_contact_email_address_primary_can_be_changed_and_removed(client) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Email Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "primary@example.com", "is_primary": True},
                {"email_address": "secondary@example.com", "is_primary": False},
            ],
        },
    ).json()["data"]["id"]

    contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    secondary_id = next(
        email_address["id"]
        for email_address in contact["email_addresses"]
        if email_address["email_address"] == "secondary@example.com"
    )
    primary_id = next(
        email_address["id"]
        for email_address in contact["email_addresses"]
        if email_address["email_address"] == "primary@example.com"
    )

    primary_response = client.post(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{secondary_id}/primary"
    )

    assert primary_response.status_code == 200
    email_addresses = primary_response.json()["data"]["email_addresses"]
    assert email_addresses[0]["id"] == secondary_id
    assert email_addresses[0]["is_primary"] is True
    assert next(
        email_address
        for email_address in email_addresses
        if email_address["id"] == primary_id
    )["is_primary"] is False

    delete_response = client.delete(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{primary_id}"
    )

    assert delete_response.status_code == 200
    remaining_email_addresses = delete_response.json()["data"]["email_addresses"]
    assert [email_address["id"] for email_address in remaining_email_addresses] == [
        secondary_id
    ]


def test_first_added_email_address_becomes_primary_after_all_addresses_removed(
    client,
) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Empty Email Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "initial@example.com", "is_primary": True},
            ],
        },
    ).json()["data"]["id"]

    contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    initial_id = contact["email_addresses"][0]["id"]

    delete_response = client.delete(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{initial_id}"
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["email_addresses"] == []

    add_response = client.post(
        f"{CONTACTS_URL}/{contact_id}/email-addresses",
        json={"email_address": "new-primary@example.com", "is_primary": False},
    )

    assert add_response.status_code == 200
    email_addresses = add_response.json()["data"]["email_addresses"]
    assert len(email_addresses) == 1
    assert email_addresses[0]["email_address"] == "new-primary@example.com"
    assert email_addresses[0]["is_primary"] is True


def test_email_address_with_inbound_history_becomes_inactive_when_removed(
    client,
    database_path: Path,
) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Referenced Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "old-address@example.com", "is_primary": True},
                {"email_address": "current-address@example.com", "is_primary": False},
            ],
        },
    ).json()["data"]["id"]

    contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    old_email_id = next(
        email_address["id"]
        for email_address in contact["email_addresses"]
        if email_address["email_address"] == "old-address@example.com"
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contact_email_addresses
            SET has_inbound_message_history = 1
            WHERE id = ?
            """,
            (old_email_id,),
        )
        connection.commit()

    delete_response = client.delete(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{old_email_id}"
    )

    assert delete_response.status_code == 200
    old_email = next(
        email_address
        for email_address in delete_response.json()["data"]["email_addresses"]
        if email_address["id"] == old_email_id
    )
    assert old_email["status"] == "inactive"
    assert old_email["is_primary"] is False

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT contact_id, resolution_status, status, is_primary,
                   has_inbound_message_history, deactivated_at, deleted_at
            FROM contact_email_addresses
            WHERE id = ?
            """,
            (old_email_id,),
        ).fetchone()

    assert row[0:5] == (contact_id, "linked", "inactive", 0, 1)
    assert row[5] is not None
    assert row[6] is None


def test_email_address_can_be_moved_to_another_contact(
    client,
    database_path: Path,
) -> None:
    source_contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Source Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "move-me@example.com", "is_primary": True},
            ],
        },
    ).json()["data"]["id"]
    target_contact_id = client.post(
        CONTACTS_URL,
        json={"display_name": "Target Owner", "status": "active"},
    ).json()["data"]["id"]

    source_contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    email_id = source_contact["email_addresses"][0]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contact_email_addresses
            SET has_inbound_message_history = 1
            WHERE id = ?
            """,
            (email_id,),
        )
        connection.commit()

    move_response = client.post(
        f"{CONTACTS_URL}/{source_contact_id}/email-addresses/{email_id}/move",
        json={"target_contact_id": target_contact_id},
    )

    assert move_response.status_code == 200
    assert move_response.json()["data"]["source_contact"]["email_addresses"] == []
    moved_email = move_response.json()["data"]["target_contact"]["email_addresses"][0]
    assert moved_email["id"] == email_id
    assert moved_email["status"] == "active"
    assert moved_email["is_primary"] is True

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT contact_id, status, has_inbound_message_history, deactivated_at
            FROM contact_email_addresses
            WHERE id = ?
            """,
            (email_id,),
        ).fetchone()

    assert row == (target_contact_id, "active", 1, None)


def test_inactive_email_address_can_still_be_moved_to_another_contact(
    client,
    database_path: Path,
) -> None:
    source_contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Inactive Source",
            "status": "active",
            "email_addresses": [
                {"email_address": "inactive-move@example.com", "is_primary": True},
            ],
        },
    ).json()["data"]["id"]
    target_contact_id = client.post(
        CONTACTS_URL,
        json={"display_name": "Inactive Target", "status": "active"},
    ).json()["data"]["id"]

    source_contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    email_id = source_contact["email_addresses"][0]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contact_email_addresses
            SET has_inbound_message_history = 1
            WHERE id = ?
            """,
            (email_id,),
        )
        connection.commit()

    delete_response = client.delete(
        f"{CONTACTS_URL}/{source_contact_id}/email-addresses/{email_id}"
    )
    assert delete_response.status_code == 200

    move_response = client.post(
        f"{CONTACTS_URL}/{source_contact_id}/email-addresses/{email_id}/move",
        json={"target_contact_id": target_contact_id},
    )

    assert move_response.status_code == 200
    moved_email = move_response.json()["data"]["target_contact"]["email_addresses"][0]
    assert moved_email["id"] == email_id
    assert moved_email["status"] == "inactive"
    assert moved_email["is_primary"] is False

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT contact_id, status, is_primary, has_inbound_message_history,
                   deactivated_at
            FROM contact_email_addresses
            WHERE id = ?
            """,
            (email_id,),
        ).fetchone()

    assert row[0:4] == (target_contact_id, "inactive", 0, 1)
    assert row[4] is not None


def test_inactive_email_address_can_be_activated(client, database_path: Path) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Inactive Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "inactive-local@example.com", "is_primary": True},
            ],
        },
    ).json()["data"]["id"]
    contact = client.get(CONTACTS_URL).json()["data"]["items"][0]
    email_id = contact["email_addresses"][0]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE contact_email_addresses
            SET has_inbound_message_history = 1
            WHERE id = ?
            """,
            (email_id,),
        )
        connection.commit()

    delete_response = client.delete(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{email_id}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["email_addresses"][0]["status"] == "inactive"

    activate_response = client.post(
        f"{CONTACTS_URL}/{contact_id}/email-addresses/{email_id}/activate"
    )

    assert activate_response.status_code == 200
    email_address = activate_response.json()["data"]["email_addresses"][0]
    assert email_address["id"] == email_id
    assert email_address["status"] == "active"
    assert email_address["is_primary"] is True


def test_unresolved_from_addresses_are_listed_and_prefill_job_can_be_created(
    client,
    database_path: Path,
) -> None:
    insert_unresolved_contact_email(
        database_path,
        email_address="unknown.sender@example.com",
        email_address_id="email_unknown_sender",
    )

    list_response = client.get(f"{CONTACTS_URL}/unresolved-from-addresses")

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"] == [
        {
            "email_address_id": "email_unknown_sender",
            "email_address": "unknown.sender@example.com",
            "normalized_email_address": "unknown.sender@example.com",
            "message_count": 0,
            "latest_message_id": None,
            "latest_subject": None,
            "suggestion_status": "not_started",
            "suggestion": None,
        }
    ]

    response = client.post(
        f"{CONTACTS_URL}/unresolved-from-addresses/unknown.sender%40example.com/generate-prefill",
        json={"message_id": "mail_dummy"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["job_id"].startswith("job_contact_prefill_")

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT job_type, status, payload_json
            FROM jobs
            WHERE id = ?
            """,
            (response.json()["data"]["job_id"],),
        ).fetchone()

    assert row[0] == "contact_registration_prefill"
    assert row[1] == "pending"
    assert "unknown.sender@example.com" in row[2]


def test_email_address_cannot_be_skipped_without_a_contact(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Skipped Contact",
            "status": "skipped",
            "email_addresses": [
                {"email_address": "skip-source@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    email_data = response.json()["data"]["email_addresses"][0]
    assert "skipped" not in email_data["resolution_status"]
    assert response.json()["data"]["status"] == "skipped"
