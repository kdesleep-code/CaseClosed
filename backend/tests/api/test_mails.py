from __future__ import annotations

import sqlite3
import json

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"
MAILS_URL = "/api/v1/mails"


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


def test_mail_detail_returns_message_state_and_available_actions(client) -> None:
    message_id = create_known_sender_mail(
        client,
        subject="Detail API test",
        body_text="This body is stored for detail view.",
    )

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
    assert "process" in data["available_actions"]
    assert "set_importance" in data["available_actions"]


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
            "attachment_names": ["agenda.pdf"],
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


def test_mock_send_job_adds_sent_message_to_thread(client, database_path) -> None:
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
    assert len(sent_messages) == 1
    assert sent_messages[0]["subject"] == "Reply source"
    assert sent_messages[0]["from_address"] == "caseclosed.me@example.local"
    assert sent_messages[0]["to_addresses"] == ["reply@example.com"]
    assert sent_messages[0]["cc_addresses"] == ["team@example.com"]
    assert sent_messages[0]["body_text"] == "Thanks.\n\n> Original body."
    assert sent_messages[0]["in_reply_to_header"] == "<mail-api-1@example.com>"

    with sqlite3.connect(database_path) as connection:
        send_request_row = connection.execute(
            "SELECT status, sent_message_id FROM mail_send_requests WHERE id = ?",
            (send_request_id,),
        ).fetchone()

    assert send_request_row[0] == "sent_mock"
    assert send_request_row[1] == sent_messages[0]["id"]


def test_scheduled_send_request_can_be_rescheduled_sent_now_and_canceled(
    client,
    database_path,
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
    assert statuses == {send_request["id"]: "canceled", second_id: "sent_mock"}


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


def test_mail_detail_keeps_mailing_list_as_from_contact(client) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Committee List",
            "avatar_url": "https://example.com/list.png",
            "status": "active",
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

    detail_response = client.get(f"{MAILS_URL}/{message_id}")

    assert detail_response.status_code == 200
    message = detail_response.json()["data"]["message"]
    assert message["from_contact"]["display_name"] == "Committee List"
    assert message["from_contact"]["kind"] == "mailing_list"
    assert message["from_contact"]["avatar_url"] == "https://example.com/list.png"
    assert message["sender_contact"]["display_name"] == "Committee List"


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

    response = client.post(f"{MAILS_URL}/{pending_id}/refresh-pending")
    pending_response = client.get(f"{MAILS_URL}?tab=pending")
    unprocessed_response = client.get(f"{MAILS_URL}?tab=unprocessed")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is True
    assert data["reason"] == "released"
    assert data["queued_job_id"].startswith("job_")
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

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["changed"] is True
    assert data["reason"] == "released_to_fixed_importance"
    assert data["queued_job_id"].startswith("job_")
    assert data["mail"]["pending_reason"] is None
    assert data["mail"]["effective_importance"] == "high"

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
