from __future__ import annotations

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
    assert data["message"]["to_addresses"] == ["user@example.com"]
    assert data["user_state"]["processed_status"] == "unprocessed"
    assert data["user_state"]["read_status"] == "unread"
    assert data["auto_state"]["effective_importance"] == "unclassified"
    assert data["thread_messages"][0]["id"] == message_id
    assert "process" in data["available_actions"]
    assert "set_importance" in data["available_actions"]


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
