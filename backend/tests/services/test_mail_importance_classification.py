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
    assert detail_summary_items[0]["translation_text"] is not None
    assert list_response.json()["data"]["items"][0]["summary"].startswith(
        "Review summary target"
    )


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
    assert "translation must be a faithful Japanese translation of the full email body" in (
        sent_payload["instructions"]
    )
    assert "Please summarize and translate this message today." in sent_payload["input"]
    assert summary_row[0:3] == (
        "本日中の要約依頼。",
        "本日中にこのメッセージを要約し翻訳してください。",
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
    assert "Please review this whole thread today." in sent_payload["input"]
    assert thread_summary_row[0:3] == (
        "スレッド全体のレビュー依頼。",
        "本日中にスレッド全体をレビューしてください。",
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
