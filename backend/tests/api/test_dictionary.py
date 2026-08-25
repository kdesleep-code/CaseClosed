from __future__ import annotations


DICTIONARY_URL = "/api/v1/dictionary"


def entry_payload(
    headword: str,
    *,
    aliases: list[str] | None = None,
    interpretation: str = "An interpretation.",
    examples: str | None = None,
    source_urls: list[str] | None = None,
    related_entry_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "headword": headword,
        "aliases": aliases or [],
        "interpretation": interpretation,
        "examples": examples,
        "source_urls": source_urls or [],
        "related_entry_ids": related_entry_ids or [],
    }


def test_dictionary_entries_support_aliases_links_dates_and_crud(client) -> None:
    target_response = client.post(
        DICTIONARY_URL,
        json=entry_payload(
            "対象語",
            aliases=["たいしょうご"],
            interpretation="関連先になる項目。",
        ),
    )
    assert target_response.status_code == 200
    target = target_response.json()["data"]

    create_response = client.post(
        DICTIONARY_URL,
        json=entry_payload(
            "見出し語",
            aliases=["みだしご", "別称"],
            interpretation="対象語を参照する解釈。",
            examples="これは対象語の用例です。",
            source_urls=["https://example.com/reference"],
            related_entry_ids=[target["id"]],
        ),
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    assert created["headword"] == "見出し語"
    assert created["aliases"] == ["みだしご", "別称"]
    assert created["source_urls"] == ["https://example.com/reference"]
    assert created["related_entry_ids"] == [target["id"]]
    assert created["created_at"]
    assert created["updated_at"]

    list_response = client.get(DICTIONARY_URL, params={"query": "別称"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]["items"]] == [created["id"]]

    update_response = client.put(
        f"{DICTIONARY_URL}/{created['id']}",
        json=entry_payload(
            "更新した見出し語",
            aliases=["更新語"],
            interpretation="更新後の解釈。",
        ),
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["headword"] == "更新した見出し語"
    assert updated["version"] == 2
    assert updated["created_at"] == created["created_at"]

    delete_response = client.delete(f"{DICTIONARY_URL}/{target['id']}")
    assert delete_response.status_code == 200
    remaining_response = client.get(DICTIONARY_URL)
    assert remaining_response.status_code == 200
    assert [item["id"] for item in remaining_response.json()["data"]["items"]] == [created["id"]]


def test_dictionary_rejects_duplicate_terms_and_invalid_urls(client) -> None:
    first_response = client.post(
        DICTIONARY_URL,
        json=entry_payload("重複語", aliases=["duplicate"]),
    )
    assert first_response.status_code == 200

    duplicate_response = client.post(
        DICTIONARY_URL,
        json=entry_payload("duplicate"),
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "DUPLICATE_TERM"

    invalid_url_response = client.post(
        DICTIONARY_URL,
        json=entry_payload("URL不正", source_urls=["javascript:alert(1)"]),
    )
    assert invalid_url_response.status_code == 422
    assert invalid_url_response.json()["error"]["code"] == "VALIDATION_ERROR"
