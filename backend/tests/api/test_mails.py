from __future__ import annotations

import base64
from email import message_from_bytes
import sqlite3
import json
from types import SimpleNamespace

from caseclosed.services.mail_sending import handle_mail_send_mock

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"
MAILS_URL = "/api/v1/mails"
MAIL_DRAFTS_URL = "/api/v1/mail-drafts"
CASES_URL = "/api/v1/cases"


def ingest_mail(
    client,
    *,
    gmail_message_id: str,
    gmail_thread_id: str,
    from_address: str,
    subject: str,
    received_at: str,
    body_text: str = "",
) -> str:
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": gmail_thread_id,
            "message_id_header": f"<{gmail_message_id}@example.com>",
            "subject": subject,
            "from_address": from_address,
            "received_at": received_at,
            "body_text": body_text,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["message_id"]


def create_known_sender_mail(client, *, subject: str, body_text: str = "") -> str:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Mail Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "mail.sender@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Recipient",
            "avatar_url": "https://example.com/recipient.png",
            "status": "active",
            "email_addresses": [
                {"email_address": "user@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mail_api_1",
            "gmail_thread_id": "thread_mail_api",
            "message_id_header": "<mail-api-1@example.com>",
            "subject": subject,
            "from_address": "mail.sender@example.com",
            "reply_to_address": "reply@example.com",
            "to_addresses": ["user@example.com"],
            "received_at": "2026-05-23T13:00:00+09:00",
            "body_text": body_text,
        },
    )
    return response.json()["data"]["message_id"]


def test_mail_list_can_filter_all_sender_and_recipient_addresses_for_contact(client) -> None:
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Participant Contact",
            "status": "active",
            "email_addresses": [
                {"email_address": "participant.primary@example.com", "is_primary": True},
                {"email_address": "participant.secondary@example.com", "is_primary": False},
            ],
        },
    )
    contact_id = contact_response.json()["data"]["id"]

    inbound_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_contact_participant_inbound",
            "gmail_thread_id": "thread_contact_participant_inbound",
            "subject": "Participant inbound",
            "from_address": "participant.primary@example.com",
            "to_addresses": ["user@example.com"],
            "received_at": "2026-07-22T10:00:00+09:00",
            "body_text": "Inbound from the Contact.",
        },
    )
    outbound_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_contact_participant_outbound",
            "gmail_thread_id": "thread_contact_participant_outbound",
            "subject": "Participant outbound",
            "from_address": "user@example.com",
            "to_addresses": ["participant.secondary@example.com"],
            "gmail_labels": ["SENT"],
            "received_at": "2026-07-22T10:05:00+09:00",
            "body_text": "Outbound to the Contact.",
        },
    )
    unrelated_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_contact_participant_unrelated",
            "gmail_thread_id": "thread_contact_participant_unrelated",
            "subject": "Unrelated mail",
            "from_address": "other@example.com",
            "to_addresses": ["user@example.com"],
            "received_at": "2026-07-22T10:10:00+09:00",
        },
    )
    assert inbound_response.status_code == 200
    assert outbound_response.status_code == 200
    assert unrelated_response.status_code == 200

    list_response = client.get(
        f"{MAILS_URL}?tab=all&contact_id={contact_id}&sort=newest&limit=25"
    )
    assert list_response.status_code == 200
    assert {item["subject"] for item in list_response.json()["data"]["items"]} == {
        "Participant inbound",
        "Participant outbound",
    }

    narrowed_response = client.get(
        f"{MAILS_URL}?tab=all&contact_id={contact_id}&q=inbound&limit=25"
    )
    assert [item["subject"] for item in narrowed_response.json()["data"]["items"]] == [
        "Participant inbound"
    ]
    assert client.get(f"{MAILS_URL}?contact_id=missing-contact").status_code == 404


def test_mail_thread_can_be_assigned_to_case(client) -> None:
    case_response = client.post(
        CASES_URL,
        json={
            "name": "Assigned Thread Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Assign Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "assign.sender@example.com", "is_primary": True}
            ],
        },
    )
    assert contact_response.status_code == 200
    sender_contact_id = contact_response.json()["data"]["id"]

    first_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_case_assign_1",
        gmail_thread_id="thread_case_assign",
        from_address="assign.sender@example.com",
        subject="Assign me",
        received_at="2026-06-05T10:00:00+09:00",
        body_text="First message.",
    )
    second_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_case_assign_2",
        gmail_thread_id="thread_case_assign",
        from_address="assign.sender@example.com",
        subject="Assign me",
        received_at="2026-06-05T11:00:00+09:00",
        body_text="Second message.",
    )

    assign_response = client.post(
        f"{MAILS_URL}/{first_message_id}/case-links",
        json={"case_id": case_id},
    )
    assert assign_response.status_code == 200
    assert assign_response.json()["data"]["case_links"] == [
        {
            "id": case_id,
            "case_id": case_id,
            "title": "Assigned Thread Case",
        }
    ]

    second_detail = client.get(f"{MAILS_URL}/{second_message_id}")
    assert second_detail.status_code == 200
    assert second_detail.json()["data"]["case_links"][0]["case_id"] == case_id

    stakeholders_response = client.get(f"{CASES_URL}/{case_id}/stakeholders")
    assert stakeholders_response.status_code == 200
    assert [
        (item["contact_id"], item["role"])
        for item in stakeholders_response.json()["data"]["items"]
    ] == [(sender_contact_id, "mail_sender")]

    unassign_response = client.delete(
        f"{MAILS_URL}/{second_message_id}/case-links/{case_id}",
    )
    assert unassign_response.status_code == 200
    assert unassign_response.json()["data"]["case_links"] == []

    first_detail = client.get(f"{MAILS_URL}/{first_message_id}")
    assert first_detail.json()["data"]["case_links"] == []


def test_mail_ingestion_applies_case_auto_assign_rules(client) -> None:
    case_ids: dict[str, str] = {}
    for name in ("Rule Active Case", "Rule Completed Case", "Rule Archived Case"):
        response = client.post(
            CASES_URL,
            json={
                "name": name,
                "description": None,
                "progress_status": "in_progress",
                "ball_status": "user",
            },
        )
        assert response.status_code == 200
        case_ids[name] = response.json()["data"]["case"]["id"]

    assert (
        client.post(f"{CASES_URL}/{case_ids['Rule Completed Case']}/complete").status_code
        == 200
    )
    assert (
        client.post(f"{CASES_URL}/{case_ids['Rule Archived Case']}/archive").status_code
        == 200
    )

    for case_id in case_ids.values():
        rule_response = client.post(
            f"{CASES_URL}/{case_id}/auto-assign-rules",
            json={"sender_email": "papers@example.com"},
        )
        assert rule_response.status_code == 200
        assert rule_response.json()["data"]["rule"]["rule_value"] == "papers@example.com"

    list_response = client.get(
        f"{CASES_URL}/{case_ids['Rule Active Case']}/auto-assign-rules"
    )
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]["items"]) == 1

    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Paper Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "papers@example.com", "is_primary": True}
            ],
        },
    )
    assert contact_response.status_code == 200
    paper_sender_contact_id = contact_response.json()["data"]["id"]

    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_case_auto_assign",
        gmail_thread_id="thread_case_auto_assign",
        from_address="Papers <papers@example.com>",
        subject="Daily paper digest",
        received_at="2026-06-07T08:00:00+09:00",
        body_text="New papers.",
    )

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    assert detail_response.status_code == 200
    linked_case_ids = {
        item["case_id"] for item in detail_response.json()["data"]["case_links"]
    }
    assert case_ids["Rule Active Case"] in linked_case_ids
    assert case_ids["Rule Completed Case"] in linked_case_ids
    assert case_ids["Rule Archived Case"] not in linked_case_ids

    active_stakeholders = client.get(
        f"{CASES_URL}/{case_ids['Rule Active Case']}/stakeholders"
    )
    assert active_stakeholders.status_code == 200
    assert [
        (item["contact_id"], item["role"])
        for item in active_stakeholders.json()["data"]["items"]
    ] == [(paper_sender_contact_id, "mail_sender")]

    completed_stakeholders = client.get(
        f"{CASES_URL}/{case_ids['Rule Completed Case']}/stakeholders"
    )
    assert completed_stakeholders.status_code == 200
    assert [
        (item["contact_id"], item["role"])
        for item in completed_stakeholders.json()["data"]["items"]
    ] == [(paper_sender_contact_id, "mail_sender")]

    spam_subject_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_case_auto_assign_spam_subject",
        gmail_thread_id="thread_case_auto_assign_spam_subject",
        from_address="papers@example.com",
        subject="[SPAM] Daily paper digest",
        received_at="2026-06-07T08:10:00+09:00",
        body_text="Spam-like papers.",
    )
    spam_subject_detail = client.get(f"{MAILS_URL}/{spam_subject_message_id}")
    assert spam_subject_detail.status_code == 200
    assert spam_subject_detail.json()["data"]["case_links"] == []

    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Skipped Paper Sender",
            "status": "skipped",
            "email_addresses": [
                {"email_address": "skipped-papers@example.com", "is_primary": True}
            ],
        },
    )
    skipped_rule_response = client.post(
        f"{CASES_URL}/{case_ids['Rule Active Case']}/auto-assign-rules",
        json={"sender_email": "skipped-papers@example.com"},
    )
    assert skipped_rule_response.status_code == 200
    skipped_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_case_auto_assign_skipped_sender",
        gmail_thread_id="thread_case_auto_assign_skipped_sender",
        from_address="skipped-papers@example.com",
        subject="Skipped but collected paper digest",
        received_at="2026-06-07T08:20:00+09:00",
        body_text="This sender is skipped but should still be collected.",
    )
    skipped_detail = client.get(f"{MAILS_URL}/{skipped_message_id}")
    assert skipped_detail.status_code == 200
    assert {
        item["case_id"] for item in skipped_detail.json()["data"]["case_links"]
    } == {case_ids["Rule Active Case"]}

    rule_id = list_response.json()["data"]["items"][0]["id"]
    delete_response = client.delete(
        f"{CASES_URL}/{case_ids['Rule Active Case']}/auto-assign-rules/{rule_id}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted"] is True


def test_case_auto_assign_rules_support_contact_and_email_scopes(client) -> None:
    contact_case_response = client.post(
        CASES_URL,
        json={
            "name": "Contact-wide Rule Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    email_case_response = client.post(
        CASES_URL,
        json={
            "name": "Email-only Rule Case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    contact_case_id = contact_case_response.json()["data"]["case"]["id"]
    email_case_id = email_case_response.json()["data"]["case"]["id"]
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Multi Address Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "primary@example.com", "is_primary": True},
                {"email_address": "service-topic@example.com", "is_primary": False},
            ],
        },
    )
    contact_id = contact_response.json()["data"]["id"]

    contact_rule_response = client.post(
        f"{CASES_URL}/{contact_case_id}/auto-assign-rules",
        json={"contact_id": contact_id},
    )
    email_rule_response = client.post(
        f"{CASES_URL}/{email_case_id}/auto-assign-rules",
        json={"sender_email": "primary@example.com"},
    )

    assert contact_rule_response.status_code == 200
    assert contact_rule_response.json()["data"]["rule"]["rule_type"] == "sender_contact"
    assert contact_rule_response.json()["data"]["rule"]["contact_display_name"] == (
        "Multi Address Sender"
    )
    assert email_rule_response.status_code == 200
    assert email_rule_response.json()["data"]["rule"]["rule_type"] == "sender_email"

    all_rules_response = client.get(f"{CASES_URL}/auto-assign-rules")
    assert all_rules_response.status_code == 200
    all_rules = all_rules_response.json()["data"]["items"]
    assert [item["case_name"] for item in all_rules] == [
        "Contact-wide Rule Case",
        "Email-only Rule Case",
    ]
    assert {
        (item["case_id"], item["rule_type"], item["display_value"])
        for item in all_rules
    } == {
        (contact_case_id, "sender_contact", "Multi Address Sender"),
        (email_case_id, "sender_email", "primary@example.com"),
    }

    secondary_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_contact_scope_secondary",
        gmail_thread_id="thread_contact_scope_secondary",
        from_address="service-topic@example.com",
        subject="Secondary address mail",
        received_at="2026-07-21T10:00:00+09:00",
    )
    secondary_detail = client.get(f"{MAILS_URL}/{secondary_message_id}").json()["data"]
    secondary_case_ids = {
        item["case_id"] for item in secondary_detail["case_links"]
    }
    assert contact_case_id in secondary_case_ids
    assert email_case_id not in secondary_case_ids

    primary_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_contact_scope_primary",
        gmail_thread_id="thread_contact_scope_primary",
        from_address="primary@example.com",
        subject="Primary address mail",
        received_at="2026-07-21T10:05:00+09:00",
    )
    primary_detail = client.get(f"{MAILS_URL}/{primary_message_id}").json()["data"]
    primary_case_ids = {
        item["case_id"] for item in primary_detail["case_links"]
    }
    assert {contact_case_id, email_case_id}.issubset(primary_case_ids)


def insert_received_attachment(
    database_path,
    *,
    attachment_id: str,
    message_id: str,
    gmail_message_id: str,
    gmail_attachment_id: str,
    filename: str = "note.pdf",
    mime_type: str = "application/pdf",
    byte_size: int = 123,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO gmail_message_attachments (
                id, message_id, gmail_message_id, gmail_attachment_id,
                part_id, filename, mime_type, byte_size, storage_object_id,
                created_at, updated_at, version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
            """,
            (
                attachment_id,
                message_id,
                gmail_message_id,
                gmail_attachment_id,
                "1",
                filename,
                mime_type,
                byte_size,
                "2026-05-28T12:00:00+09:00",
                "2026-05-28T12:00:00+09:00",
            ),
        )
        connection.commit()


def connect_gmail_send(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()


def patch_gmail_send_response(
    monkeypatch,
    *,
    gmail_message_id: str,
    gmail_thread_id: str,
    subject: str,
    body_text: str,
    to_address: str,
    cc_address: str | None = None,
    in_reply_to: str | None = None,
) -> list[bytes]:
    sent_raw_messages: list[bytes] = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        sent_raw_messages.append(raw_message)
        return {"id": gmail_message_id, "threadId": thread_id or gmail_thread_id}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == f"/users/me/messages/{gmail_message_id}":
            headers = [
                {"name": "From", "value": "me@example.com"},
                {"name": "To", "value": to_address},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{gmail_message_id}@example.com>"},
            ]
            if cc_address is not None:
                headers.append({"name": "Cc", "value": cc_address})
            if in_reply_to is not None:
                headers.append({"name": "In-Reply-To", "value": in_reply_to})
            return {
                "id": gmail_message_id,
                "threadId": gmail_thread_id,
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "snippet": body_text,
                "payload": {
                    "mimeType": "text/plain",
                    "headers": headers,
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            body_text.encode("utf-8")
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )
    return sent_raw_messages


def test_mail_detail_returns_message_state_and_available_actions(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Detail API test",
        body_text="This body is stored for detail view.",
    )
    case_response = client.post(
        CASES_URL,
        json={
            "name": "Mail detail task case",
            "description": None,
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    assert case_response.status_code == 200
    case_id = case_response.json()["data"]["case"]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO tasks (
              id, case_id, storage_directory_id, parent_task_id, title, description,
              done_when_text, status, priority, start_at, due_at, estimate_minutes,
              scheduled_minutes, worked_minutes, source_type, source_id,
              completed_at, canceled_at, canceled_reason, deleted_at, deleted_reason,
              created_at, updated_at, version
            )
            VALUES (
              'task_mail_detail_related', ?, NULL, NULL, 'Follow up mail detail', NULL,
              NULL, 'not_started', 'middle', '2026-05-23', NULL, NULL,
              0, 0, 'mail', ?,
              NULL, NULL, NULL, NULL, NULL,
              '2026-05-23T13:05:00+09:00', '2026-05-23T13:05:00+09:00', 1
            )
            """,
            (case_id, message_id),
        )
        connection.execute(
            """
            INSERT INTO tasks (
              id, case_id, storage_directory_id, parent_task_id, title, description,
              done_when_text, status, priority, start_at, due_at, estimate_minutes,
              scheduled_minutes, worked_minutes, source_type, source_id,
              completed_at, canceled_at, canceled_reason, deleted_at, deleted_reason,
              created_at, updated_at, version
            )
            VALUES (
              'task_mail_detail_manual_link', ?, NULL, NULL, 'Manual linked task', NULL,
              NULL, 'in_progress', 'high', '2026-05-23', NULL, NULL,
              0, 0, 'manual', NULL,
              NULL, NULL, NULL, NULL, NULL,
              '2026-05-23T13:06:00+09:00', '2026-05-23T13:06:00+09:00', 1
            )
            """,
            (case_id,),
        )
        connection.execute(
            """
            INSERT INTO task_links (id, task_id, linked_type, linked_id, url, label, created_at)
            VALUES (
              'task_link_mail_detail_manual', 'task_mail_detail_manual_link',
              'mail', ?, NULL, NULL, '2026-05-23T13:06:00+09:00'
            )
            """,
            (message_id,),
        )
        connection.execute(
            """
            INSERT INTO calendar_events (
              id, source, external_calendar_id, external_event_id, summary, start_at, end_at,
              all_day, sync_status, attendance_requirement, created_at, updated_at, version
            ) VALUES (
              'calendar_event_mail_detail_related', 'google', 'primary', 'google_mail_detail_event',
              'Mail detail meeting', '2026-05-24T10:00:00+09:00', '2026-05-24T11:00:00+09:00',
              0, 'synced', 'unknown', '2026-05-23T13:10:00+09:00', '2026-05-23T13:10:00+09:00', 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO calendar_event_links (
              id, calendar_event_id, linked_type, linked_id, role, created_at, updated_at, version
            ) VALUES (
              'calendar_event_link_mail_detail_related', 'calendar_event_mail_detail_related',
              'mail', ?, 'related', '2026-05-23T13:10:00+09:00', '2026-05-23T13:10:00+09:00', 1
            )
            """,
            (message_id,),
        )
        connection.commit()

    response = client.get(f"{MAILS_URL}/{message_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"]["id"] == message_id
    assert data["message"]["subject"] == "Detail API test"
    assert data["message"]["body_text"] == "This body is stored for detail view."
    assert data["message"]["message_id_header"] == "<mail-api-1@example.com>"
    assert data["message"]["from_contact"]["display_name"] == "Mail Sender"
    assert data["message"]["sender_contact"]["display_name"] == "Mail Sender"
    assert data["message"]["to_addresses"] == ["user@example.com"]
    assert data["message"]["to_recipients"] == [
        {
            "email_address": "user@example.com",
            "contact": {
                "id": data["message"]["to_recipients"][0]["contact"]["id"],
                "display_name": "Known Recipient",
                "avatar_url": "https://example.com/recipient.png",
                "kind": "person",
                "status": "active",
                "tags": [],
            },
        }
    ]
    assert data["message"]["cc_recipients"] == []
    assert data["user_state"]["processed_status"] == "unprocessed"
    assert data["user_state"]["read_status"] == "unread"
    assert data["auto_state"]["effective_importance"] == "unclassified"
    assert data["thread_messages"][0]["id"] == message_id
    assert data["thread_messages"][0]["body_text"] == "This body is stored for detail view."
    assert data["thread_messages"][0]["effective_importance"] == "unclassified"
    assert data["thread_messages"][0]["processed_status"] == "unprocessed"
    assert data["task_links"] == [
        {
            "id": "task_mail_detail_manual_link",
            "task_id": "task_mail_detail_manual_link",
            "case_id": case_id,
            "title": "Manual linked task",
            "status": "in_progress",
            "priority": "high",
        },
        {
            "id": "task_mail_detail_related",
            "task_id": "task_mail_detail_related",
            "case_id": case_id,
            "title": "Follow up mail detail",
            "status": "not_started",
            "priority": "middle",
        },
    ]
    assert data["calendar_event_links"] == [
        {
            "id": "calendar_event_mail_detail_related",
            "calendar_event_id": "calendar_event_mail_detail_related",
            "title": "Mail detail meeting",
            "start_at": "2026-05-24T10:00:00+09:00",
            "end_at": "2026-05-24T11:00:00+09:00",
            "all_day": False,
            "status": None,
        }
    ]
    assert "process" in data["available_actions"]
    assert "set_importance" in data["available_actions"]


def test_mail_detail_and_list_report_received_attachments(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment detail",
        body_text="Please see the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_detail",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_detail",
        filename="review-note.pdf",
        byte_size=2048,
    )

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    list_response = client.get(f"{MAILS_URL}?tab=unprocessed&limit=20")

    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["message"]["has_attachments"] is True
    assert detail["message"]["attachment_count"] == 1
    assert detail["message"]["attachments"][0]["filename"] == "review-note.pdf"
    assert detail["message"]["attachments"][0]["download_url"].endswith(
        "/api/v1/mails/attachments/mail_attachment_detail/download"
    )
    assert detail["attachments"] == detail["message"]["attachments"]
    assert list_response.status_code == 200
    item = next(
        item for item in list_response.json()["data"]["items"] if item["id"] == message_id
    )
    assert item["has_attachments"] is True
    assert item["attachment_count"] == 1


def test_mail_detail_hides_legacy_inline_uuid_images(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Google shared-file notification",
        body_text="A file was shared.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_inline_image",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_inline_image",
        filename="2b2b4e92-e9c1-4215-bf82-2ddca127240c",
        mime_type="image/png",
        byte_size=2877,
    )

    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["attachments"] == []
    assert message["attachment_count"] == 0
    assert message["has_attachments"] is False


def test_mail_attachment_download_caches_gmail_data(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment download",
        body_text="Please download the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_download",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_download",
        filename="review-note.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)
    calls: list[str] = []

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        calls.append(path)
        assert path == "/users/me/messages/gmail_mail_api_1/attachments/gmail_attach_download"
        return {
            "data": base64.urlsafe_b64encode(b"hello attachment")
            .decode("ascii")
            .rstrip("="),
            "size": 16,
        }

    from caseclosed import google_integration

    monkeypatch.setattr(google_integration, "gmail_api_get_json", fake_gmail_api_get_json)

    first_response = client.get(
        f"{MAILS_URL}/attachments/mail_attachment_download/download"
    )
    with sqlite3.connect(database_path) as connection:
        storage_object_id = connection.execute(
            "SELECT storage_object_id FROM gmail_message_attachments WHERE id = ?",
            ("mail_attachment_download",),
        ).fetchone()[0]
        connection.execute(
            "UPDATE storage_objects SET original_filename = ? WHERE id = ?",
            ("storage_object_internal_name.txt", storage_object_id),
        )
    second_response = client.get(
        f"{MAILS_URL}/attachments/mail_attachment_download/download"
    )

    assert first_response.status_code == 200
    assert first_response.content == b"hello attachment"
    assert first_response.headers["content-disposition"] == (
        'attachment; filename="review-note.txt"'
    )
    assert second_response.status_code == 200
    assert second_response.content == b"hello attachment"
    assert second_response.headers["content-disposition"] == (
        'attachment; filename="review-note.txt"'
    )
    assert calls == [
        "/users/me/messages/gmail_mail_api_1/attachments/gmail_attach_download"
    ]


def test_scheduled_send_request_detail_reports_sent_attachments(client) -> None:
    attachment_bytes = "送信添付".encode()
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["receiver@example.com"],
            "subject": "Attachment scheduled mail",
            "body_text": "Please see attached.",
            "attachments": [
                {
                    "filename": "送信メモ.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(attachment_bytes).decode("ascii"),
                    "size": len(attachment_bytes),
                }
            ],
            "scheduled_at": "2099-05-25T09:00:00+09:00",
        },
    )
    assert send_response.status_code == 200
    send_request = send_response.json()["data"]
    assert send_request["attachment_names"] == ["送信メモ.txt"]
    assert send_request["attachments"][0]["filename"] == "送信メモ.txt"
    assert send_request["attachments"][0]["source_type"] == "sent_attachment"

    detail_response = client.get(f"{MAILS_URL}/{send_request['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["message"]["has_attachments"] is True
    assert detail["message"]["attachments"][0]["filename"] == "送信メモ.txt"
    assert detail["attachments"] == detail["message"]["attachments"]

    download_response = client.get(
        f"{MAILS_URL}/send-requests/{send_request['id']}/attachments/0/download"
    )
    assert download_response.status_code == 200
    assert download_response.content == attachment_bytes
    assert "filename*=UTF-8''" in download_response.headers["content-disposition"]


def test_move_cached_mail_attachment_to_storage_deletes_tmp_file(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment move",
        body_text="Please store the file.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_move",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_move",
        filename="move-note.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        lambda path, access_token, params=None: {
            "data": base64.urlsafe_b64encode(b"cached attachment")
            .decode("ascii")
            .rstrip("="),
        },
    )

    cache_response = client.get(f"{MAILS_URL}/attachments/mail_attachment_move/download")
    assert cache_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        tmp_row = connection.execute(
            """
            SELECT storage_objects.id, storage_objects.storage_path
            FROM gmail_message_attachments
            JOIN storage_objects
                ON storage_objects.id = gmail_message_attachments.storage_object_id
            WHERE gmail_message_attachments.id = ?
            """,
            ("mail_attachment_move",),
        ).fetchone()
    tmp_storage_object_id, tmp_storage_path = tmp_row
    assert (database_path.parent / "storage" / tmp_storage_path).is_file()

    move_response = client.post(
        f"{MAILS_URL}/attachments/mail_attachment_move/move-to-storage"
    )

    assert move_response.status_code == 200
    managed_object = move_response.json()["data"]["storage_object"]
    assert managed_object["scope"] == "managed"
    assert managed_object["source_type"] == "mail_attachment"
    assert managed_object["source_message_id"] == message_id
    with sqlite3.connect(database_path) as connection:
        tmp_status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (tmp_storage_object_id,),
        ).fetchone()[0]
        attachment_storage_object_id = connection.execute(
            "SELECT storage_object_id FROM gmail_message_attachments WHERE id = ?",
            ("mail_attachment_move",),
        ).fetchone()[0]

    assert tmp_status == "deleted"
    assert attachment_storage_object_id == managed_object["id"]
    assert not (database_path.parent / "storage" / tmp_storage_path).exists()

    with sqlite3.connect(database_path) as connection:
        managed_storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (managed_object["id"],),
        ).fetchone()[0]
    assert (database_path.parent / "storage" / managed_storage_path).is_file()

    delete_response = client.delete(f"/api/v1/storage/objects/{managed_object['id']}")

    assert delete_response.status_code == 200
    restored_object = delete_response.json()["data"]["restored_storage_object"]
    assert restored_object["scope"] == "tmp/gmail-attachments"
    assert restored_object["source_type"] == "mail_attachment"
    assert restored_object["source_message_id"] == message_id
    with sqlite3.connect(database_path) as connection:
        managed_status = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (managed_object["id"],),
        ).fetchone()[0]
        restored_storage_path = connection.execute(
            "SELECT storage_path FROM storage_objects WHERE id = ?",
            (restored_object["id"],),
        ).fetchone()[0]
        restored_attachment_storage_object_id = connection.execute(
            "SELECT storage_object_id FROM gmail_message_attachments WHERE id = ?",
            ("mail_attachment_move",),
        ).fetchone()[0]

    assert managed_status == "deleted"
    assert restored_attachment_storage_object_id == restored_object["id"]
    assert not (database_path.parent / "storage" / managed_storage_path).exists()
    assert (database_path.parent / "storage" / restored_storage_path).is_file()


def test_mail_attachment_fetch_job_stores_attachment(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Attachment background fetch",
        body_text="Please store this file in the background.",
    )
    insert_received_attachment(
        database_path,
        attachment_id="mail_attachment_fetch_job",
        message_id=message_id,
        gmail_message_id="gmail_mail_api_1",
        gmail_attachment_id="gmail_attach_fetch_job",
        filename="fetch-job.txt",
        mime_type="text/plain",
        byte_size=5,
    )
    connect_gmail_send(database_path)

    from caseclosed import google_integration
    from caseclosed.services.orchestrator import Orchestrator

    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        lambda path, access_token, params=None: {
            "data": base64.urlsafe_b64encode(b"background attachment")
            .decode("ascii")
            .rstrip("="),
        },
    )

    response = client.post(
        f"{MAILS_URL}/attachments/mail_attachment_fetch_job/fetch-job"
    )

    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    assert Orchestrator(worker_id="worker-test").run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            "SELECT status, error_type FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        attachment_row = connection.execute(
            """
            SELECT gmail_message_attachments.storage_object_id,
                   storage_objects.scope,
                   storage_objects.original_filename,
                   storage_objects.byte_size,
                   storage_objects.storage_path
            FROM gmail_message_attachments
            JOIN storage_objects
                ON storage_objects.id = gmail_message_attachments.storage_object_id
            WHERE gmail_message_attachments.id = ?
            """,
            ("mail_attachment_fetch_job",),
        ).fetchone()

    assert job_row == ("succeeded", None)
    assert attachment_row[1:4] == (
        "managed",
        "fetch-job.txt",
        len(b"background attachment"),
    )
    assert (database_path.parent / "storage" / attachment_row[4]).is_file()


def test_llm_block_filter_marks_matching_mail_and_worker_skips_llm(
    client,
    database_path,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Password reset notice",
        body_text="Your temporary password is hunter2.",
    )

    response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "temporary password", "reason": "May contain password."},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filter"]["query_text"] == "temporary password"
    assert data["filter"]["is_enabled"] is True
    assert data["matched"] == 1
    assert data["changed"] == 1
    assert data["items"][0]["id"] == message_id
    assert data["items"][0]["llm_block_reason"] == "May contain password."

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["auto_state"]["llm_blocked"] is True
    assert detail["auto_state"]["llm_block_reason"] == "May contain password."
    assert detail["auto_state"]["effective_importance"] == "pinned"
    assert detail["message"]["effective_importance"] == "pinned"
    assert detail["message"]["llm_blocked"] is True

    run_response = client.post("/api/v1/jobs/run-next")
    assert run_response.status_code == 200
    with sqlite3.connect(database_path) as connection:
        llm_run_count = connection.execute("SELECT COUNT(*) FROM llm_runs").fetchone()
        job_row = connection.execute(
            """
            SELECT status, result_json
            FROM jobs
            WHERE job_type = 'mail_importance_classification'
            """
        ).fetchone()

    assert llm_run_count == (0,)
    assert job_row[0] == "succeeded"
    assert json.loads(job_row[1])["reason"] == "llm_blocked"
    assert json.loads(job_row[1])["effective_importance"] == "pinned"


def test_llm_blocked_mail_can_be_allowed_again(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Temporary password note",
        body_text="The temporary password was sent by mistake.",
    )
    block_response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "temporary password", "reason": "May contain password."},
    )
    assert block_response.status_code == 200

    allow_response = client.post(f"{MAILS_URL}/{message_id}/allow-llm")

    assert allow_response.status_code == 200
    detail = allow_response.json()["data"]
    assert detail["auto_state"]["llm_blocked"] is False
    assert detail["auto_state"]["llm_block_reason"] is None
    assert detail["auto_state"]["llm_blocked_at"] is None
    assert detail["auto_state"]["effective_importance"] == "unclassified"
    assert detail["message"]["llm_blocked"] is False
    assert detail["message"]["effective_importance"] == "unclassified"


def test_llm_block_filter_applies_to_newly_ingested_mail_before_llm_job(
    client,
    database_path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Blocked Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "blocked.sender@example.com", "is_primary": True}
            ],
        },
    )
    register_response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "secret token", "reason": "Contains credential material."},
    )

    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_future_llm_block",
        gmail_thread_id="thread_future_llm_block",
        from_address="blocked.sender@example.com",
        subject="Routine note",
        received_at="2026-05-23T13:30:00+09:00",
        body_text="Please use this secret token only once.",
    )

    assert register_response.status_code == 200
    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    detail = detail_response.json()["data"]
    assert detail["auto_state"]["llm_blocked"] is True
    assert detail["auto_state"]["llm_block_reason"] == "Contains credential material."
    assert detail["auto_state"]["effective_importance"] == "pinned"
    assert detail["message"]["effective_importance"] == "pinned"

    with sqlite3.connect(database_path) as connection:
        jobs = connection.execute(
            """
            SELECT job_type
            FROM jobs
            WHERE payload_json LIKE ?
            """,
            (f"%{message_id}%",),
        ).fetchall()

    assert jobs == []


def test_llm_block_filters_can_be_listed_and_disabled(client) -> None:
    create_response = client.post(
        f"{MAILS_URL}/llm-block-filter",
        json={"q": "private material", "reason": "Private material."},
    )
    block_filter = create_response.json()["data"]["filter"]

    list_response = client.get(f"{MAILS_URL}/llm-block-filters")
    disable_response = client.patch(
        f"{MAILS_URL}/llm-block-filters/{block_filter['id']}",
        json={"is_enabled": False},
    )

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["id"] == block_filter["id"]
    assert disable_response.status_code == 200
    assert disable_response.json()["data"]["is_enabled"] is False


def test_llm_model_config_lists_profiles_and_updates_assignment(client) -> None:
    config_response = client.get(f"{MAILS_URL}/llm-model-config")

    assert config_response.status_code == 200
    config = config_response.json()["data"]
    profile_ids = {profile["id"] for profile in config["profiles"]}
    assert {"openai_gpt_5_2", "openai_gpt_5_4"} <= profile_ids
    importance_config = next(
        item
        for item in config["functions"]
        if item["function_type"] == "mail_importance_classification"
    )
    assert importance_config["profile_id"] == "mock"

    update_response = client.patch(
        f"{MAILS_URL}/llm-model-config",
        json={
            "function_type": "mail_importance_classification",
            "profile_id": "openai_gpt_5_2",
        },
    )

    assert update_response.status_code == 200
    updated_importance_config = next(
        item
        for item in update_response.json()["data"]["functions"]
        if item["function_type"] == "mail_importance_classification"
    )
    assert updated_importance_config["profile_id"] == "openai_gpt_5_2"


def test_send_mail_records_mock_send_request(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Reply source",
        body_text="Original body.",
    )

    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com", "reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Reply source",
            "body_text": "Thanks.\n\n> Original body.",
            "attachments": [
                {
                    "filename": "agenda.pdf",
                    "content_type": "application/pdf",
                    "data_base64": base64.b64encode(b"agenda").decode("ascii"),
                    "size": 6,
                }
            ],
            "reply_to_message_id": message_id,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"].startswith("mail_send_")
    assert data["status"] == "scheduled_mock"
    assert data["to_addresses"] == ["reply@example.com"]
    assert data["cc_addresses"] == ["team@example.com"]
    assert data["bcc_addresses"] == []
    assert data["subject"] == "Reply source"
    assert data["body_text"] == "Thanks.\n\n> Original body."
    assert data["attachment_names"] == ["agenda.pdf"]
    assert data["reply_to_message_id"] == message_id
    assert data["sent_message_id"] is None
    assert data["scheduled_at"] is not None

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT status, to_addresses_json, attachment_names_json, scheduled_at "
            "FROM mail_send_requests"
        ).fetchall()
        jobs = connection.execute(
            "SELECT job_type, status, payload_json FROM jobs "
            "WHERE job_type = 'mail_send_mock'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "scheduled_mock"
    assert rows[0][1] == '["reply@example.com"]'
    assert rows[0][2] == '["agenda.pdf"]'
    assert rows[0][3] is not None
    assert len(jobs) == 1
    assert jobs[0][1] == "pending"
    assert json.loads(jobs[0][2])["send_request_id"] == data["id"]


def test_send_mail_expands_contact_tag_recipient_selectors(client, database_path) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Student One",
            "status": "active",
            "tags": ["student", "lab-member"],
            "email_addresses": [
                {"email_address": "student.one@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Student Alumni",
            "status": "active",
            "tags": ["student", "lab-alumni"],
            "email_addresses": [
                {"email_address": "alumni.one@example.com", "is_primary": True}
            ],
        },
    )

    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["{student&!lab-alumni}", "direct@example.com"],
            "subject": "Selector recipients",
            "body_text": "Hello selector recipients.",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["to_addresses"] == [
        "student.one@example.com",
        "direct@example.com",
    ]

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT to_addresses_json FROM mail_send_requests WHERE id = ?",
            (data["id"],),
        ).fetchone()

    assert json.loads(row[0]) == ["student.one@example.com", "direct@example.com"]


def test_send_mail_expands_case_role_recipient_selectors(client) -> None:
    contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Case Reviewer",
            "status": "active",
            "email_addresses": [
                {"email_address": "case.reviewer@example.com", "is_primary": True}
            ],
        },
    )
    owner_contact_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Case Owner",
            "status": "active",
            "email_addresses": [
                {"email_address": "case.owner@example.com", "is_primary": True}
            ],
        },
    )
    case_response = client.post(
        CASES_URL,
        json={
            "name": "Annual Review",
            "description": None,
            "progress_status": "not_started",
            "ball_status": "user",
        },
    )
    case_id = case_response.json()["data"]["case"]["id"]
    contact_id = contact_response.json()["data"]["id"]
    owner_contact_id = owner_contact_response.json()["data"]["id"]
    stakeholder_response = client.post(
        f"{CASES_URL}/{case_id}/stakeholders",
        json={"contact_id": contact_id, "role": "reviewer"},
    )
    assert stakeholder_response.status_code == 200
    owner_stakeholder_response = client.post(
        f"{CASES_URL}/{case_id}/stakeholders",
        json={"contact_id": owner_contact_id, "role": "owner"},
    )
    assert owner_stakeholder_response.status_code == 200

    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["Case:Annual Review:reviewer"],
            "subject": "Case role recipients",
            "body_text": "Hello case reviewers.",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["to_addresses"] == ["case.reviewer@example.com"]

    all_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["Case:Annual Review:ALL"],
            "subject": "All case recipients",
            "body_text": "Hello all case stakeholders.",
        },
    )

    assert all_response.status_code == 200
    assert all_response.json()["data"]["to_addresses"] == [
        "case.reviewer@example.com",
        "case.owner@example.com",
    ]


def test_send_mail_rejects_attachment_names_without_file_data(client) -> None:
    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Attachment names only",
            "body_text": "Body.",
            "attachment_names": ["name-only.pdf"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_send_mail_requests_can_be_listed_for_debug(client) -> None:
    client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["first@example.com"],
            "subject": "First",
            "body_text": "First body.",
        },
    )
    client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["second@example.com"],
            "subject": "Second",
            "body_text": "Second body.",
            "cc_addresses": ["cc@example.com"],
        },
    )

    response = client.get(f"{MAILS_URL}/send-requests")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["subject"] for item in items] == ["Second", "First"]
    assert items[0]["status"] == "scheduled_mock"
    assert items[0]["to_addresses"] == ["second@example.com"]
    assert items[0]["cc_addresses"] == ["cc@example.com"]


def test_send_job_fails_without_gmail_connection(client, database_path) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Reply source",
        body_text="Original body.",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Reply source",
            "body_text": "Thanks.\n\n> Original body.",
            "reply_to_message_id": message_id,
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")

    run_response = client.post("/api/v1/jobs/run-next")

    assert run_response.status_code == 200
    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    detail = detail_response.json()["data"]
    sent_messages = [
        message
        for message in detail["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert sent_messages == []

    with sqlite3.connect(database_path) as connection:
        send_request_row = connection.execute(
            "SELECT status, sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()
        job_row = connection.execute(
            """
            SELECT status, error_type, error_message
            FROM jobs
            WHERE job_type = 'mail_send_mock'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    assert send_request_row == ("failed_gmail", None)
    assert job_row[0] == "failed"
    assert job_row[1] == "RuntimeError"
    assert "Gmail is not connected" in job_row[2]


def test_send_only_sent_message_appears_in_done_list(
    client,
    database_path,
    monkeypatch,
) -> None:
    connect_gmail_send(database_path)
    patch_gmail_send_response(
        monkeypatch,
        gmail_message_id="gmail_sent_standalone",
        gmail_thread_id="thread_sent_standalone",
        subject="Standalone sent mail",
        body_text="This mail starts a new thread.",
        to_address="new.receiver@example.com",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["new.receiver@example.com"],
            "subject": "Standalone sent mail",
            "body_text": "This mail starts a new thread.",
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert run_response.status_code == 200

    list_response = client.get(f"{MAILS_URL}?tab=processed&limit=20")
    items = list_response.json()["data"]["items"]
    sent_item = next(item for item in items if item["subject"] == "Standalone sent mail")

    search_response = client.get(
        f"{MAILS_URL}?tab=all&q=starts%20a%20new%20thread"
    )
    assert search_response.status_code == 200
    assert sent_item["id"] in [
        item["id"] for item in search_response.json()["data"]["items"]
    ]
    assert sent_item["processed_status"] == "processed"
    assert sent_item["read_status"] == "read"
    assert sent_item["effective_importance"] == "sent"

    detail_response = client.get(f"{MAILS_URL}/{sent_item['id']}")
    detail = detail_response.json()["data"]
    assert detail["message"]["body_text"] == "This mail starts a new thread."
    assert detail["message"]["gmail_labels"] == ["SENT"]


def test_send_job_uses_gmail_api_when_gmail_send_scope_is_connected(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Gmail reply source",
        body_text="Original Gmail body.",
    )
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "Gmail reply source",
            "body_text": "Thanks from Gmail.",
            "reply_to_message_id": message_id,
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    sent_raw_messages = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        assert thread_id == "thread_mail_api"
        sent_raw_messages.append(raw_message)
        return {"id": "gmail_sent_real", "threadId": "thread_mail_api"}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == "/users/me/messages/gmail_sent_real":
            return {
                "id": "gmail_sent_real",
                "threadId": "thread_mail_api",
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "snippet": "Thanks from Gmail.",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "reply@example.com"},
                        {"name": "Cc", "value": "team@example.com"},
                        {"name": "Subject", "value": "Gmail reply source"},
                        {"name": "Message-ID", "value": "<gmail-sent-real@example.com>"},
                        {"name": "In-Reply-To", "value": "<mail-api-1@example.com>"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Thanks from Gmail."
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert run_response.status_code == 200
    assert len(sent_raw_messages) == 1
    raw_message = message_from_bytes(sent_raw_messages[0])
    assert raw_message["From"] == "me@example.com"
    assert raw_message["To"] == "reply@example.com"
    assert raw_message["Cc"] == "team@example.com"
    assert raw_message["In-Reply-To"] == "<mail-api-1@example.com>"
    assert raw_message.get_payload().strip() == "Thanks from Gmail."

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    sent_messages = [
        message
        for message in detail_response.json()["data"]["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert len(sent_messages) == 1
    assert sent_messages[0]["gmail_message_id"] == "gmail_sent_real"
    assert sent_messages[0]["from_address"] == "me@example.com"

    with sqlite3.connect(database_path) as connection:
        send_request_row = connection.execute(
            "SELECT status, sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()

    assert send_request_row[0] == "sent_gmail"
    assert send_request_row[1] == sent_messages[0]["id"]


def test_gmail_send_job_builds_attachment_mime_part(
    client,
    database_path,
    monkeypatch,
) -> None:
    draft_response = client.post(
        MAIL_DRAFTS_URL,
        json={
            "to_addresses": ["receiver@example.com"],
            "subject": "Attachment draft",
            "body_text": "Draft body.",
            "attachment_refs": [
                {
                    "name": "draft-note.txt",
                    "content_type": "text/plain",
                    "data_base64": base64.b64encode(b"draft attachment").decode("ascii"),
                },
            ],
        },
    )
    draft_storage_object_id = draft_response.json()["data"]["attachment_refs"][0][
        "storage_object_id"
    ]
    attachment_upload_response = client.post(
        "/api/v1/storage/tmp",
        json={
            "filename": "note.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"attached text").decode("ascii"),
        },
    )
    storage_object_id = attachment_upload_response.json()["data"]["storage_object"]["id"]
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["receiver@example.com"],
            "subject": "Attachment mail",
            "body_text": "Please see attached.",
            "attachments": [
                {
                    "filename": "note.txt",
                    "content_type": "text/plain",
                    "storage_object_id": storage_object_id,
                    "size": 13,
                }
            ],
        },
    )
    send_request_id = send_response.json()["data"]["id"]
    assert send_response.json()["data"]["attachment_names"] == ["note.txt"]
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_google_gmail_oauth_connection",
                "google_gmail_oauth_connection",
                json.dumps(
                    {
                        "access_token": "gmail-send-access-token",
                        "token_expires_at": "2099-05-26T23:00:00+09:00",
                        "connected_at": "2026-05-26T08:00:00+09:00",
                        "scopes": [
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.send",
                        ],
                    }
                ),
                "2026-05-26T08:00:00+09:00",
            ),
        )
        connection.commit()

    sent_raw_messages = []

    def fake_gmail_api_send_raw_message(access_token, raw_message, *, thread_id=None):
        assert access_token == "gmail-send-access-token"
        assert thread_id is None
        sent_raw_messages.append(raw_message)
        return {"id": "gmail_sent_attachment", "threadId": "thread_sent_attachment"}

    def fake_gmail_api_get_json(path, access_token, params=None):
        assert access_token == "gmail-send-access-token"
        if path == "/users/me/profile":
            return {"emailAddress": "me@example.com"}
        if path == "/users/me/messages/gmail_sent_attachment":
            return {
                "id": "gmail_sent_attachment",
                "threadId": "thread_sent_attachment",
                "internalDate": "1779746400000",
                "labelIds": ["SENT"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "receiver@example.com"},
                        {"name": "Subject", "value": "Attachment mail"},
                    ],
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"Please see attached."
                        ).decode("ascii").rstrip("=")
                    },
                },
            }
        raise AssertionError(f"unexpected Gmail API path: {path}")

    from caseclosed import google_integration

    monkeypatch.setattr(
        google_integration,
        "gmail_api_send_raw_message",
        fake_gmail_api_send_raw_message,
    )
    monkeypatch.setattr(
        google_integration,
        "gmail_api_get_json",
        fake_gmail_api_get_json,
    )

    send_now_response = client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now")
    assert send_now_response.status_code == 200
    run_response = client.post("/api/v1/jobs/run-next")

    assert run_response.status_code == 200
    assert run_response.json()["data"]["job_id"] is not None
    assert sent_raw_messages, client.get("/api/v1/jobs").json()
    raw_message = message_from_bytes(sent_raw_messages[0])
    attachments = [
        part
        for part in raw_message.walk()
        if part.get_content_disposition() == "attachment"
    ]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "note.txt"
    assert attachments[0].get_payload(decode=True) == b"attached text"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM storage_objects WHERE id = ?",
            (draft_storage_object_id,),
        ).fetchone()
        send_request_row = connection.execute(
            "SELECT sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()
    assert row == ("deleted",)
    assert send_request_row[0] is not None

    sent_detail_response = client.get(f"{MAILS_URL}/{send_request_row[0]}")
    assert sent_detail_response.status_code == 200
    sent_detail = sent_detail_response.json()["data"]
    assert sent_detail["message"]["has_attachments"] is True
    assert sent_detail["message"]["attachments"][0]["filename"] == "note.txt"
    assert sent_detail["message"]["attachments"][0]["source_type"] == "sent_attachment"
    assert sent_detail["attachments"] == sent_detail["message"]["attachments"]


def test_scheduled_send_request_can_be_rescheduled_sent_now_and_canceled(
    client,
    database_path,
    monkeypatch,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Scheduled source",
        body_text="Original body.",
    )
    schedule_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Scheduled source",
            "body_text": "Later reply.",
            "reply_to_message_id": message_id,
            "scheduled_at": "2099-05-25T09:00:00+09:00",
        },
    )
    send_request = schedule_response.json()["data"]

    assert schedule_response.status_code == 200
    assert send_request["status"] == "scheduled_mock"
    assert send_request["scheduled_at"] == "2099-05-25T09:00:00+09:00"

    detail_response = client.get(f"{MAILS_URL}/{message_id}")
    scheduled_requests = detail_response.json()["data"]["scheduled_send_requests"]
    assert [item["id"] for item in scheduled_requests] == [send_request["id"]]

    reschedule_response = client.patch(
        f"{MAILS_URL}/send-requests/{send_request['id']}/schedule",
        json={"scheduled_at": "2099-05-25T10:30:00+09:00"},
    )
    assert reschedule_response.status_code == 200
    assert reschedule_response.json()["data"]["status"] == "scheduled_mock"
    assert reschedule_response.json()["data"]["scheduled_at"] == (
        "2099-05-25T10:30:00+09:00"
    )

    cancel_response = client.post(f"{MAILS_URL}/send-requests/{send_request['id']}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "canceled"

    edit_source_response = client.get(
        f"{MAILS_URL}/send-requests/{send_request['id']}"
    )
    assert edit_source_response.status_code == 200
    assert edit_source_response.json()["data"]["body_text"] == "Later reply."
    assert edit_source_response.json()["data"]["reply_to_message_id"] == message_id

    after_cancel_detail_response = client.get(f"{MAILS_URL}/{message_id}")
    assert after_cancel_detail_response.json()["data"]["scheduled_send_requests"] == []

    second_schedule_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "subject": "Scheduled source",
            "body_text": "Send now reply.",
            "reply_to_message_id": message_id,
            "scheduled_at": "2099-05-25T11:00:00+09:00",
        },
    )
    second_id = second_schedule_response.json()["data"]["id"]
    connect_gmail_send(database_path)
    patch_gmail_send_response(
        monkeypatch,
        gmail_message_id="gmail_sent_scheduled",
        gmail_thread_id="thread_mail_api",
        subject="Scheduled source",
        body_text="Send now reply.",
        to_address="reply@example.com",
        in_reply_to="<mail-api-1@example.com>",
    )
    send_now_response = client.post(f"{MAILS_URL}/send-requests/{second_id}/send-now")
    run_response = client.post("/api/v1/jobs/run-next")

    assert send_now_response.status_code == 200
    assert send_now_response.json()["data"]["status"] == "queued_mock"
    assert send_now_response.json()["data"]["scheduled_at"] is None
    assert run_response.status_code == 200

    detail_after_send_response = client.get(f"{MAILS_URL}/{message_id}")
    sent_messages = [
        message
        for message in detail_after_send_response.json()["data"]["thread_messages"]
        if "SENT" in message["gmail_labels"]
    ]
    assert len(sent_messages) == 1
    assert sent_messages[0]["body_text"] == "Send now reply."

    with sqlite3.connect(database_path) as connection:
        statuses = dict(
            connection.execute(
                "SELECT id, status FROM mail_send_requests WHERE id IN (?, ?)",
                (send_request["id"], second_id),
            ).fetchall()
        )
    assert statuses == {send_request["id"]: "canceled", second_id: "sent_gmail"}


def test_reschedule_supersedes_pending_and_already_claimed_old_jobs(
    client,
    database_path,
) -> None:
    first_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["first@example.com"],
            "subject": "Pending old schedule",
            "body_text": "Do not send at the old time.",
            "scheduled_at": "2099-05-25T09:00:00+09:00",
        },
    )
    first_id = first_response.json()["data"]["id"]
    with sqlite3.connect(database_path) as connection:
        first_old_job = connection.execute(
            """
            SELECT id
            FROM jobs
            WHERE job_type = 'mail_send_mock'
              AND json_extract(payload_json, '$.send_request_id') = ?
            """,
            (first_id,),
        ).fetchone()

    first_reschedule = client.patch(
        f"{MAILS_URL}/send-requests/{first_id}/schedule",
        json={"scheduled_at": "2099-05-25T10:00:00+09:00"},
    )
    assert first_reschedule.status_code == 200
    with sqlite3.connect(database_path) as connection:
        first_jobs = connection.execute(
            """
            SELECT id, status, available_at, result_json
            FROM jobs
            WHERE job_type = 'mail_send_mock'
              AND json_extract(payload_json, '$.send_request_id') = ?
            ORDER BY created_at, id
            """,
            (first_id,),
        ).fetchall()
    first_jobs_by_id = {row[0]: row for row in first_jobs}
    superseded_job = first_jobs_by_id[first_old_job[0]]
    assert superseded_job[1:3] == (
        "succeeded",
        "2099-05-25T09:00:00+09:00",
    )
    assert json.loads(superseded_job[3])["status"] == "superseded"
    replacement_jobs = [row for row in first_jobs if row[0] != first_old_job[0]]
    assert len(replacement_jobs) == 1
    assert replacement_jobs[0][1:3] == (
        "pending",
        "2099-05-25T10:00:00+09:00",
    )

    second_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["second@example.com"],
            "subject": "Claimed old schedule",
            "body_text": "A claimed stale job must not send.",
            "scheduled_at": "2099-05-25T11:00:00+09:00",
        },
    )
    second_id = second_response.json()["data"]["id"]
    with sqlite3.connect(database_path) as connection:
        second_old_job = connection.execute(
            """
            SELECT id, payload_json, available_at
            FROM jobs
            WHERE job_type = 'mail_send_mock'
              AND json_extract(payload_json, '$.send_request_id') = ?
            """,
            (second_id,),
        ).fetchone()
        connection.execute(
            "UPDATE jobs SET status = 'running' WHERE id = ?",
            (second_old_job[0],),
        )
        connection.commit()

    second_reschedule = client.patch(
        f"{MAILS_URL}/send-requests/{second_id}/schedule",
        json={"scheduled_at": "2099-05-25T12:00:00+09:00"},
    )
    assert second_reschedule.status_code == 200
    stale_result = handle_mail_send_mock(
        SimpleNamespace(
            payload_json=second_old_job[1],
            available_at=second_old_job[2],
        )
    )
    assert stale_result["status"] == "superseded"
    assert stale_result["reason"] == "request_version_changed"
    with sqlite3.connect(database_path) as connection:
        second_request = connection.execute(
            "SELECT status, scheduled_at, sent_message_id FROM mail_send_requests WHERE id = ?",
            (second_id,),
        ).fetchone()
    assert second_request == ("scheduled_mock", "2099-05-25T12:00:00+09:00", None)

    past_response = client.patch(
        f"{MAILS_URL}/send-requests/{second_id}/schedule",
        json={"scheduled_at": "2000-01-01T00:00:00+09:00"},
    )
    assert past_response.status_code == 422

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE mail_send_requests SET status = 'sending_gmail' WHERE id = ?",
            (second_id,),
        )
        connection.commit()
    already_sending_response = client.patch(
        f"{MAILS_URL}/send-requests/{second_id}/schedule",
        json={"scheduled_at": "2099-05-25T13:00:00+09:00"},
    )
    assert already_sending_response.status_code == 409


def test_send_only_scheduled_request_appears_in_done_list_and_detail(client) -> None:
    response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["new.receiver@example.com"],
            "cc_addresses": ["team@example.com"],
            "subject": "New scheduled mail",
            "body_text": "This is a send-only scheduled mail.",
            "scheduled_at": "2099-05-25T15:00:00+09:00",
        },
    )
    send_request = response.json()["data"]

    list_response = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2099-05-25T00:00:00%2B09:00&date_to=2099-05-25T23:59:59%2B09:00"
    )
    dates_response = client.get(f"{MAILS_URL}/dates?tab=processed")
    detail_response = client.get(f"{MAILS_URL}/{send_request['id']}")

    assert response.status_code == 200
    assert send_request["status"] == "scheduled_mock"
    list_items = list_response.json()["data"]["items"]
    assert [item["id"] for item in list_items] == [send_request["id"]]
    assert list_items[0]["processed_status"] == "processed"
    assert list_items[0]["read_status"] == "read"
    assert list_items[0]["effective_importance"] == "sent"
    assert list_items[0]["received_date"] == "2099-05-25"
    assert dates_response.json()["data"]["items"] == [
        {"date": "2099-05-25", "count": 1}
    ]

    detail = detail_response.json()["data"]
    assert detail["message"]["id"] == send_request["id"]
    assert detail["message"]["thread_id"].startswith("provisional_thread_")
    assert detail["thread_messages"] == []
    assert [item["id"] for item in detail["scheduled_send_requests"]] == [
        send_request["id"]
    ]


def test_send_mail_requires_recipient_and_existing_reply_target(client) -> None:
    missing_recipient_response = client.post(
        f"{MAILS_URL}/send",
        json={"to_addresses": [], "body_text": "Body."},
    )
    missing_reply_target_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["reply@example.com"],
            "body_text": "Body.",
            "reply_to_message_id": "mail_missing",
        },
    )

    assert missing_recipient_response.status_code == 422
    assert missing_recipient_response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert missing_reply_target_response.status_code == 404
    assert missing_reply_target_response.json()["error"]["code"] == "NOT_FOUND"


def test_mail_draft_generation_standard_prompt_is_saved_in_app_settings(
    client,
    database_path,
) -> None:
    initial_response = client.get(f"{MAILS_URL}/draft-generation-standard-prompt")
    assert initial_response.status_code == 200
    assert initial_response.json()["data"]["standard_prompt"] == ""
    assert initial_response.json()["data"]["generation_language"] == "japanese"

    update_response = client.patch(
        f"{MAILS_URL}/draft-generation-standard-prompt",
        json={
            "standard_prompt": "Use concise academic English.\n",
            "generation_language": "english",
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["data"]["standard_prompt"] == (
        "Use concise academic English."
    )
    assert update_response.json()["data"]["generation_language"] == "english"
    read_response = client.get(f"{MAILS_URL}/draft-generation-standard-prompt")
    assert read_response.status_code == 200
    assert read_response.json()["data"]["standard_prompt"] == (
        "Use concise academic English."
    )
    assert read_response.json()["data"]["generation_language"] == "english"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT value_json
            FROM app_settings
            WHERE key = 'mail_draft_generation_standard_prompt'
            """
        ).fetchone()
        language_row = connection.execute(
            """
            SELECT value_json
            FROM app_settings
            WHERE key = 'mail_draft_generation_language'
            """
        ).fetchone()
    assert row == ('"Use concise academic English."',)
    assert language_row == ('"english"',)


def test_generate_mail_draft_provider_build_error_returns_json_error(
    client, monkeypatch
) -> None:
    import importlib

    mails_module = importlib.import_module("caseclosed.mails")
    provider_module = importlib.import_module("caseclosed.services.llm_provider")

    def fail_provider(_function_type):
        raise provider_module.OpenAIProviderError("OpenAI API key is not configured.")

    monkeypatch.setattr(
        mails_module,
        "build_mail_draft_generation_provider",
        fail_provider,
    )

    response = client.post(
        f"{MAILS_URL}/generate-draft",
        json={
            "to_addresses": ["recipient@example.com"],
            "cc_addresses": [],
            "bcc_addresses": [],
            "subject": "Draft request",
            "body_text": "",
            "auto_body_text": "",
            "instruction": "Write a short message.",
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_PROVIDER_ERROR"
    assert "OpenAI API key is not configured" in response.json()["error"]["message"]

def test_generate_reply_draft_uses_language_policy_without_auto_retry(
    client,
    database_path,
    monkeypatch,
) -> None:
    import importlib

    mails_module = importlib.import_module("caseclosed.mails")
    provider_module = importlib.import_module("caseclosed.services.llm_provider")

    class CapturingDraftProvider:
        provider_name = "test"
        model_name = "language-policy-test"

        def __init__(self) -> None:
            self.calls = []

        def complete_json(self, *, function_type, input_payload):
            self.calls.append(dict(input_payload))
            body = "承知しました。確認します。"
            output = {
                "schema_version": "1.0",
                "subject": "Re: Agenda review",
                "body": body,
                "reasoning_summary": "Generated test draft.",
                "warnings": [],
            }
            return provider_module.LlmProviderResponse(
                output=output,
                output_preview=body,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                estimated_cost=0.1,
            )

    provider = CapturingDraftProvider()
    monkeypatch.setattr(
        mails_module,
        "build_mail_draft_generation_provider",
        lambda _function_type: provider,
    )
    reply_to_message_id = ingest_mail(
        client,
        gmail_message_id="gmail_language_policy_source",
        gmail_thread_id="thread_language_policy_source",
        from_address="sender@example.com",
        subject="Agenda review",
        body_text=(
            "Please review the attached agenda and let me know if you can join "
            "tomorrow. We need your confirmation by Friday morning."
        ),
        received_at="2026-05-23T15:00:00+09:00",
    )
    setting_response = client.patch(
        f"{MAILS_URL}/draft-generation-standard-prompt",
        json={"generation_language": "english"},
    )
    assert setting_response.status_code == 200

    response = client.post(
        f"{MAILS_URL}/generate-draft",
        json={
            "to_addresses": ["sender@example.com"],
            "cc_addresses": [],
            "bcc_addresses": [],
            "subject": "Re: Agenda review",
            "body_text": "",
            "auto_body_text": "On May 23, sender@example.com wrote: ...",
            "reply_to_message_id": reply_to_message_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["body_text"] == "承知しました。確認します。"
    assert len(provider.calls) == 1
    assert provider.calls[0]["reply_language"] == "English"
    assert provider.calls[0]["language_generation_prompt"] == "英語で生成してください。"
    assert "reply to an English email" in provider.calls[0]["language_policy"]
    with sqlite3.connect(database_path) as connection:
        llm_run_row = connection.execute(
            """
            SELECT retry_count, prompt_tokens, completion_tokens, total_tokens,
                   input_source_json, input_diagnostic_json
            FROM llm_runs
            WHERE function_type = 'reply_draft_generation'
            """
        ).fetchone()
    assert llm_run_row[:4] == (0, 10, 5, 15)
    assert json.loads(llm_run_row[4])["generation_language"] == "english"
    assert json.loads(llm_run_row[5])["language_generation_prompt"] == (
        "英語で生成してください。"
    )


def test_mail_detail_keeps_mailing_list_as_from_contact_and_uses_reply_to_sender(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Committee List",
            "avatar_url": "https://example.com/list.png",
            "status": "archived",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "committee-list@example.com", "is_primary": True}
            ],
        },
    )
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "List Writer",
            "avatar_url": "https://example.com/writer.png",
            "status": "active",
            "email_addresses": [
                {"email_address": "writer@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mailing_list_detail",
            "gmail_thread_id": "thread_mailing_list_detail",
            "message_id_header": "<mailing-list-detail@example.com>",
            "subject": "Mailing list detail",
            "from_address": "committee-list@example.com",
            "reply_to_address": "writer@example.com",
            "received_at": "2026-05-23T14:00:00+09:00",
            "body_text": "List mail.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    list_response = client.get(f"{MAILS_URL}?limit=20")
    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert list_response.status_code == 200
    list_item = next(
        item
        for item in list_response.json()["data"]["items"]
        if item["id"] == message_id
    )
    assert list_item["sender_contact"]["display_name"] == "Committee List"
    assert list_item["sender_contact"]["kind"] == "mailing_list"
    assert list_item["sender_contact"]["status"] == "archived"

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["from_contact"]["display_name"] == "Committee List"
    assert message["from_contact"]["kind"] == "mailing_list"
    assert message["from_contact"]["avatar_url"] == "https://example.com/list.png"
    assert message["sender_contact"]["display_name"] == "List Writer"
    assert message["sender_contact"]["kind"] == "person"
    assert message["sender_contact"]["avatar_url"] == "https://example.com/writer.png"


def test_mail_detail_uses_unresolved_reply_to_address_for_mailing_list_sender(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Archive Committee List",
            "status": "archived",
            "kind": "mailing_list",
            "sender_resolution_mode": "reply_to",
            "email_addresses": [
                {"email_address": "archive-committee@example.com", "is_primary": True}
            ],
        },
    )
    response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_mailing_list_unresolved_reply_to",
            "gmail_thread_id": "thread_mailing_list_unresolved_reply_to",
            "message_id_header": "<mailing-list-unresolved-reply-to@example.com>",
            "subject": "Mailing list unresolved reply-to",
            "from_address": "archive-committee@example.com",
            "reply_to_address": "unregistered-writer@example.com",
            "received_at": "2026-05-23T14:10:00+09:00",
            "body_text": "List mail.",
        },
    )
    message_id = response.json()["data"]["message_id"]

    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["from_contact"]["display_name"] == "Archive Committee List"
    assert message["from_contact"]["kind"] == "mailing_list"
    assert message["from_contact"]["sender_resolution_mode"] == "reply_to"
    assert message["reply_to_address"] == "unregistered-writer@example.com"
    assert message["sender_contact"] is None


def test_mail_list_filters_by_importance_processed_and_query(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Review deadline",
        body_text="Please review this before the deadline.",
    )
    client.post(
        f"{MAILS_URL}/{message_id}/importance",
        json={"importance": "Middle"},
    )
    client.post(f"{MAILS_URL}/{message_id}/process", json={"reason": "handled"})

    matching_response = client.get(
        f"{MAILS_URL}?importance=Middle&processed=1&q=deadline"
    )
    empty_response = client.get(f"{MAILS_URL}?importance=High&processed=1&q=deadline")
    unprocessed_response = client.get(f"{MAILS_URL}?processed=0")

    assert matching_response.status_code == 200
    assert [item["id"] for item in matching_response.json()["data"]["items"]] == [
        message_id
    ]
    assert matching_response.json()["data"]["items"][0]["processed_status"] == (
        "processed"
    )
    assert empty_response.json()["data"]["items"] == []
    assert unprocessed_response.json()["data"]["items"] == []


def test_mail_list_supports_matomail_style_tabs_and_read_filter(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Tab Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "tab.sender@example.com", "is_primary": True}
            ],
        },
    )
    unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_unprocessed",
        gmail_thread_id="thread_tab_unprocessed",
        from_address="tab.sender@example.com",
        subject="Unprocessed mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    processed_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_processed",
        gmail_thread_id="thread_tab_processed",
        from_address="tab.sender@example.com",
        subject="Processed mail",
        received_at="2026-05-23T10:00:00+09:00",
    )
    skip_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_skip",
        gmail_thread_id="thread_tab_skip",
        from_address="tab.sender@example.com",
        subject="Skip mail",
        received_at="2026-05-23T11:00:00+09:00",
    )
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_tab_pending",
        gmail_thread_id="thread_tab_pending",
        from_address="pending.tab@example.com",
        subject="Pending mail",
        received_at="2026-05-23T12:00:00+09:00",
    )
    client.post(f"{MAILS_URL}/{processed_id}/process", json={"reason": "handled"})
    client.post(f"{MAILS_URL}/{skip_id}/importance", json={"importance": "Skip"})
    client.post(f"{MAILS_URL}/{unprocessed_id}/read")

    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")
    processed_response = client.get(f"{MAILS_URL}?tab=processed")
    skip_response = client.get(f"{MAILS_URL}?tab=skip")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    read_response = client.get(f"{MAILS_URL}?read=read")
    unread_response = client.get(f"{MAILS_URL}?read=unread&tab=unprocessed")

    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        unprocessed_id
    ]
    assert [item["id"] for item in processed_response.json()["data"]["items"]] == [
        processed_id
    ]
    assert [item["id"] for item in skip_response.json()["data"]["items"]] == [
        skip_id
    ]
    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]
    read_item = read_response.json()["data"]["items"][0]
    assert read_item["id"] == unprocessed_id
    assert read_item["read_status"] == "read"
    assert read_item["received_date"] == "2026-05-23"
    assert isinstance(read_item["importance_rank"], int)
    assert unread_response.json()["data"]["items"] == []


def test_mail_list_needs_action_matches_unprocessed_high_or_middle_messages(
    client,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Needs Action Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "needs.action@example.com", "is_primary": True}
            ],
        },
    )
    processed_high_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_processed_high",
        gmail_thread_id="thread_needs_processed_high_low",
        from_address="needs.action@example.com",
        subject="Processed high older mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    low_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_low_unprocessed",
        gmail_thread_id="thread_needs_processed_high_low",
        from_address="needs.action@example.com",
        subject="Low latest mail",
        received_at="2026-05-23T10:00:00+09:00",
    )
    high_same_thread_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_high_same_thread",
        gmail_thread_id="thread_needs_high_low_same_thread",
        from_address="needs.action@example.com",
        subject="High same-thread action mail",
        received_at="2026-05-23T10:30:00+09:00",
    )
    low_same_thread_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_low_same_thread",
        gmail_thread_id="thread_needs_high_low_same_thread",
        from_address="needs.action@example.com",
        subject="Low same-thread mail",
        received_at="2026-05-23T10:45:00+09:00",
    )
    high_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_high_unprocessed",
        gmail_thread_id="thread_needs_high_unprocessed",
        from_address="needs.action@example.com",
        subject="High action mail",
        received_at="2026-05-23T11:00:00+09:00",
    )
    middle_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_middle_unprocessed",
        gmail_thread_id="thread_needs_middle_unprocessed",
        from_address="needs.action@example.com",
        subject="Middle action mail",
        received_at="2026-05-23T12:00:00+09:00",
    )
    pinned_unprocessed_id = ingest_mail(
        client,
        gmail_message_id="gmail_needs_pinned_unprocessed",
        gmail_thread_id="thread_needs_pinned_unprocessed",
        from_address="needs.action@example.com",
        subject="Pinned mail",
        received_at="2026-05-23T13:00:00+09:00",
    )
    client.post(
        f"{MAILS_URL}/{processed_high_id}/importance",
        json={"importance": "High"},
    )
    client.post(f"{MAILS_URL}/{processed_high_id}/process", json={"reason": "handled"})
    client.post(f"{MAILS_URL}/{low_unprocessed_id}/importance", json={"importance": "Low"})
    client.post(f"{MAILS_URL}/{high_same_thread_id}/importance", json={"importance": "High"})
    client.post(f"{MAILS_URL}/{low_same_thread_id}/importance", json={"importance": "Low"})
    client.post(f"{MAILS_URL}/{high_unprocessed_id}/importance", json={"importance": "High"})
    client.post(
        f"{MAILS_URL}/{middle_unprocessed_id}/importance",
        json={"importance": "Middle"},
    )
    client.post(
        f"{MAILS_URL}/{pinned_unprocessed_id}/importance",
        json={"importance": "Pinned"},
    )

    response = client.get(f"{MAILS_URL}?needs_action=true")

    assert response.status_code == 200
    gmail_thread_ids = {
        item["gmail_thread_id"] for item in response.json()["data"]["items"]
    }
    assert gmail_thread_ids == {
        "thread_needs_high_low_same_thread",
        "thread_needs_high_unprocessed",
        "thread_needs_middle_unprocessed",
    }
    items_by_thread_id = {
        item["gmail_thread_id"]: item for item in response.json()["data"]["items"]
    }
    assert items_by_thread_id["thread_needs_high_low_same_thread"]["id"] == high_same_thread_id


def test_spam_contact_mail_appears_in_skip_tab_with_contact_status(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Spam Sender",
            "status": "spam",
            "email_addresses": [
                {"email_address": "spam.list@example.com", "is_primary": True}
            ],
        },
    )
    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_spam_tab",
        gmail_thread_id="thread_spam_tab",
        from_address="spam.list@example.com",
        subject="Spam tab mail",
        received_at="2026-05-23T13:00:00+09:00",
    )

    skip_response = client.get(f"{MAILS_URL}?tab=skip")

    assert skip_response.status_code == 200
    items = skip_response.json()["data"]["items"]
    assert [item["id"] for item in items] == [message_id]
    assert items[0]["effective_importance"] == "skip"
    assert items[0]["sender_contact"]["status"] == "spam"


def test_mail_list_aggregates_inbound_messages_by_thread(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Thread Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "thread.sender@example.com", "is_primary": True}
            ],
        },
    )
    older_id = ingest_mail(
        client,
        gmail_message_id="gmail_thread_older",
        gmail_thread_id="thread_aggregate",
        from_address="thread.sender@example.com",
        subject="Older inbound",
        received_at="2026-05-23T09:00:00+09:00",
    )
    latest_id = ingest_mail(
        client,
        gmail_message_id="gmail_thread_latest",
        gmail_thread_id="thread_aggregate",
        from_address="thread.sender@example.com",
        subject="Latest inbound",
        received_at="2026-05-23T11:00:00+09:00",
    )
    sent_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_thread_sent",
            "gmail_thread_id": "thread_aggregate",
            "message_id_header": "<gmail-thread-sent@example.com>",
            "subject": "Sent reply",
            "from_address": "me@example.com",
            "gmail_labels": ["SENT"],
            "received_at": "2026-05-23T12:00:00+09:00",
            "body_text": "Outgoing reply.",
        },
    )
    assert sent_response.status_code == 200
    client.post(f"{MAILS_URL}/{older_id}/importance", json={"importance": "High"})
    client.post(f"{MAILS_URL}/{latest_id}/importance", json={"importance": "Low"})
    client.post(f"{MAILS_URL}/{latest_id}/read")
    client.post(f"{MAILS_URL}/{older_id}/unread")

    response = client.get(f"{MAILS_URL}?tab=unprocessed")
    unread_response = client.get(f"{MAILS_URL}?tab=unprocessed&read=unread")
    read_response = client.get(f"{MAILS_URL}?tab=unprocessed&read=read")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["id"] for item in items] == [latest_id]
    assert items[0]["subject"] == "Latest inbound"
    assert items[0]["effective_importance"] == "high"
    assert items[0]["importance_rank"] == 1
    assert items[0]["user_importance"] == "low"
    assert items[0]["read_status"] == "unread"
    assert [item["id"] for item in unread_response.json()["data"]["items"]] == [
        latest_id
    ]
    assert read_response.json()["data"]["items"] == []

    thread_read_response = client.post(f"{MAILS_URL}/{latest_id}/read")

    assert thread_read_response.status_code == 200
    assert {
        message["id"]: message["read_status"]
        for message in thread_read_response.json()["data"]["thread_messages"]
        if message["id"] in {older_id, latest_id}
    } == {older_id: "read", latest_id: "read"}


def test_mail_dates_returns_days_with_mail_for_tab(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Calendar Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "calendar.sender@example.com", "is_primary": True}
            ],
        },
    )
    first_id = ingest_mail(
        client,
        gmail_message_id="gmail_calendar_first",
        gmail_thread_id="thread_calendar_first",
        from_address="calendar.sender@example.com",
        subject="First calendar mail",
        received_at="2026-05-21T09:00:00+09:00",
    )
    second_id = ingest_mail(
        client,
        gmail_message_id="gmail_calendar_second",
        gmail_thread_id="thread_calendar_second",
        from_address="calendar.sender@example.com",
        subject="Second calendar mail",
        received_at="2026-05-23T09:00:00+09:00",
    )
    client.post(f"{MAILS_URL}/{second_id}/process", json={"reason": "handled"})

    all_response = client.get(f"{MAILS_URL}/dates")
    unprocessed_response = client.get(f"{MAILS_URL}/dates?tab=unprocessed")
    processed_response = client.get(f"{MAILS_URL}/dates?tab=processed")

    assert all_response.status_code == 200
    assert all_response.json()["data"]["items"] == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-23", "count": 1},
    ]
    assert unprocessed_response.json()["data"]["items"] == [
        {"date": "2026-05-21", "count": 1}
    ]
    assert processed_response.json()["data"]["items"] == [
        {"date": "2026-05-23", "count": 1}
    ]
    assert first_id != second_id


def test_thread_mail_is_grouped_by_thread_and_day(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Daily Thread Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "daily.thread@example.com", "is_primary": True}
            ],
        },
    )
    first_id = ingest_mail(
        client,
        gmail_message_id="gmail_daily_thread_first",
        gmail_thread_id="thread_daily_group",
        from_address="daily.thread@example.com",
        subject="Daily thread first",
        received_at="2026-05-21T09:00:00+09:00",
    )
    second_id = ingest_mail(
        client,
        gmail_message_id="gmail_daily_thread_second",
        gmail_thread_id="thread_daily_group",
        from_address="daily.thread@example.com",
        subject="Daily thread second",
        received_at="2026-05-23T09:00:00+09:00",
    )
    sent_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_daily_thread_sent",
            "gmail_thread_id": "thread_daily_group",
            "message_id_header": "<gmail-daily-thread-sent@example.com>",
            "subject": "Daily thread reply",
            "from_address": "me@example.com",
            "gmail_labels": ["SENT"],
            "received_at": "2026-05-24T09:00:00+09:00",
            "body_text": "Sent reply.",
        },
    )
    sent_id = sent_response.json()["data"]["message_id"]
    client.post(f"{MAILS_URL}/{first_id}/process", json={"reason": "handled"})

    all_dates = client.get(f"{MAILS_URL}/dates").json()["data"]["items"]
    processed_dates = client.get(f"{MAILS_URL}/dates?tab=processed").json()["data"]["items"]
    unprocessed_dates = client.get(
        f"{MAILS_URL}/dates?tab=unprocessed"
    ).json()["data"]["items"]

    assert all_dates == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-23", "count": 1},
        {"date": "2026-05-24", "count": 1},
    ]
    assert processed_dates == [
        {"date": "2026-05-21", "count": 1},
        {"date": "2026-05-24", "count": 1},
    ]
    assert unprocessed_dates == [{"date": "2026-05-23", "count": 1}]

    day1 = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2026-05-21T00:00:00+09:00"
        "&date_to=2026-05-21T23:59:59+09:00"
    ).json()["data"]["items"]
    day2 = client.get(
        f"{MAILS_URL}?tab=unprocessed&date_from=2026-05-23T00:00:00+09:00"
        "&date_to=2026-05-23T23:59:59+09:00"
    ).json()["data"]["items"]
    day3 = client.get(
        f"{MAILS_URL}?tab=processed&date_from=2026-05-24T00:00:00+09:00"
        "&date_to=2026-05-24T23:59:59+09:00"
    ).json()["data"]["items"]

    assert [item["id"] for item in day1] == [first_id]
    assert [item["id"] for item in day2] == [second_id]
    assert [item["id"] for item in day3] == [sent_id]
    assert day3[0]["processed_status"] == "processed"
    assert day3[0]["effective_importance"] == "sent"


def test_mail_list_filters_pending_dates_and_and_query(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Senders",
            "status": "active",
            "email_addresses": [
                {"email_address": "alpha.sender@example.com", "is_primary": True},
                {"email_address": "beta.sender@example.com", "is_primary": False},
            ],
        },
    )
    alpha_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_alpha",
        gmail_thread_id="thread_filter_alpha",
        from_address="alpha.sender@example.com",
        subject="Alpha budget",
        received_at="2026-05-23T10:00:00+09:00",
        body_text="Please review the budget memo.",
    )
    beta_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_beta",
        gmail_thread_id="thread_filter_beta",
        from_address="beta.sender@example.com",
        subject="Beta deadline",
        received_at="2026-05-23T11:00:00+09:00",
        body_text="Ordinary update.",
    )
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_filter_pending",
        gmail_thread_id="thread_filter_pending",
        from_address="pending.filter@example.com",
        subject="Pending sender",
        received_at="2026-05-23T12:00:00+09:00",
        body_text="Needs contact resolution.",
    )
    client.post(f"{MAILS_URL}/{beta_id}/importance", json={"importance": "High"})

    pending_response = client.get(f"{MAILS_URL}?contact_status=pending")
    resolved_response = client.get(f"{MAILS_URL}?contact_status=resolved")
    date_response = client.get(
        f"{MAILS_URL}?date_from=2026-05-23T10:30:00%2B09:00&date_to=2026-05-23T11:30:00%2B09:00"
    )
    and_match_response = client.get(f"{MAILS_URL}?q=alpha%20budget")
    and_empty_response = client.get(f"{MAILS_URL}?q=alpha%20deadline")
    pending_importance_response = client.get(f"{MAILS_URL}?importance=pending")
    high_response = client.get(f"{MAILS_URL}?importance=high")

    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]
    assert [item["id"] for item in resolved_response.json()["data"]["items"]] == [
        beta_id,
        alpha_id,
    ]
    assert [item["id"] for item in date_response.json()["data"]["items"]] == [
        beta_id
    ]
    assert [item["id"] for item in and_match_response.json()["data"]["items"]] == [
        alpha_id
    ]
    assert and_empty_response.json()["data"]["items"] == []
    assert [item["id"] for item in pending_importance_response.json()["data"]["items"]] == [
        pending_id
    ]
    assert [item["id"] for item in high_response.json()["data"]["items"]] == [
        beta_id
    ]


def test_refresh_pending_mail_state_releases_linked_sender(client) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_pending",
        gmail_thread_id="thread_refresh_pending",
        from_address="refresh.pending@example.com",
        subject="Refresh pending sender",
        received_at="2026-05-23T12:10:00+09:00",
        body_text="Needs refresh.",
    )
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Refresh Pending",
            "status": "active",
            "email_addresses": [
                {"email_address": "refresh.pending@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200

    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")
    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "not_pending"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] is None
    assert data["mail"]["effective_importance"] == "unclassified"
    assert pending_response.json()["data"]["items"] == []
    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        pending_id
    ]


def test_refresh_pending_mail_state_applies_fixed_contact_importance(
    client,
    database_path,
) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_fixed_rule",
        gmail_thread_id="thread_refresh_fixed_rule",
        from_address="refresh.fixed@example.com",
        subject="Refresh fixed sender",
        received_at="2026-05-23T12:15:00+09:00",
        body_text="This should use fixed importance after contact creation.",
    )
    create_response = client.post(
        CONTACTS_URL,
        json={
            "display_name": "Refresh Fixed",
            "status": "active",
            "mail_importance_rule_action": "fixed",
            "mail_importance_rule_importance": "high",
            "email_addresses": [
                {"email_address": "refresh.fixed@example.com", "is_primary": True}
            ],
        },
    )
    assert create_response.status_code == 200

    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "not_pending"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] is None
    assert data["mail"]["effective_importance"] == "high"
    assert pending_response.json()["data"]["items"] == []
    assert [item["id"] for item in unprocessed_response.json()["data"]["items"]] == [
        pending_id
    ]

    with sqlite3.connect(database_path) as connection:
        job_types = connection.execute(
            """
            SELECT job_type
            FROM jobs
            ORDER BY job_type
            """
        ).fetchall()

    assert ("mail_importance_classification",) not in job_types
    assert ("mail_summary",) in job_types


def test_refresh_pending_mail_state_keeps_unresolved_sender_pending(client) -> None:
    pending_id = ingest_mail(
        client,
        gmail_message_id="gmail_refresh_unresolved",
        gmail_thread_id="thread_refresh_unresolved",
        from_address="refresh.unresolved@example.com",
        subject="Refresh unresolved sender",
        received_at="2026-05-23T12:20:00+09:00",
    )

    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is False
    assert data["reason"] == "pending_address_unresolved"
    assert data["queued_job_id"] is None
    assert data["mail"]["pending_reason"] == "unresolved_from_contact"
    assert [item["id"] for item in pending_response.json()["data"]["items"]] == [
        pending_id
    ]


def test_mail_list_uses_limit_and_cursor_pagination(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Paged Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "paged.sender@example.com", "is_primary": True}
            ],
        },
    )
    newest_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_newest",
        gmail_thread_id="thread_page_newest",
        from_address="paged.sender@example.com",
        subject="Newest",
        received_at="2026-05-23T13:00:00+09:00",
    )
    middle_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_middle",
        gmail_thread_id="thread_page_middle",
        from_address="paged.sender@example.com",
        subject="Middle",
        received_at="2026-05-23T12:00:00+09:00",
    )
    oldest_id = ingest_mail(
        client,
        gmail_message_id="gmail_page_oldest",
        gmail_thread_id="thread_page_oldest",
        from_address="paged.sender@example.com",
        subject="Oldest",
        received_at="2026-05-23T11:00:00+09:00",
    )

    first_response = client.get(f"{MAILS_URL}?limit=2")
    first_data = first_response.json()["data"]
    second_response = client.get(
        f"{MAILS_URL}?limit=2&cursor={first_data['next_cursor']}"
    )
    invalid_response = client.get(f"{MAILS_URL}?cursor=not-a-valid-cursor")

    assert first_response.status_code == 200
    assert first_data["limit"] == 2
    assert [item["id"] for item in first_data["items"]] == [newest_id, middle_id]
    assert first_data["next_cursor"] is not None
    assert [item["id"] for item in second_response.json()["data"]["items"]] == [
        oldest_id
    ]
    assert second_response.json()["data"]["next_cursor"] is None
    assert invalid_response.status_code == 422

    client.post(
        f"{MAILS_URL}/{newest_id}/importance", json={"importance": "Low"}
    )
    client.post(
        f"{MAILS_URL}/{middle_id}/importance", json={"importance": "High"}
    )
    client.post(
        f"{MAILS_URL}/{oldest_id}/importance", json={"importance": "Pinned"}
    )

    importance_first_response = client.get(
        f"{MAILS_URL}?sort=importance&limit=2"
    )
    importance_first_data = importance_first_response.json()["data"]
    importance_second_response = client.get(
        f"{MAILS_URL}?sort=importance&limit=2&cursor={importance_first_data['next_cursor']}"
    )

    assert importance_first_response.status_code == 200
    assert [item["id"] for item in importance_first_data["items"]] == [
        oldest_id,
        middle_id,
    ]
    assert [item["id"] for item in importance_second_response.json()["data"]["items"]] == [
        newest_id
    ]


def test_mail_process_unprocess_and_importance_update(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Routine update",
    )

    importance_response = client.post(
        f"{MAILS_URL}/{message_id}/importance",
        json={"importance": "High"},
    )
    process_response = client.post(
        f"{MAILS_URL}/{message_id}/process",
        json={"reason": "done"},
    )
    unprocess_response = client.post(f"{MAILS_URL}/{message_id}/unprocess")

    assert importance_response.status_code == 200
    assert importance_response.json()["data"]["auto_state"]["effective_importance"] == (
        "high"
    )
    assert importance_response.json()["data"]["user_state"]["user_importance"] == (
        "high"
    )
    assert process_response.json()["data"]["user_state"]["processed_status"] == (
        "processed"
    )
    assert unprocess_response.json()["data"]["user_state"]["processed_status"] == (
        "unprocessed"
    )


def test_request_mail_summary_queues_for_unclassified_mail(
    client,
    database_path,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Manual summary request",
        body_text="Please summarize this even before automatic importance is available.",
    )

    response = client.post(f"{MAILS_URL}/{message_id}/summary")

    assert response.status_code == 200
    job_id = response.json()["data"]["job_id"]
    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            """
            SELECT job_type, status, payload_json
            FROM jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()

    assert job_row[0:2] == ("mail_summary", "pending")
    payload = json.loads(job_row[2])
    assert payload["message_id"] == message_id
    assert payload["force"] is True
    assert payload["reason"] == "manual_request"


def test_mail_detail_reports_active_summary_job(
    client,
) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Summary job visible",
        body_text="The detail view should show that summary is still running.",
    )

    summary_response = client.post(f"{MAILS_URL}/{message_id}/summary")
    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert summary_response.status_code == 200
    assert detail_response.status_code == 200
    summary_jobs = detail_response.json()["data"]["summary_jobs"]
    assert summary_jobs[message_id]["job_id"] == summary_response.json()["data"]["job_id"]
    assert summary_jobs[message_id]["status"] == "pending"


def test_request_mail_summary_rejects_pinned_mail(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Pinned mail to read directly",
        body_text="This should not be summarized.",
    )
    client.post(f"{MAILS_URL}/{message_id}/importance", json={"importance": "Pinned"})

    response = client.post(f"{MAILS_URL}/{message_id}/summary")

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Pinned mail cannot be summarized."


def test_mail_read_unread_update(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Read state update",
    )

    read_response = client.post(f"{MAILS_URL}/{message_id}/read")
    unread_response = client.post(f"{MAILS_URL}/{message_id}/unread")

    assert read_response.status_code == 200
    assert read_response.json()["data"]["user_state"]["read_status"] == "read"
    assert read_response.json()["data"]["user_state"]["read_at"] is not None
    assert unread_response.json()["data"]["user_state"]["read_status"] == "unread"
    assert unread_response.json()["data"]["user_state"]["read_at"] is None


def test_low_mail_review_session_lists_today_low_skip_and_only_promotes_to_middle(
    client,
    certificate_headers,
    monkeypatch,
) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    review_password = "review-only-password"
    monkeypatch.setenv("CASECLOSED_LOW_MAIL_REVIEW_PASSWORD", review_password)
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Review Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "review.sender@example.com", "is_primary": True}
            ],
        },
    )
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    message_id = ingest_mail(
        client,
        gmail_message_id="gmail_review_today_low",
        gmail_thread_id="thread_review_today_low",
        from_address="review.sender@example.com",
        subject="Review this mail",
        received_at=f"{today}T10:30:00+09:00",
        body_text="Full review body.",
    )
    importance_response = client.post(
        f"{MAILS_URL}/{message_id}/importance",
        json={"importance": "low"},
    )
    assert importance_response.status_code == 200
    client.post("/api/v1/auth/logout", headers=certificate_headers)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"password": review_password},
        headers=certificate_headers,
    )
    assert login_response.status_code == 200

    list_response = client.get(f"{MAILS_URL}/review/today")
    assert list_response.status_code == 200
    items = list_response.json()["data"]["items"]
    assert [item["id"] for item in items] == [message_id]
    assert "body_text" not in items[0]

    detail_response = client.get(f"{MAILS_URL}/review/{message_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["body_text"] == "Full review body."

    promote_response = client.post(
        f"{MAILS_URL}/review/{message_id}/promote-to-middle"
    )
    assert promote_response.status_code == 200
    assert promote_response.json()["data"]["importance"] == "middle"
    assert client.get(f"{MAILS_URL}/review/today").json()["data"]["items"] == []


def test_full_session_cannot_use_low_mail_review_api(
    client,
    certificate_headers,
) -> None:
    from conftest import TEST_PASSWORD

    assert client.post(
        "/api/v1/auth/login",
        json={"password": TEST_PASSWORD},
        headers=certificate_headers,
    ).status_code == 200

    response = client.get(f"{MAILS_URL}/review/today")
    assert response.status_code == 403


def test_scheduled_send_case_link_is_transferred_to_sent_mail(
    client,
    database_path,
    monkeypatch,
) -> None:
    case_response = client.post(
        CASES_URL,
        json={
            "name": "Scheduled Send Case",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    case_id = case_response.json()["data"]["case"]["id"]
    send_response = client.post(
        f"{MAILS_URL}/send",
        json={
            "to_addresses": ["scheduled.case@example.com"],
            "subject": "Scheduled Case Link",
            "body_text": "Keep this Case assignment after sending.",
            "scheduled_at": "2099-07-29T15:00:00+09:00",
            "case_ids": [case_id],
        },
    )
    send_request_id = send_response.json()["data"]["id"]

    queued_detail_response = client.get(f"{MAILS_URL}/send-requests/{send_request_id}")
    assert queued_detail_response.status_code == 200
    assert queued_detail_response.json()["data"]["case_ids"] == [case_id]
    provisional_detail = client.get(f"{MAILS_URL}/{send_request_id}").json()["data"]
    assert provisional_detail["case_links"] == [
        {"id": case_id, "case_id": case_id, "title": "Scheduled Send Case"}
    ]

    connect_gmail_send(database_path)
    patch_gmail_send_response(
        monkeypatch,
        gmail_message_id="gmail_scheduled_case_link",
        gmail_thread_id="thread_scheduled_case_link",
        subject="Scheduled Case Link",
        body_text="Keep this Case assignment after sending.",
        to_address="scheduled.case@example.com",
    )
    assert client.post(f"{MAILS_URL}/send-requests/{send_request_id}/send-now").status_code == 200
    assert client.post("/api/v1/jobs/run-next").status_code == 200

    old_url_detail = client.get(f"{MAILS_URL}/{send_request_id}")
    assert old_url_detail.status_code == 200
    detail = old_url_detail.json()["data"]
    assert detail["message"]["id"] != send_request_id
    assert [item["case_id"] for item in detail["case_links"]] == [case_id]

    with sqlite3.connect(database_path) as connection:
        sent_message_id = connection.execute(
            "SELECT sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()[0]
        transferred = connection.execute(
            "SELECT count(1) FROM case_mail_links WHERE case_id = ? AND message_id = ?",
            (case_id, sent_message_id),
        ).fetchone()[0]
    assert transferred == 1


def test_llm_personalization_lists_and_saves_function_instruction(
    client,
    database_path,
) -> None:
    initial_response = client.get(f"{MAILS_URL}/llm-personalization")

    assert initial_response.status_code == 200
    initial_items = initial_response.json()["data"]["functions"]
    importance = next(
        item
        for item in initial_items
        if item["function_type"] == "mail_importance_classification"
    )
    assert importance["instruction_text"] == ""
    assert importance["is_enabled"] is False

    update_response = client.patch(
        f"{MAILS_URL}/llm-personalization",
        json={
            "function_type": "mail_importance_classification",
            "instruction_text": "Teaching deadlines should be treated as important.\n",
            "is_enabled": True,
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["instruction_text"] == (
        "Teaching deadlines should be treated as important."
    )
    assert updated["is_enabled"] is True
    assert updated["source"] == "settings"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT instruction_text, function_types_json, is_enabled
            FROM llm_instruction_rules
            WHERE id = ?
            """,
            (
                "llm_instruction_rule_settings_"
                "mail_importance_classification",
            ),
        ).fetchone()
    assert row == (
        "Teaching deadlines should be treated as important.",
        "[\"mail_importance_classification\"]",
        1,
    )
