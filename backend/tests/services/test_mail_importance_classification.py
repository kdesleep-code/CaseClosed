from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

from caseclosed.services.llm_provider import LlmProviderResponse

CONTACTS_URL = "/api/v1/contacts"
MOCK_MAILS_URL = "/api/v1/mails/mock-ingest"


def test_mock_mail_importance_classification_marks_high_mail(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.high@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_high_1",
            "gmail_thread_id": "thread_high",
            "subject": "URGENT: response needed",
            "from_address": "known.high@example.com",
            "received_at": "2026-05-23T12:00:00+09:00",
            "body_text": "Please respond today.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        job_row = connection.execute(
            "SELECT status, result_json FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT provider_name, model_name, input_source_json, output_json, status
            FROM llm_runs
            WHERE function_type = 'mail_importance_classification'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT suggested_importance, effective_importance, llm_run_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert job_row[0] == "succeeded"
    result = json.loads(job_row[1])
    assert result["message_id"] == message_id
    assert result["suggested_importance"] == "high"
    assert result["provider"] == "mock"
    assert result["llm_run_id"].startswith("llm_run_")
    assert llm_run_row[0:2] == ("mock", "deterministic-mail-importance-v1")
    assert json.loads(llm_run_row[2]) == {
        "gmail_message_id": "gmail_high_1",
        "message_id": message_id,
        "subject": "URGENT: response needed",
    }
    assert "Please respond today." not in llm_run_row[2]
    assert json.loads(llm_run_row[3])["importance"] == "high"
    assert llm_run_row[4] == "succeeded"
    assert auto_row[0:2] == ("high", "high")
    assert auto_row[2] == result["llm_run_id"]

    list_response = client.get("/api/v1/mails")
    mail_item = list_response.json()["data"]["items"][0]
    assert mail_item["id"] == message_id
    assert mail_item["effective_importance"] == "high"
    assert mail_item["pending_reason"] is None


def test_openai_mail_importance_provider_is_used_when_api_key_is_configured(
    client,
    database_path: Path,
    monkeypatch,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "OpenAI Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "openai.sender@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_openai_importance_1",
            "gmail_thread_id": "thread_openai_importance",
            "subject": "Please review",
            "from_address": "openai.sender@example.com",
            "received_at": "2026-05-23T12:05:00+09:00",
            "body_text": "Please review this message before tomorrow.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    class FakeOpenAIResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": json.dumps(
                        {
                            "importance": "middle",
                            "reasoning_summary": "Review request.",
                        }
                    ),
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "total_tokens": 18,
                    },
                }
            ).encode("utf-8")

    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append((request, timeout))
        return FakeOpenAIResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv(
        "CASECLOSED_LLM_PROFILE_MAIL_IMPORTANCE_CLASSIFICATION",
        "openai_test_profile",
    )
    profile_dir = database_path.parent / "llm_profiles"
    profile_dir.mkdir()
    (profile_dir / "openai_test_profile.json").write_text(
        json.dumps(
            {
                "id": "openai_test_profile",
                "provider": "openai",
                "model": "gpt-test",
                "timeout_seconds": 12,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CASECLOSED_LLM_MODEL_PROFILES_DIR", str(profile_dir))
    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-openai-mail-importance",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        llm_run_row = connection.execute(
            """
            SELECT provider_name, model_name, input_source_json,
                   input_diagnostic_json, output_json, prompt_tokens,
                   completion_tokens, total_tokens
            FROM llm_runs
            WHERE function_type = 'mail_importance_classification'
            """
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT suggested_importance, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert len(captured_requests) == 1
    assert captured_requests[0][1] == 12
    sent_payload = json.loads(captured_requests[0][0].data.decode("utf-8"))
    assert sent_payload["model"] == "gpt-test"
    assert sent_payload["text"]["format"]["type"] == "json_schema"
    assert "Please review this message before tomorrow." in sent_payload["input"]
    assert llm_run_row[0:2] == ("openai", "gpt-test")
    assert "Please review this message before tomorrow." not in llm_run_row[2]
    assert "Please review this message before tomorrow." not in llm_run_row[3]
    assert json.loads(llm_run_row[4])["importance"] == "middle"
    assert llm_run_row[5:8] == (11, 7, 18)
    assert auto_row == ("middle", "middle")


def test_mock_mail_importance_classification_keeps_external_star_high(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Known Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "known.star@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_star_1",
            "gmail_thread_id": "thread_star",
            "subject": "routine FYI",
            "from_address": "known.star@example.com",
            "received_at": "2026-05-23T12:10:00+09:00",
            "external_starred": True,
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance",
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT external_importance, suggested_importance, effective_importance,
                   llm_run_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert auto_row[0:3] == ("high", "low", "high")
    assert auto_row[3].startswith("llm_run_")


def test_mail_importance_classification_keeps_llm_skip_as_skip(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Skip Judged Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "llm.skip@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_llm_skip_1",
            "gmail_thread_id": "thread_llm_skip",
            "subject": "Automated notice",
            "from_address": "llm.skip@example.com",
            "received_at": "2026-05-23T12:15:00+09:00",
            "body_text": "Noise that the LLM would skip.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    class SkipProvider:
        provider_name = "test"
        model_name = "skip-provider"

        def complete_json(self, *, function_type, input_payload):
            assert function_type == "mail_importance_classification"
            assert input_payload["message_id"] == message_id
            return LlmProviderResponse(
                output={"importance": "skip"},
                output_preview="skip",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                estimated_cost=0.0,
            )

    importance_module = importlib.import_module(
        "caseclosed.services.mail_importance_classification"
    )
    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance-skip",
        handlers={
            "mail_importance_classification": lambda job: (
                importance_module.handle_mail_importance_classification(
                    job,
                    provider=SkipProvider(),
                )
            )
        },
    )

    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        auto_row = connection.execute(
            """
            SELECT suggested_importance, effective_importance, llm_run_id
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        job_row = connection.execute(
            "SELECT status, result_json FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    result = json.loads(job_row[1])
    assert job_row[0] == "succeeded"
    assert result["suggested_importance"] == "skip"
    assert auto_row[0:2] == ("skip", "skip")
    assert auto_row[2] == result["llm_run_id"]


def test_mail_importance_classification_uses_profile_context(
    client,
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO app_settings (id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "setting_user_profile_test",
                "user_profile",
                json.dumps(
                    {
                        "display_name": "Kazumasa Horie",
                        "affiliation": "University of Tsukuba",
                        "research_fields": "sleep medicine, medical AI",
                        "teaching_responsibilities": (
                            "Student international conference support\n"
                            "Medical AI lectures"
                        ),
                        "committee_roles": "Public relations committee",
                        "important_projects": "Home sleep monitoring project",
                        "mail_importance_notes": (
                            "Prioritize student, committee, and review requests."
                        ),
                    },
                    ensure_ascii=False,
                ),
                "2026-06-03T19:00:00+09:00",
            ),
        )
        connection.commit()

    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Profile Context Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "profile.context@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_profile_context_1",
            "gmail_thread_id": "thread_profile_context",
            "subject": "Student review request",
            "from_address": "profile.context@example.com",
            "received_at": "2026-05-23T12:18:00+09:00",
            "body_text": "Please review the student conference abstract.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]

    class CapturingProvider:
        provider_name = "test"
        model_name = "profile-context-provider"

        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def complete_json(self, *, function_type, input_payload):
            assert function_type == "mail_importance_classification"
            self.payloads.append(input_payload)
            return LlmProviderResponse(
                output={"importance": "middle"},
                output_preview="middle",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                estimated_cost=0.0,
            )

    provider = CapturingProvider()
    importance_module = importlib.import_module(
        "caseclosed.services.mail_importance_classification"
    )
    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-importance-profile-context",
        handlers={
            "mail_importance_classification": lambda job: (
                importance_module.handle_mail_importance_classification(
                    job,
                    provider=provider,
                )
            )
        },
    )

    assert orchestrator.run_once() == job_id
    assert len(provider.payloads) == 1
    profile_context = provider.payloads[0]["profile_context"]
    assert profile_context["research_fields"] == "sleep medicine, medical AI"
    assert profile_context["teaching_responsibilities"] == [
        "Student international conference support",
        "Medical AI lectures",
    ]
    assert profile_context["important_projects"] == ["Home sleep monitoring project"]
    assert profile_context["mail_importance_notes"] == (
        "Prioritize student, committee, and review requests."
    )

    with sqlite3.connect(database_path) as connection:
        llm_run_row = connection.execute(
            """
            SELECT input_source_json, input_diagnostic_json
            FROM llm_runs
            WHERE function_type = 'mail_importance_classification'
            """,
        ).fetchone()
        auto_row = connection.execute(
            """
            SELECT suggested_importance, effective_importance
            FROM mail_auto_state
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()

    assert json.loads(llm_run_row[0])["has_profile_context"] is True
    assert json.loads(llm_run_row[1])["has_profile_context"] is True
    assert auto_row == ("middle", "middle")


def test_high_or_middle_mail_queues_and_stores_mock_summary(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Summary Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "summary.sender@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_summary_1",
            "gmail_thread_id": "thread_summary",
            "subject": "Review summary target",
            "from_address": "summary.sender@example.com",
            "received_at": "2026-05-23T12:20:00+09:00",
            "body_text": "Please review the attached plan before the deadline.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-mail-summary",
    )
    importance_job_id = orchestrator.run_once()

    with sqlite3.connect(database_path) as connection:
        summary_job_row = connection.execute(
            """
            SELECT id, status
            FROM jobs
            WHERE job_type = 'mail_summary'
            """
        ).fetchone()

    assert importance_job_id == ingest_response.json()["data"]["queued_job_id"]
    assert summary_job_row[1] == "pending"
    assert orchestrator.run_once() == summary_job_row[0]

    with sqlite3.connect(database_path) as connection:
        thread_summary_job_row = connection.execute(
            """
            SELECT id, status
            FROM jobs
            WHERE job_type = 'mail_thread_summary'
            """
        ).fetchone()

    assert thread_summary_job_row[1] == "pending"
    assert orchestrator.run_once() == thread_summary_job_row[0]

    detail_response = client.get(f"/api/v1/mails/{message_id}")
    list_response = client.get("/api/v1/mails")

    with sqlite3.connect(database_path) as connection:
        summary_row = connection.execute(
            """
            SELECT summary_text, language, llm_run_id
            FROM mail_summaries
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT function_type, provider_name, model_name, input_source_json
            FROM llm_runs
            WHERE id = ?
            """,
            (summary_row[2],),
        ).fetchone()
        thread_summary_row = connection.execute(
            """
            SELECT summary_text, language, llm_run_id
            FROM mail_thread_summaries
            """
        ).fetchone()
        thread_llm_run_row = connection.execute(
            """
            SELECT function_type, provider_name, model_name, input_source_json
            FROM llm_runs
            WHERE id = ?
            """,
            (thread_summary_row[2],),
        ).fetchone()

    assert summary_row[0].startswith("Review summary target")
    assert summary_row[1] == "ja"
    assert llm_run_row[0:3] == (
        "mail_summary",
        "mock",
        "deterministic-mail-summary-v1",
    )
    assert "Please review the attached plan" not in llm_run_row[3]
    assert thread_summary_row[0].startswith("Review summary target")
    assert thread_summary_row[1] == "ja"
    assert thread_llm_run_row[0:3] == (
        "mail_thread_summary",
        "mock",
        "deterministic-mail-thread-summary-v1",
    )
    assert "Please review the attached plan" not in thread_llm_run_row[3]
    assert detail_response.json()["data"]["summary"]["summary_text"].startswith(
        "Review summary target"
    )
    detail_summary_items = detail_response.json()["data"]["summary"]["items"]
    assert len(detail_summary_items) == 1
    assert detail_summary_items[0]["message_id"] == message_id
    assert detail_summary_items[0]["summary_text"].startswith("Review summary target")
    assert detail_summary_items[0]["translation_text"] is None
    assert list_response.json()["data"]["items"][0]["summary"].startswith(
        "Review summary target"
    )


def test_thread_summary_cuts_quoted_reply_sections_before_llm_input() -> None:
    service = importlib.import_module("caseclosed.services.mail_thread_summary")

    body = "\n".join(
        [
            "ハンさん,",
            "",
            "下記、受け取りました。",
            "",
            "2026年5月28日(木) 10:27 SHUYAN HAN <yuimachineheart@gmail.com>:",
            "堀江先生",
            "お世話になっております、Tcredoをお送りします。",
        ]
    )

    assert service.strip_quoted_reply_sections(body) == "\n".join(
        ["ハンさん,", "", "下記、受け取りました。"]
    )


def test_thread_summary_splits_long_input_and_integrates_partial_summaries() -> None:
    service = importlib.import_module("caseclosed.services.mail_thread_summary")

    class CapturingThreadSummaryProvider:
        provider_name = "test"
        model_name = "thread-summary-test"

        def __init__(self) -> None:
            self.payloads = []

        def complete_json(self, *, function_type, input_payload):
            assert function_type == "mail_thread_summary"
            self.payloads.append(input_payload)
            scope = input_payload.get("summary_scope")
            if scope == "final_from_partial_summaries":
                output = {
                    "schema_version": "1.0",
                    "summary": "統合要約",
                    "translation": None,
                    "needs_action": True,
                    "next_action": "確認する。",
                    "key_points": ["統合"],
                    "reply_needed": False,
                    "confidence": 0.8,
                    "reasoning_summary": "Integrated partial summaries.",
                    "warnings": [],
                }
            else:
                output = {
                    "schema_version": "1.0",
                    "summary": f"部分要約 {len(self.payloads)}",
                    "translation": None,
                    "needs_action": True,
                    "next_action": "部分確認。",
                    "key_points": ["部分"],
                    "reply_needed": False,
                    "confidence": 0.7,
                    "reasoning_summary": "Partial summary.",
                    "warnings": [],
                }
            return LlmProviderResponse(
                output=output,
                output_preview=str(output["summary"]),
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                estimated_cost=0.1,
            )

    provider = CapturingThreadSummaryProvider()
    messages = [
        {
            "message_id": f"mail_{index}",
            "gmail_message_id": f"gmail_{index}",
            "received_at": "2026-05-28T10:00:00+09:00",
            "subject": "Long thread",
            "from_address": "sender@example.com",
            "to_addresses_json": "[]",
            "cc_addresses_json": "[]",
            "snippet": "Long",
            "body_text": "x" * 10000,
            "importance": "middle",
        }
        for index in range(5)
    ]

    response, chunk_count = service.complete_thread_summary(
        provider,
        thread_id="thread_1",
        gmail_thread_id="gmail_thread_1",
        subject="Long thread",
        messages=messages,
    )

    assert chunk_count > 1
    assert response.output["summary"] == "統合要約"
    assert response.prompt_tokens == len(provider.payloads) * 10
    assert provider.payloads[-1]["summary_scope"] == "final_from_partial_summaries"
    assert provider.payloads[-1]["messages"] == []
    assert len(provider.payloads[-1]["partial_summaries"]) == chunk_count


def test_thread_summary_incremental_payload_uses_current_summary() -> None:
    service = importlib.import_module("caseclosed.services.mail_thread_summary")

    class CapturingThreadSummaryProvider:
        provider_name = "test"
        model_name = "thread-summary-incremental-test"

        def __init__(self) -> None:
            self.payloads = []

        def complete_json(self, *, function_type, input_payload):
            assert function_type == "mail_thread_summary"
            self.payloads.append(input_payload)
            output = {
                "schema_version": "1.0",
                "summary": "更新済み要約",
                "translation": None,
                "needs_action": True,
                "next_action": "新規メールを確認する",
                "key_points": ["既存要約に新規メールを統合"],
                "reply_needed": False,
                "confidence": 0.8,
                "reasoning_summary": "Incremental summary.",
                "warnings": [],
            }
            return LlmProviderResponse(
                output=output,
                output_preview=str(output["summary"]),
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                estimated_cost=0.1,
            )

    provider = CapturingThreadSummaryProvider()
    response, chunk_count = service.complete_thread_summary(
        provider,
        thread_id="thread_1",
        gmail_thread_id="gmail_thread_1",
        subject="Incremental thread",
        current_thread_summary={
            "summary": "既存のスレッド要約",
            "next_action": "待機",
            "key_points": ["既存ポイント"],
            "needs_action": False,
        },
        messages=[
            {
                "message_id": "mail_new",
                "gmail_message_id": "gmail_new",
                "received_at": "2026-05-28T10:00:00+09:00",
                "subject": "Incremental thread",
                "from_address": "sender@example.com",
                "to_addresses_json": "[]",
                "cc_addresses_json": "[]",
                "snippet": "New",
                "body_text": "This is the only newly arrived mail body.",
                "importance": "middle",
            }
        ],
    )

    assert chunk_count == 1
    assert response.output["summary"] == "更新済み要約"
    assert provider.payloads[0]["summary_scope"] == "incremental_update"
    assert provider.payloads[0]["current_thread_summary"]["summary"] == "既存のスレッド要約"
    assert [message["message_id"] for message in provider.payloads[0]["messages"]] == [
        "mail_new"
    ]


def test_openai_json_response_repairs_invalid_json_once(monkeypatch) -> None:
    provider_module = importlib.import_module("caseclosed.services.llm_provider")

    class FakeOpenAIResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    responses = [
        {
            "output_text": '{"summary": "壊れたJSON",',
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
            },
        },
        {
            "output_text": json.dumps(
                {
                    "schema_version": "1.0",
                    "summary": "修復済み",
                    "translation": None,
                    "needs_action": False,
                    "next_action": None,
                    "key_points": [],
                    "reply_needed": False,
                    "confidence": 0.5,
                    "reasoning_summary": "Repaired invalid JSON.",
                    "warnings": [],
                }
            ),
            "usage": {
                "input_tokens": 13,
                "output_tokens": 5,
                "total_tokens": 18,
            },
        },
    ]
    captured_payloads = []

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode("utf-8")))
        return FakeOpenAIResponse(responses.pop(0))

    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)

    parsed = provider_module.parse_openai_json_response(
        {
            "model": "gpt-json-repair-test",
            "instructions": "Return JSON.",
            "input": "Summarize this.",
            "max_output_tokens": 500,
            "text": {
                "format": provider_module.mail_summary_response_format(
                    "mail_thread_summary"
                )
            },
        },
        api_key="test-key",
        timeout_seconds=10,
    )

    assert parsed.output["summary"] == "修復済み"
    assert parsed.prompt_tokens == 24
    assert parsed.completion_tokens == 12
    assert parsed.total_tokens == 36
    assert parsed.repaired is True
    assert len(captured_payloads) == 2
    assert "Repair the previous assistant output" in captured_payloads[1]["instructions"]
    assert "壊れたJSON" in captured_payloads[1]["input"]


def test_openai_mail_summary_provider_is_used_when_profile_is_configured(
    client,
    database_path: Path,
    monkeypatch,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "OpenAI Summary Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "openai.summary@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_openai_summary_1",
            "gmail_thread_id": "thread_openai_summary",
            "subject": "Please summarize",
            "from_address": "openai.summary@example.com",
            "received_at": "2026-05-23T12:30:00+09:00",
            "body_text": "Please summarize and translate this message today.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]

    class FakeOpenAIResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": json.dumps(
                        {
                            "schema_version": "1.0",
                            "summary": "本日中の要約依頼。",
                            "translation": "本日中にこのメッセージを要約し翻訳してください。",
                            "needs_action": True,
                            "next_action": "要約内容を確認する。",
                            "key_points": ["本日中", "要約と翻訳"],
                            "reply_needed": False,
                            "confidence": 0.8,
                            "reasoning_summary": "Review request.",
                            "warnings": [],
                        }
                    ),
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 15,
                        "total_tokens": 35,
                    },
                }
            ).encode("utf-8")

    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append((request, timeout))
        return FakeOpenAIResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("CASECLOSED_LLM_PROFILE_MAIL_SUMMARY", "openai_summary_profile")
    profile_dir = database_path.parent / "llm_profiles_summary"
    profile_dir.mkdir()
    (profile_dir / "openai_summary_profile.json").write_text(
        json.dumps(
            {
                "id": "openai_summary_profile",
                "provider": "openai",
                "model": "gpt-summary-test",
                "timeout_seconds": 12,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CASECLOSED_LLM_MODEL_PROFILES_DIR", str(profile_dir))
    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-openai-mail-summary",
    )

    importance_job_id = orchestrator.run_once()
    summary_job_id = orchestrator.run_once()
    assert importance_job_id == ingest_response.json()["data"]["queued_job_id"]
    assert summary_job_id is not None

    with sqlite3.connect(database_path) as connection:
        summary_row = connection.execute(
            """
            SELECT summary_text, translation_text, language, llm_run_id
            FROM mail_summaries
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT function_type, provider_name, model_name, input_source_json,
                   input_diagnostic_json, output_json, prompt_tokens,
                   completion_tokens, total_tokens
            FROM llm_runs
            WHERE id = ?
            """,
            (summary_row[3],),
        ).fetchone()

    assert len(captured_requests) == 1
    assert captured_requests[0][1] == 12
    sent_payload = json.loads(captured_requests[0][0].data.decode("utf-8"))
    assert sent_payload["model"] == "gpt-summary-test"
    assert sent_payload["text"]["format"]["name"] == "mail_summary"
    assert "homepage address" in sent_payload["instructions"]
    assert "Full-body translation is disabled" in sent_payload["instructions"]
    assert "Please summarize and translate this message today." in sent_payload["input"]
    assert summary_row[0:3] == (
        "本日中の要約依頼。",
        None,
        "ja",
    )
    assert llm_run_row[0:3] == ("mail_summary", "openai", "gpt-summary-test")
    assert "Please summarize and translate this message today." not in llm_run_row[3]
    assert "Please summarize and translate this message today." not in llm_run_row[4]
    assert json.loads(llm_run_row[5])["summary"] == "本日中の要約依頼。"
    assert llm_run_row[6:9] == (20, 15, 35)


def test_openai_mail_thread_summary_provider_is_used_when_profile_is_configured(
    client,
    database_path: Path,
    monkeypatch,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "OpenAI Thread Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "openai.thread@example.com", "is_primary": True}
            ],
        },
    )
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_openai_thread_1",
            "gmail_thread_id": "thread_openai_thread",
            "subject": "Thread review",
            "from_address": "openai.thread@example.com",
            "received_at": "2026-05-23T12:40:00+09:00",
            "body_text": "Please review this whole thread today.",
        },
    )

    class FakeOpenAIResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "output_text": json.dumps(
                        {
                            "schema_version": "1.0",
                            "summary": "スレッド全体のレビュー依頼。",
                            "translation": "本日中にスレッド全体をレビューしてください。",
                            "needs_action": True,
                            "next_action": "スレッドを確認する。",
                            "key_points": ["レビュー依頼", "本日中"],
                            "reply_needed": False,
                            "confidence": 0.8,
                            "reasoning_summary": "Thread review request.",
                            "warnings": [],
                        }
                    ),
                    "usage": {
                        "input_tokens": 30,
                        "output_tokens": 18,
                        "total_tokens": 48,
                    },
                }
            ).encode("utf-8")

    captured_requests = []

    def fake_urlopen(request, timeout):
        captured_requests.append((request, timeout))
        return FakeOpenAIResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv(
        "CASECLOSED_LLM_PROFILE_MAIL_THREAD_SUMMARY",
        "openai_thread_summary_profile",
    )
    profile_dir = database_path.parent / "llm_profiles_thread"
    profile_dir.mkdir()
    (profile_dir / "openai_thread_summary_profile.json").write_text(
        json.dumps(
            {
                "id": "openai_thread_summary_profile",
                "provider": "openai",
                "model": "gpt-thread-test",
                "timeout_seconds": 12,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CASECLOSED_LLM_MODEL_PROFILES_DIR", str(profile_dir))
    provider_module = importlib.import_module("caseclosed.services.llm_provider")
    monkeypatch.setattr(provider_module, "urlopen", fake_urlopen)

    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-openai-mail-thread-summary",
    )

    importance_job_id = orchestrator.run_once()
    summary_job_id = orchestrator.run_once()
    thread_summary_job_id = orchestrator.run_once()
    assert importance_job_id == ingest_response.json()["data"]["queued_job_id"]
    assert summary_job_id is not None
    assert thread_summary_job_id is not None

    with sqlite3.connect(database_path) as connection:
        thread_summary_row = connection.execute(
            """
            SELECT summary_text, translation_text, language, llm_run_id
            FROM mail_thread_summaries
            """
        ).fetchone()
        llm_run_row = connection.execute(
            """
            SELECT function_type, provider_name, model_name, input_source_json,
                   input_diagnostic_json, output_json, prompt_tokens,
                   completion_tokens, total_tokens
            FROM llm_runs
            WHERE id = ?
            """,
            (thread_summary_row[3],),
        ).fetchone()

    assert len(captured_requests) == 1
    assert captured_requests[0][1] == 12
    sent_payload = json.loads(captured_requests[0][0].data.decode("utf-8"))
    assert sent_payload["model"] == "gpt-thread-test"
    assert sent_payload["text"]["format"]["name"] == "mail_thread_summary"
    assert "Write the summary as bullet points." in sent_payload["instructions"]
    assert "Please review this whole thread today." in sent_payload["input"]
    assert thread_summary_row[0:3] == (
        "スレッド全体のレビュー依頼。",
        None,
        "ja",
    )
    assert llm_run_row[0:3] == (
        "mail_thread_summary",
        "openai",
        "gpt-thread-test",
    )
    assert "Please review this whole thread today." not in llm_run_row[3]
    assert "Please review this whole thread today." not in llm_run_row[4]
    assert json.loads(llm_run_row[5])["summary"] == "スレッド全体のレビュー依頼。"
    assert llm_run_row[6:9] == (30, 18, 48)


def test_case_linked_thread_has_middle_floor_for_llm_skip(
    client,
    database_path: Path,
) -> None:
    client.post(
        CONTACTS_URL,
        json={
            "display_name": "Case Sender",
            "status": "active",
            "email_addresses": [
                {"email_address": "case.floor@example.com", "is_primary": True}
            ],
        },
    )
    case_response = client.post(
        "/api/v1/cases",
        json={
            "name": "Importance floor case",
            "progress_status": "in_progress",
            "ball_status": "user",
        },
    )
    case_id = case_response.json()["data"]["case"]["id"]
    ingest_response = client.post(
        MOCK_MAILS_URL,
        json={
            "gmail_message_id": "gmail_case_floor_1",
            "gmail_thread_id": "thread_case_floor",
            "subject": "Ordinary notice",
            "from_address": "case.floor@example.com",
            "received_at": "2026-07-14T10:00:00+09:00",
            "body_text": "An LLM may consider this low priority.",
        },
    )
    message_id = ingest_response.json()["data"]["message_id"]
    job_id = ingest_response.json()["data"]["queued_job_id"]
    assign_response = client.post(
        f"/api/v1/mails/{message_id}/case-links",
        json={"case_id": case_id},
    )
    assert assign_response.status_code == 200

    class SkipProvider:
        provider_name = "test"
        model_name = "skip-provider"

        def complete_json(self, *, function_type, input_payload):
            return LlmProviderResponse(
                output={"importance": "skip"},
                output_preview="skip",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                estimated_cost=0.0,
            )

    importance_module = importlib.import_module(
        "caseclosed.services.mail_importance_classification"
    )
    orchestrator_module = importlib.import_module("caseclosed.services.orchestrator")
    orchestrator = orchestrator_module.Orchestrator(
        worker_id="worker-case-floor",
        handlers={
            "mail_importance_classification": lambda job: (
                importance_module.handle_mail_importance_classification(
                    job, provider=SkipProvider()
                )
            )
        },
    )
    assert orchestrator.run_once() == job_id

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT suggested_importance, effective_importance "
            "FROM mail_auto_state WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    assert row == ("skip", "middle")
