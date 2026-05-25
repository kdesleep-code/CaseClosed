from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen

from caseclosed.settings import get_llm_model_profiles_dir
from caseclosed.settings import get_llm_profile_env_key
from caseclosed.settings import get_llm_profile_id
from caseclosed.settings import get_openai_api_key


@dataclass(frozen=True)
class LlmProviderResponse:
    output: dict[str, object]
    output_preview: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None


class LlmProvider(Protocol):
    provider_name: str
    model_name: str

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        """Return a schema-shaped JSON response without exposing provider details."""


@dataclass(frozen=True)
class LlmModelProfile:
    id: str
    provider: str
    model: str
    api_key_env: str | None = None
    endpoint_env: str | None = None
    timeout_seconds: float = 30.0


class MockMailImportanceProvider:
    provider_name = "mock"
    model_name = "deterministic-mail-importance-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_importance_classification":
            raise ValueError(f"Unsupported mock function type: {function_type}")

        text = " ".join(
            str(input_payload.get(key) or "")
            for key in ("subject", "snippet", "body_text", "additional_instruction")
        ).lower()
        instruction = str(input_payload.get("additional_instruction") or "").lower()
        if "always high" in instruction or "常にhigh" in instruction:
            importance = "high"
        elif "always skip" in instruction:
            importance = "skip"
        elif "always low" in instruction or "常にlow" in instruction:
            importance = "low"
        elif any(token in text for token in ["urgent", "至急", "asap", "today"]):
            importance = "high"
        elif any(token in text for token in ["meeting", "deadline", "確認", "review"]):
            importance = "middle"
        else:
            importance = "low"

        return LlmProviderResponse(
            output={"importance": importance},
            output_preview=importance,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class OpenAIProviderError(RuntimeError):
    pass


class OpenAIMailImportanceProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        model_name: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key or read_api_key(api_key_env)
        if self.api_key is None or self.api_key.strip() == "":
            raise OpenAIProviderError("OpenAI API key is not configured.")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_importance_classification":
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": mail_importance_instructions(),
            "input": mail_importance_input_text(input_payload),
            "max_output_tokens": 500,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "mail_importance_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "importance": {
                                "type": "string",
                                "enum": ["high", "middle", "low", "skip"],
                            },
                            "reasoning_summary": {
                                "type": "string",
                            },
                        },
                        "required": ["importance", "reasoning_summary"],
                    },
                },
            },
        }
        response_payload = post_openai_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )
        output_text = extract_response_output_text(response_payload)
        try:
            output = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise OpenAIProviderError("OpenAI response was not valid JSON.") from error

        importance = normalize_openai_importance(output.get("importance"))
        output["importance"] = importance
        return LlmProviderResponse(
            output=output,
            output_preview=importance,
            prompt_tokens=read_usage_int(response_payload, "input_tokens"),
            completion_tokens=read_usage_int(response_payload, "output_tokens"),
            total_tokens=read_usage_int(response_payload, "total_tokens"),
            estimated_cost=None,
        )


def build_mail_importance_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_MAIL_IMPORTANCE)
    if profile is None or profile.provider == "mock":
        return MockMailImportanceProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_MAIL_IMPORTANCE}: {profile.provider}"
        )

    return OpenAIMailImportanceProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_mail_summary_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_MAIL_SUMMARY)
    if profile is None or profile.provider == "mock":
        return MockMailSummaryProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_MAIL_SUMMARY}: {profile.provider}"
        )

    return OpenAIMailSummaryProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_mail_thread_summary_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_MAIL_THREAD_SUMMARY)
    if profile is None or profile.provider == "mock":
        return MockMailThreadSummaryProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_MAIL_THREAD_SUMMARY}: "
            f"{profile.provider}"
        )

    return OpenAIMailThreadSummaryProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


FUNCTION_TYPE_MAIL_IMPORTANCE = "mail_importance_classification"
FUNCTION_TYPE_MAIL_SUMMARY = "mail_summary"
FUNCTION_TYPE_MAIL_THREAD_SUMMARY = "mail_thread_summary"


def load_llm_model_profile(function_type: str) -> LlmModelProfile | None:
    profile_id = get_configured_llm_profile_id(function_type)
    if profile_id is None:
        return None
    if profile_id == "mock":
        return LlmModelProfile(id="mock", provider="mock", model="mock")

    return load_llm_model_profile_by_id(profile_id)


def get_configured_llm_profile_id(function_type: str) -> str | None:
    configured_profile = read_llm_profile_assignment(function_type)
    if configured_profile is not None:
        return configured_profile

    return get_llm_profile_id(function_type)


def read_llm_profile_assignment(function_type: str) -> str | None:
    try:
        from caseclosed.db import runtime
        from caseclosed.db.models import AppSetting

        with runtime.SessionLocal() as session:
            setting = session.get(AppSetting, "setting_llm_profile_assignments")
            if setting is None:
                return None
            assignments = json.loads(setting.value_json)
    except Exception:
        return None

    if not isinstance(assignments, dict):
        return None
    configured_profile = assignments.get(function_type)
    if not isinstance(configured_profile, str) or configured_profile.strip() == "":
        return None
    return configured_profile.strip()


def resolve_llm_model_profile_path(profile_id: str) -> Path:
    if any(separator in profile_id for separator in ("/", "\\")) or profile_id.endswith(
        ".json"
    ):
        raise OpenAIProviderError(
            "LLM model profile id must be a bare file stem, not a path."
        )

    return get_llm_model_profiles_dir() / f"{profile_id}.json"


def read_api_key(api_key_env: str | None) -> str | None:
    if api_key_env is not None and api_key_env.strip() != "":
        import os

        return os.environ.get(api_key_env.strip())

    return get_openai_api_key()


def optional_profile_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def list_llm_model_profiles() -> list[LlmModelProfile]:
    profiles_dir = get_llm_model_profiles_dir()
    profiles: list[LlmModelProfile] = []
    for profile_path in sorted(profiles_dir.glob("*.json")):
        profile_id = profile_path.stem
        profile = load_llm_model_profile_by_id(profile_id)
        profiles.append(profile)
    return profiles


def load_llm_model_profile_by_id(profile_id: str) -> LlmModelProfile:
    profile_path = resolve_llm_model_profile_path(profile_id)
    try:
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OpenAIProviderError(
            f"LLM model profile was not found: {profile_id}"
        ) from error
    except json.JSONDecodeError as error:
        raise OpenAIProviderError(
            f"LLM model profile is not valid JSON: {profile_id}"
        ) from error

    provider = str(profile_data.get("provider") or "").strip()
    model = str(profile_data.get("model") or "").strip()
    if provider == "" or model == "":
        raise OpenAIProviderError(
            f"LLM model profile requires provider and model: {profile_id}"
        )

    return LlmModelProfile(
        id=str(profile_data.get("id") or profile_id),
        provider=provider,
        model=model,
        api_key_env=optional_profile_text(profile_data.get("api_key_env")),
        endpoint_env=optional_profile_text(profile_data.get("endpoint_env")),
        timeout_seconds=float(profile_data.get("timeout_seconds") or 30.0),
    )


def llm_model_profile_data(profile: LlmModelProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "provider": profile.provider,
        "model": profile.model,
        "api_key_env": profile.api_key_env,
        "endpoint_env": profile.endpoint_env,
        "timeout_seconds": profile.timeout_seconds,
    }


def llm_function_label(function_type: str) -> str:
    return function_type.replace("_", " ")


LLM_FUNCTION_TYPES = [
    "mail_importance_classification",
    "contact_registration_prefill",
    "mail_summary",
    "mail_thread_summary",
    "mail_case_selection",
    "reply_draft_generation",
    "new_mail_draft_generation",
    "mail_task_suggestion",
    "calendar_candidate_extraction",
    "preparation_task_suggestion",
]


def llm_function_config_data(function_type: str) -> dict[str, object]:
    return {
        "function_type": function_type,
        "label": llm_function_label(function_type),
        "profile_id": get_configured_llm_profile_id(function_type) or "mock",
        "env_key": get_llm_profile_env_key(function_type),
    }


def mail_importance_instructions() -> str:
    return (
        "You classify the user's email importance for a personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Use high for urgent, time-sensitive, high-impact, or action-critical mail. "
        "Use middle for review, meeting, deadline, coordination, or normal work items. "
        "Use low for FYI, routine notices, newsletters, and non-actionable mail. "
        "Use skip only when the mail is safe to ignore as noise or automated clutter. "
        "Respect any additional contact-specific instruction when present."
    )


def mail_importance_input_text(input_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"Message ID: {input_payload.get('message_id') or ''}",
            f"Gmail message ID: {input_payload.get('gmail_message_id') or ''}",
            f"Subject: {input_payload.get('subject') or ''}",
            f"Snippet: {truncated_text(input_payload.get('snippet'), 1000)}",
            f"Body text: {truncated_text(input_payload.get('body_text'), 8000)}",
            (
                "Additional contact instruction: "
                f"{input_payload.get('additional_instruction') or ''}"
            ),
        ]
    )


def post_openai_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> dict[str, object]:
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise OpenAIProviderError(
            f"OpenAI API request failed with HTTP {error.code}: {body}"
        ) from error
    except URLError as error:
        raise OpenAIProviderError(f"OpenAI API request failed: {error}") from error


def extract_response_output_text(response_payload: dict[str, object]) -> str:
    direct_output_text = response_payload.get("output_text")
    if isinstance(direct_output_text, str) and direct_output_text.strip() != "":
        return direct_output_text

    output_items = response_payload.get("output")
    if not isinstance(output_items, list):
        raise OpenAIProviderError("OpenAI response did not include output text.")

    text_parts: list[str] = []
    for output_item in output_items:
        if not isinstance(output_item, dict):
            continue
        content_items = output_item.get("content")
        if not isinstance(content_items, list):
            continue
        for content_item in content_items:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str):
                text_parts.append(text)

    output_text = "".join(text_parts).strip()
    if output_text == "":
        raise OpenAIProviderError("OpenAI response output text was empty.")
    return output_text


def normalize_openai_importance(value: object) -> str:
    importance = str(value or "").strip().lower()
    if importance not in {"high", "middle", "low", "skip"}:
        raise OpenAIProviderError(f"Invalid OpenAI importance value: {importance}")
    return importance


def read_usage_int(response_payload: dict[str, object], key: str) -> int | None:
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    return value if isinstance(value, int) else None


class MockContactPrefillProvider:
    provider_name = "mock"
    model_name = "deterministic-contact-prefill-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "contact_registration_prefill":
            raise ValueError(f"Unsupported mock function type: {function_type}")

        email_address = str(input_payload["email_address"])
        output = {
            "suggested_display_name": display_name_from_email(email_address),
            "suggested_tags": suggested_tags_for_email(email_address),
            "confidence": 0.5,
        }
        return LlmProviderResponse(
            output=output,
            output_preview=str(output["suggested_display_name"]),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class MockMailSummaryProvider:
    provider_name = "mock"
    model_name = "deterministic-mail-summary-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_summary":
            raise ValueError(f"Unsupported mock function type: {function_type}")

        subject = compact_text(str(input_payload.get("subject") or "No subject"), 80)
        body = normalized_text(
            str(input_payload.get("body_text") or input_payload.get("snippet") or "")
        )
        key_points = [point for point in [subject, compact_text(body, 140)] if point]
        summary = f"{subject}: {body}" if body else subject
        output = {
            "schema_version": "1.0",
            "summary": summary,
            "translation": mock_translation(body),
            "needs_action": any(
                token in f"{subject} {body}".lower()
                for token in ["urgent", "asap", "today", "deadline", "review", "確認", "至急"]
            ),
            "deadline": {
                "date_text": None,
                "normalized_date": None,
                "confidence": 0.0,
            },
            "next_action": "内容を確認する。",
            "key_points": key_points[:3],
            "reply_needed": False,
            "confidence": 0.5,
            "reasoning_summary": "Mock summary generated from subject and body snippet.",
            "warnings": [],
        }
        return LlmProviderResponse(
            output=output,
            output_preview=str(output["summary"]),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class MockMailThreadSummaryProvider:
    provider_name = "mock"
    model_name = "deterministic-mail-thread-summary-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_thread_summary":
            raise ValueError(f"Unsupported mock function type: {function_type}")

        messages = input_payload.get("messages")
        message_count = len(messages) if isinstance(messages, list) else 0
        subject = compact_text(str(input_payload.get("subject") or "No subject"), 80)
        output = {
            "schema_version": "1.0",
            "summary": f"{subject}: {message_count} messages in this thread.",
            "translation": None,
            "needs_action": message_count > 0,
            "next_action": "Review the thread.",
            "key_points": [subject, f"{message_count} messages"],
            "reply_needed": False,
            "confidence": 0.5,
            "reasoning_summary": "Mock thread summary generated from message metadata.",
            "warnings": [],
        }
        return LlmProviderResponse(
            output=output,
            output_preview=str(output["summary"]),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class OpenAIMailSummaryProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        model_name: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key or read_api_key(api_key_env)
        if self.api_key is None or self.api_key.strip() == "":
            raise OpenAIProviderError("OpenAI API key is not configured.")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_summary":
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": mail_summary_instructions(),
            "input": mail_summary_input_text(input_payload),
            "max_output_tokens": 1600,
            "text": {"format": mail_summary_response_format("mail_summary")},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAIMailThreadSummaryProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        model_name: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key or read_api_key(api_key_env)
        if self.api_key is None or self.api_key.strip() == "":
            raise OpenAIProviderError("OpenAI API key is not configured.")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != "mail_thread_summary":
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": mail_thread_summary_instructions(),
            "input": mail_thread_summary_input_text(input_payload),
            "max_output_tokens": 1800,
            "text": {"format": mail_summary_response_format("mail_thread_summary")},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


def openai_structured_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> LlmProviderResponse:
    response_payload = post_openai_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output_text = extract_response_output_text(response_payload)
    try:
        output = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise OpenAIProviderError("OpenAI response was not valid JSON.") from error

    if not isinstance(output, dict):
        raise OpenAIProviderError("OpenAI response JSON was not an object.")
    summary = str(output.get("summary") or "").strip()
    if summary == "":
        raise OpenAIProviderError("OpenAI summary response did not include summary.")
    output["summary"] = summary
    return LlmProviderResponse(
        output=output,
        output_preview=summary,
        prompt_tokens=read_usage_int(response_payload, "input_tokens"),
        completion_tokens=read_usage_int(response_payload, "output_tokens"),
        total_tokens=read_usage_int(response_payload, "total_tokens"),
        estimated_cost=None,
    )


def mail_summary_response_format(name: str) -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "summary": {"type": "string"},
                "translation": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
                "needs_action": {"type": "boolean"},
                "next_action": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
                "key_points": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "reply_needed": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reasoning_summary": {"type": "string"},
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "schema_version",
                "summary",
                "translation",
                "needs_action",
                "next_action",
                "key_points",
                "reply_needed",
                "confidence",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def mail_summary_instructions() -> str:
    return (
        "You summarize one email for a Japanese personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Write summary, translation, next_action, and key_points in Japanese. "
        "If the email is already Japanese, set translation to null. "
        "Keep the summary concise but preserve deadlines, requests, and decisions. "
        "Do not include sensitive full body text unless it is necessary as a short fact."
    )


def mail_thread_summary_instructions() -> str:
    return (
        "You summarize an email thread for a Japanese personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Write summary, translation, next_action, and key_points in Japanese. "
        "Summarize the whole thread chronologically, including current status, "
        "open questions, deadlines, requests, and decisions. "
        "If the thread is already Japanese, set translation to null."
    )


def mail_summary_input_text(input_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"Message ID: {input_payload.get('message_id') or ''}",
            f"Gmail message ID: {input_payload.get('gmail_message_id') or ''}",
            f"Thread ID: {input_payload.get('thread_id') or ''}",
            f"Importance: {input_payload.get('importance') or ''}",
            f"Subject: {input_payload.get('subject') or ''}",
            f"From: {input_payload.get('from_address') or ''}",
            f"To: {input_payload.get('to_addresses_json') or ''}",
            f"Cc: {input_payload.get('cc_addresses_json') or ''}",
            f"Snippet: {truncated_text(input_payload.get('snippet'), 1000)}",
            f"Body text: {truncated_text(input_payload.get('body_text'), 20000)}",
        ]
    )


def mail_thread_summary_input_text(input_payload: dict[str, object]) -> str:
    messages = input_payload.get("messages")
    lines = [
        f"Thread ID: {input_payload.get('thread_id') or ''}",
        f"Gmail thread ID: {input_payload.get('gmail_thread_id') or ''}",
        f"Subject: {input_payload.get('subject') or ''}",
    ]
    if isinstance(messages, list):
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                continue
            lines.extend(
                [
                    f"\nMessage {index}",
                    f"Message ID: {message.get('message_id') or ''}",
                    f"Received at: {message.get('received_at') or ''}",
                    f"From: {message.get('from_address') or ''}",
                    f"To: {message.get('to_addresses_json') or ''}",
                    f"Cc: {message.get('cc_addresses_json') or ''}",
                    f"Importance: {message.get('importance') or ''}",
                    f"Subject: {message.get('subject') or ''}",
                    f"Snippet: {truncated_text(message.get('snippet'), 800)}",
                    f"Body text: {truncated_text(message.get('body_text'), 12000)}",
                ]
            )
    return "\n".join(lines)


def display_name_from_email(email_address: str) -> str:
    local_part = email_address.split("@", maxsplit=1)[0]
    words = [word for word in re.split(r"[._+\-]+", local_part) if word]
    if not words:
        return email_address
    return " ".join(word.capitalize() for word in words)


def truncated_text(value: object, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[truncated {len(text) - limit} characters]"


def compact_text(value: str, limit: int) -> str:
    normalized = normalized_text(value)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)]}..."


def normalized_text(value: str) -> str:
    return " ".join(value.split())


def mock_translation(value: str) -> str | None:
    text = normalized_text(value)
    if text == "":
        return None
    has_ascii_letter = any(("a" <= character.lower() <= "z") for character in text)
    has_japanese = any(
        "\u3040" <= character <= "\u30ff" or "\u4e00" <= character <= "\u9fff"
        for character in text
    )
    if not has_ascii_letter or has_japanese:
        return None
    return f"和訳（モック）: {text}"


def suggested_tags_for_email(email_address: str) -> list[str]:
    local_part, _, domain = email_address.partition("@")
    low_value = f"{local_part} {domain}".lower()
    if any(token in low_value for token in ["no-reply", "noreply", "notification"]):
        return ["system-sender"]
    if any(token in low_value for token in ["list", "newsletter", "announce"]):
        return ["broadcast"]
    return ["unknown-domain"]
