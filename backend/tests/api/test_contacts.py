from __future__ import annotations

from pathlib import Path

import sqlite3

from conftest import insert_unresolved_contact_email

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"


def test_contact_can_be_created_and_listed(client, database_path: Path) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Example Student",
            "avatar_url": "https://example.com/student.png",
            "user_memo": "Phase 3 dummy contact.",
            "ai_memo": "AI context placeholder.",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
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
    assert data["user_memo"] == "Phase 3 dummy contact."
    assert data["ai_memo"] == "AI context placeholder."
    assert data["status"] == "active"
    assert data["kind"] == "person"
    assert data["sender_resolution_mode"] == "self"
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
    assert detail_data["contact"]["user_memo"] == "Phase 3 dummy contact."
    assert detail_data["contact"]["ai_memo"] == "AI context placeholder."
    assert detail_data["related_cases"] == []


def test_reserved_contact_role_tags_can_be_used(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Role Tagged Contact",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "tags": ["supervised-student", "lab-alumni", "collaborator"],
            "email_addresses": [
                {"email_address": "role-tagged@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["tags"] == [
        "collaborator",
        "lab-alumni",
        "supervised-student",
    ]


def test_mailing_list_reserved_tag_is_still_rejected(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Forbidden Tag Contact",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "tags": ["mailing-list"],
            "email_addresses": [
                {"email_address": "forbidden-tag@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_advisees_tag_can_be_used_as_regular_tag(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Advisees Tagged Contact",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "tags": ["Advisees"],
            "email_addresses": [
                {"email_address": "advisees-tagged@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["tags"] == ["Advisees"]



def test_contact_custom_tabs_are_persisted(client) -> None:
    initial_response = client.get(f"{CONTACTS_URL}/custom-tabs")
    update_response = client.put(
        f"{CONTACTS_URL}/custom-tabs",
        json={
            "items": [
                {
                    "id": "custom_tsukuba",
                    "label": "Tsukuba",
                    "expression": "tsukuba&student",
                }
            ]
        },
    )
    next_response = client.get(f"{CONTACTS_URL}/custom-tabs")

    assert initial_response.status_code == 200
    assert initial_response.json()["data"]["items"] == []
    assert update_response.status_code == 200
    assert update_response.json()["data"]["items"] == [
        {
            "id": "custom_tsukuba",
            "label": "Tsukuba",
            "expression": "tsukuba&student",
        }
    ]
    assert next_response.json()["data"]["items"] == update_response.json()["data"]["items"]


def test_mailing_list_contact_can_choose_sender_resolution_mode(
    client,
    database_path: Path,
) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Campus PR ML",
            "status": "active",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "mailing_list_recipient_expression": "{faculty&public-relations}",
            "email_addresses": [
                {"email_address": "pr-list@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kind"] == "mailing_list"
    assert data["sender_resolution_mode"] == "reply_to"
    assert data["mailing_list_recipient_expression"] == "{faculty&public-relations}"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT kind, sender_resolution_mode, mailing_list_recipient_expression
            FROM contacts
            WHERE id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row == ("mailing_list", "reply_to", "{faculty&public-relations}")

    second_email_response = client.post(
        f"{CONTACTS_URL}/{data['id']}/email-addresses",
        json={"email_address": "pr-list-alt@example.com", "is_primary": False},
    )

    assert second_email_response.status_code == 409

    email_id = data["email_addresses"][0]["id"]
    delete_email_response = client.delete(
        f"{CONTACTS_URL}/{data['id']}/email-addresses/{email_id}"
    )
    primary_response = client.post(
        f"{CONTACTS_URL}/{data['id']}/email-addresses/{email_id}/primary"
    )

    assert delete_email_response.status_code == 409
    assert primary_response.status_code == 409


def test_service_contact_allows_multiple_addresses_and_tags(
    client,
    database_path: Path,
) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "PayPal",
            "status": "active",
            "kind": "service",
            "sender_resolution_mode": "self",
            "mailing_list_recipient_expression": "{should-not-persist}",
            "tags": ["payment", "service"],
            "email_addresses": [
                {"email_address": "notice@paypal.example", "is_primary": True},
                {"email_address": "support@paypal.example", "is_primary": False},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["kind"] == "service"
    assert data["sender_resolution_mode"] == "self"
    assert data["mailing_list_recipient_expression"] is None
    assert data["mail_importance_rule_action"] == "fixed"
    assert data["mail_importance_rule_importance"] == "low"
    assert data["tags"] == ["payment", "service"]
    assert [item["email_address"] for item in data["email_addresses"]] == [
        "notice@paypal.example",
        "support@paypal.example",
    ]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT
                kind, sender_resolution_mode, mailing_list_recipient_expression,
                mail_importance_rule_action, mail_importance_rule_importance
            FROM contacts
            WHERE id = ?
            """,
            (data["id"],),
        ).fetchone()

    assert row == ("service", "self", None, "fixed", "low")


def test_service_contact_rejects_reply_to_sender_resolution(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "No Reply Service",
            "status": "active",
            "kind": "service",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "no-reply@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_mailing_list_contact_rejects_contact_tags(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Tagged ML",
            "status": "active",
            "kind": "mailing_list",
            "sender_resolution_mode": "self",
            "tags": ["mailing-list"],
            "email_addresses": [
                {"email_address": "tagged-ml@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_contact_fixed_importance_rule_rejects_skip(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Skip Rule Contact",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "skip",
            "email_addresses": [
                {"email_address": "skip-rule@example.com", "is_primary": True}
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_person_contact_cannot_use_reply_to_sender_resolution(client) -> None:
    response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Normal Person",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "reply_to",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_contact_kind_cannot_be_changed_after_creation(client) -> None:
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Normal Person",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
        },
    )

    assert create_response.status_code == 200
    contact_id = create_response.json()["data"]["id"]

    update_response = client.patch(
        f"{CONTACTS_URL}/{contact_id}",
        json={
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "mailing_list_recipient_expression": "{faculty}",
        },
    )

    assert update_response.status_code == 409
    assert update_response.json()["error"]["code"] == (
        "CONTACT_KIND_CHANGE_NOT_ALLOWED"
    )


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


def test_marking_contact_spam_updates_existing_from_and_reply_to_mail(
    client,
    database_path: Path,
) -> None:
    spam_target_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Future Spam Target",
            "status": "active",
            "email_addresses": [
                {"email_address": "future.spam@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.sender@example.com", "is_primary": True}
            ],
        },
    )
    from_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_existing_from_spam",
            "gmail_thread_id": "thread_existing_from_spam",
            "subject": "Existing from target",
            "from_address": "future.spam@example.com",
            "received_at": "2026-05-24T10:00:00+09:00",
        },
    )
    reply_to_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_existing_reply_to_spam",
            "gmail_thread_id": "thread_existing_reply_to_spam",
            "subject": "Existing reply-to target",
            "from_address": "known.sender@example.com",
            "reply_to_address": "future.spam@example.com",
            "received_at": "2026-05-24T10:05:00+09:00",
        },
    )

    update_response = client.patch(
        f"{CONTACTS_URL}/{spam_target_response.json()['data']['id']}",
        json={"status": "spam"},
    )

    assert from_response.status_code == 200
    assert reply_to_response.status_code == 200
    assert update_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT gm.gmail_message_id, mas.effective_importance, mas.pending_reason
            FROM gmail_messages gm
            JOIN mail_auto_state mas ON mas.message_id = gm.id
            WHERE gm.gmail_message_id IN (
                'gmail_existing_from_spam',
                'gmail_existing_reply_to_spam'
            )
            ORDER BY gm.gmail_message_id
            """
        ).fetchall()

    assert rows == [
        ("gmail_existing_from_spam", "skip", None),
        ("gmail_existing_reply_to_spam", "skip", None),
    ]


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


def test_contact_can_be_deleted_when_all_addresses_are_removable(
    client,
    database_path: Path,
) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Disposable Contact",
            "status": "active",
            "email_addresses": [
                {"email_address": "disposable@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    response = client.delete(f"{CONTACTS_URL}/{contact_id}")

    assert response.status_code == 200
    assert response.json()["data"]["deleted_contact_id"] == contact_id

    with sqlite3.connect(database_path) as connection:
        contact_row = connection.execute(
            "SELECT deleted_at FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        email_row = connection.execute(
            """
            SELECT COUNT(*)
            FROM contact_email_addresses
            WHERE contact_id = ?
            """,
            (contact_id,),
        ).fetchone()

    assert contact_row[0] is not None
    assert email_row == (0,)


def test_person_contacts_can_be_merged(client) -> None:
    source_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Same Person",
            "status": "active",
            "tags": ["source-tag"],
            "email_addresses": [
                {"email_address": "source@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]
    target_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Same Person",
            "status": "active",
            "tags": ["target-tag"],
            "email_addresses": [
                {"email_address": "target@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{source_id}/merge",
        json={"target_contact_id": target_id},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["deleted_contact_id"] == source_id
    assert data["target_contact"]["id"] == target_id
    assert sorted(data["target_contact"]["tags"]) == ["source-tag", "target-tag"]
    assert sorted(
        email_address["email_address"]
        for email_address in data["target_contact"]["email_addresses"]
    ) == ["source@example.com", "target@example.com"]

    list_response = client.get(CONTACTS_URL)
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [target_id]


def test_contact_merge_uses_older_user_memo_unless_it_is_empty(client) -> None:
    older_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Older Memo",
            "user_memo": "older memo",
            "ai_memo": "older AI memo",
            "status": "active",
            "email_addresses": [
                {"email_address": "older-memo@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]
    newer_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Newer Memo",
            "user_memo": "newer memo",
            "ai_memo": "newer AI memo",
            "status": "active",
            "email_addresses": [
                {"email_address": "newer-memo@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{newer_id}/merge",
        json={"target_contact_id": older_id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["target_contact"]["user_memo"] == "older memo"
    assert response.json()["data"]["target_contact"]["ai_memo"] == "older AI memo"

    empty_older_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Empty Older",
            "user_memo": "",
            "ai_memo": "",
            "status": "active",
            "email_addresses": [
                {"email_address": "empty-older@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]
    filled_newer_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Filled Newer",
            "user_memo": "fallback memo",
            "ai_memo": "fallback AI memo",
            "status": "active",
            "email_addresses": [
                {"email_address": "filled-newer@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    fallback_response = client.post(
        f"{CONTACTS_URL}/{filled_newer_id}/merge",
        json={"target_contact_id": empty_older_id},
    )

    assert fallback_response.status_code == 200
    assert fallback_response.json()["data"]["target_contact"]["user_memo"] == "fallback memo"
    assert fallback_response.json()["data"]["target_contact"]["ai_memo"] == (
        "fallback AI memo"
    )


def test_duplicate_contact_display_name_gets_number_suffix(client) -> None:
    first_response = client.post(
        CONTACTS_URL,
        json={"display_name": "Duplicate Name", "status": "active"},
    )
    second_response = client.post(
        CONTACTS_URL,
        json={"display_name": "Duplicate Name", "status": "active"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["data"]["display_name"] == "Duplicate Name"
    assert second_response.json()["data"]["display_name"] == "Duplicate Name_2"


def test_service_contacts_can_be_merged(client) -> None:
    source_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Same Service",
            "status": "skipped",
            "kind": "service",
            "email_addresses": [
                {"email_address": "source-service@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]
    target_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Same Service",
            "status": "skipped",
            "kind": "service",
            "email_addresses": [
                {"email_address": "target-service@example.com", "is_primary": True}
            ],
        },
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{source_id}/merge",
        json={"target_contact_id": target_id},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["deleted_contact_id"] == source_id
    assert data["target_contact"]["kind"] == "service"
    assert sorted(
        email_address["email_address"]
        for email_address in data["target_contact"]["email_addresses"]
    ) == ["source-service@example.com", "target-service@example.com"]


def test_mailing_list_contacts_cannot_be_merged(client) -> None:
    source_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Source List",
            "status": "active",
            "kind": "mailing_list",
        },
    ).json()["data"]["id"]
    target_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Target List",
            "status": "active",
            "kind": "mailing_list",
        },
    ).json()["data"]["id"]

    response = client.post(
        f"{CONTACTS_URL}/{source_id}/merge",
        json={"target_contact_id": target_id},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_contact_cannot_be_deleted_when_address_has_inbound_history(
    client,
    database_path: Path,
) -> None:
    contact_id = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Referenced Contact",
            "status": "active",
            "email_addresses": [
                {"email_address": "referenced-delete@example.com", "is_primary": True}
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

    response = client.delete(f"{CONTACTS_URL}/{contact_id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


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
            "latest_from_name": None,
            "latest_from_address": None,
            "latest_reply_to_address": None,
            "latest_received_at": None,
            "latest_body_preview": None,
            "inferred_display_name": "Unknown Sender",
            "inferred_kind": "person",
            "inferred_sender_resolution": "self",
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


def test_fixed_importance_rule_update_rewrites_existing_mail_auto_state(
    client,
    database_path: Path,
) -> None:
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Rule Rewrite Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "rule-rewrite@example.com", "is_primary": True}
            ],
        },
    )
    contact_id = contact_response.json()["data"]["id"]
    first_mail_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_rule_rewrite_manual",
            "gmail_thread_id": "thread_rule_rewrite_manual",
            "from_address": "rule-rewrite@example.com",
            "received_at": "2026-05-24T10:00:00+09:00",
            "subject": "Manual importance target",
        },
    )
    second_mail_response = client.post(
        "/api/v1/mails/mock-ingest",
        json={
            "gmail_message_id": "gmail_rule_rewrite_auto",
            "gmail_thread_id": "thread_rule_rewrite_auto",
            "from_address": "rule-rewrite@example.com",
            "received_at": "2026-05-24T10:10:00+09:00",
            "subject": "Auto importance target",
        },
    )
    first_mail_id = first_mail_response.json()["data"]["message_id"]
    second_mail_id = second_mail_response.json()["data"]["message_id"]
    manual_response = client.post(
        f"/api/v1/mails/{first_mail_id}/importance",
        json={"importance": "high"},
    )
    assert manual_response.status_code == 200

    update_response = client.patch(
        f"{CONTACTS_URL}/{contact_id}",
        json={
            "display_name": "Rule Rewrite Sender",
            "status": "active",
            "kind": "person",
            "sender_resolution_mode": "self",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "low",
            "mail_importance_rule_instruction": None,
            "tags": [],
        },
    )

    assert update_response.status_code == 200
    first_detail = client.get(f"/api/v1/mails/{first_mail_id}").json()["data"]
    second_detail = client.get(f"/api/v1/mails/{second_mail_id}").json()["data"]
    assert first_detail["user_state"]["user_importance"] == "high"
    assert first_detail["auto_state"]["effective_importance"] == "high"
    assert first_detail["message"]["effective_importance"] == "high"
    assert second_detail["user_state"]["user_importance"] is None
    assert second_detail["auto_state"]["effective_importance"] == "low"
    assert second_detail["message"]["effective_importance"] == "low"

    with sqlite3.connect(database_path) as connection:
        auto_rows = connection.execute(
            """
            SELECT message_id, effective_importance
            FROM mail_auto_state
            WHERE message_id IN (?, ?)
            ORDER BY message_id
            """,
            (first_mail_id, second_mail_id),
        ).fetchall()

    assert auto_rows == sorted(
        [(first_mail_id, "low"), (second_mail_id, "low")],
    )

def test_fixed_importance_rule_can_be_changed_back_to_llm(client) -> None:
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Rule Reset Sender",
            "status": "active",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "low",
            "email_addresses": [
                {"email_address": "rule-reset@example.com", "is_primary": True}
            ],
        },
    )
    assert contact_response.status_code == 200
    contact_id = contact_response.json()["data"]["id"]

    update_response = client.patch(
        f"{CONTACTS_URL}/{contact_id}",
        json={
            "mail_importance_rule_action": "llm",
            "mail_importance_rule_importance": None,
            "mail_importance_rule_instruction": None,
        },
    )

    assert update_response.status_code == 200
    data = update_response.json()["data"]
    assert data["mail_importance_rule_action"] == "llm"
    assert data["mail_importance_rule_importance"] is None
    assert data["mail_importance_rule_instruction"] is None
