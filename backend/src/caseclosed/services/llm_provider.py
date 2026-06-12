from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


@dataclass(frozen=True)
class ParsedOpenAIJsonResponse:
    output: dict[str, object]
    output_text: str
    response_payload: dict[str, object]
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    repaired: bool = False


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
        parsed_response = parse_openai_json_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )
        output = parsed_response.output
        if not isinstance(output, dict):
            raise OpenAIProviderError("OpenAI response JSON was not an object.")
        importance = normalize_openai_importance(parsed_response.output.get("importance"))
        parsed_response.output["importance"] = importance
        return LlmProviderResponse(
            output=parsed_response.output,
            output_preview=importance,
            prompt_tokens=parsed_response.prompt_tokens,
            completion_tokens=parsed_response.completion_tokens,
            total_tokens=parsed_response.total_tokens,
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


def build_file_summary_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_FILE_SUMMARY)
    if profile is None or profile.provider == "mock":
        return MockFileSummaryProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_FILE_SUMMARY}: {profile.provider}"
        )

    return OpenAIFileSummaryProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_case_current_situation_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_CASE_CURRENT_SITUATION_SUMMARY)
    if profile is None or profile.provider == "mock":
        return MockCaseCurrentSituationProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            "Unsupported provider for "
            f"{FUNCTION_TYPE_CASE_CURRENT_SITUATION_SUMMARY}: {profile.provider}"
        )

    return OpenAICaseCurrentSituationProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_contact_ai_memo_update_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE)
    if profile is None or profile.provider == "mock":
        return MockContactAiMemoUpdateProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE}: "
            f"{profile.provider}"
        )

    return OpenAIContactAiMemoUpdateProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_mail_draft_generation_provider(function_type: str) -> LlmProvider:
    if function_type not in {
        FUNCTION_TYPE_REPLY_DRAFT_GENERATION,
        FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
    }:
        raise OpenAIProviderError(f"Unsupported mail draft generation type: {function_type}")

    profile = load_llm_model_profile(function_type)
    if profile is None or profile.provider == "mock":
        return MockMailDraftGenerationProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {function_type}: {profile.provider}"
        )

    return OpenAIMailDraftGenerationProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_task_prefill_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_TASK_PREFILL_GENERATION)
    if profile is None or profile.provider == "mock":
        return MockTaskPrefillProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_TASK_PREFILL_GENERATION}: "
            f"{profile.provider}"
        )

    return OpenAITaskPrefillProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_calendar_event_prefill_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION)
    if profile is None or profile.provider == "mock":
        return MockCalendarEventPrefillProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION}: "
            f"{profile.provider}"
        )

    return OpenAICalendarEventPrefillProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


def build_case_prefill_provider() -> LlmProvider:
    profile = load_llm_model_profile(FUNCTION_TYPE_CASE_PREFILL_GENERATION)
    if profile is None or profile.provider == "mock":
        return MockCasePrefillProvider()

    if profile.provider != "openai":
        raise OpenAIProviderError(
            f"Unsupported provider for {FUNCTION_TYPE_CASE_PREFILL_GENERATION}: "
            f"{profile.provider}"
        )

    return OpenAICasePrefillProvider(
        api_key_env=profile.api_key_env,
        model_name=profile.model,
        timeout_seconds=profile.timeout_seconds,
    )


FUNCTION_TYPE_MAIL_IMPORTANCE = "mail_importance_classification"
FUNCTION_TYPE_MAIL_SUMMARY = "mail_summary"
FUNCTION_TYPE_MAIL_THREAD_SUMMARY = "mail_thread_summary"
FUNCTION_TYPE_FILE_SUMMARY = "file_summary"
FUNCTION_TYPE_CASE_CURRENT_SITUATION_SUMMARY = "case_current_situation_summary"
FUNCTION_TYPE_CASE_PREFILL_GENERATION = "case_prefill_generation"
FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE = "contact_ai_memo_update"
FUNCTION_TYPE_REPLY_DRAFT_GENERATION = "reply_draft_generation"
FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION = "new_mail_draft_generation"
FUNCTION_TYPE_TASK_PREFILL_GENERATION = "mail_task_suggestion"
FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION = "calendar_candidate_extraction"


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
    "contact_ai_memo_update",
    "mail_summary",
    "mail_thread_summary",
    "file_summary",
    "case_current_situation_summary",
    "case_prefill_generation",
    "mail_case_selection",
    "reply_draft_generation",
    "new_mail_draft_generation",
    "mail_task_suggestion",
    FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION,
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
        "Use the user profile context to judge whether the message is relevant to "
        "the user's research, teaching, committee work, administration, projects, "
        "and usual responsibilities. "
        "Return only JSON matching the provided schema. "
        "Use high for urgent, time-sensitive, high-impact, or action-critical mail. "
        "Use middle for review, meeting, deadline, coordination, or normal work items. "
        "Use low for FYI, routine notices, newsletters, and non-actionable mail. "
        "Use skip only when the mail is safe to ignore as noise or automated clutter. "
        "Respect any additional contact-specific instruction when present."
    )


def profile_context_input_text(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "User profile context: Not configured."
    labels = {
        "display_name": "Name",
        "affiliation": "Affiliation",
        "academic_title": "Academic title",
        "lab_or_group": "Lab/group",
        "research_fields": "Research fields",
        "teaching_responsibilities": "Teaching responsibilities",
        "committee_roles": "Committee roles",
        "administrative_roles": "Administrative roles",
        "important_projects": "Important projects",
        "priority_keywords": "Priority keywords",
        "low_priority_keywords": "Low priority keywords",
        "important_senders_or_domains": "Important senders/domains",
        "expected_response_policy": "Expected response policy",
        "unavailable_times": "Unavailable times",
        "llm_self_description": "Self description",
        "mail_importance_notes": "Mail importance notes",
        "primary_email": "Primary email",
        "email_aliases": "Email aliases",
    }
    lines = ["User profile context:"]
    for key, label in labels.items():
        item = value.get(key)
        if isinstance(item, list):
            text = "; ".join(str(part).strip() for part in item if str(part).strip())
        else:
            text = str(item or "").strip()
        if text:
            lines.append(f"- {label}: {truncated_text(text, 1200)}")
    return "\n".join(lines)


def mail_importance_input_text(input_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            profile_context_input_text(input_payload.get("profile_context")),
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


def parse_openai_json_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> ParsedOpenAIJsonResponse:
    response_payload = post_openai_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output_text = extract_response_output_text(response_payload)
    try:
        output = json.loads(output_text)
    except json.JSONDecodeError:
        repair_payload = build_json_repair_payload(payload, output_text)
        repair_response_payload = post_openai_response(
            repair_payload,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        repaired_output_text = extract_response_output_text(repair_response_payload)
        try:
            repaired_output = json.loads(repaired_output_text)
        except json.JSONDecodeError as error:
            raise OpenAIProviderError(
                "OpenAI response was not valid JSON after repair."
            ) from error
        return ParsedOpenAIJsonResponse(
            output=repaired_output,
            output_text=repaired_output_text,
            response_payload=repair_response_payload,
            prompt_tokens=sum_usage_int(
                response_payload,
                repair_response_payload,
                "input_tokens",
            ),
            completion_tokens=sum_usage_int(
                response_payload,
                repair_response_payload,
                "output_tokens",
            ),
            total_tokens=sum_usage_int(
                response_payload,
                repair_response_payload,
                "total_tokens",
            ),
            repaired=True,
        )

    return ParsedOpenAIJsonResponse(
        output=output,
        output_text=output_text,
        response_payload=response_payload,
        prompt_tokens=read_usage_int(response_payload, "input_tokens"),
        completion_tokens=read_usage_int(response_payload, "output_tokens"),
        total_tokens=read_usage_int(response_payload, "total_tokens"),
        repaired=False,
    )


def build_json_repair_payload(
    original_payload: dict[str, object],
    invalid_output_text: str,
) -> dict[str, object]:
    repair_payload = dict(original_payload)
    repair_payload["instructions"] = (
        "Repair the previous assistant output into valid JSON matching the exact "
        "provided schema. Return only the JSON object. Do not add markdown, code "
        "fences, comments, or explanatory text. Preserve the original meaning as "
        "much as possible. If a required field is missing, fill it with a concise "
        "safe value of the correct type."
    )
    repair_payload["input"] = "\n".join(
        [
            "The previous assistant output was not valid JSON.",
            "Convert it into valid JSON matching the schema.",
            "",
            "Previous invalid output:",
            truncated_text(invalid_output_text, 20000),
        ]
    )
    repair_payload["max_output_tokens"] = original_payload.get("max_output_tokens", 1600)
    return repair_payload


def sum_usage_int(
    first_payload: dict[str, object],
    second_payload: dict[str, object],
    key: str,
) -> int | None:
    first_value = read_usage_int(first_payload, key)
    second_value = read_usage_int(second_payload, key)
    if first_value is None and second_value is None:
        return None
    return (first_value or 0) + (second_value or 0)


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
            str(
                input_payload.get("current_body_text")
                or input_payload.get("body_text")
                or input_payload.get("snippet")
                or ""
            )
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


class MockFileSummaryProvider:
    provider_name = "mock"
    model_name = "deterministic-file-summary-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_FILE_SUMMARY:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        filename = str(input_payload.get("filename") or "file")
        content_type = str(input_payload.get("content_type") or "unknown")
        source_text = normalized_text(str(input_payload.get("source_text") or ""))
        excerpt = compact_text(source_text, 220)
        points = [
            f"File name: {filename}",
            f"Content type: {content_type}",
        ]
        if excerpt:
            points.append(f"Visible content excerpt: {excerpt}")
        output = {
            "schema_version": "1.0",
            "file_description": f"{filename} prepared as an LLM input digest.",
            "summary_points": points[:5],
            "llm_digest": "\n".join(points),
            "structured_digest": {
                "document_type": content_type,
                "facts": points,
                "entities": [],
                "dates": [],
                "numbers": [],
                "action_items": [],
                "structure_notes": [],
            },
            "coverage": {
                "source_kind": str(input_payload.get("source_kind") or "unknown"),
                "read_scope": str(input_payload.get("read_scope") or "unknown"),
                "truncated": bool(input_payload.get("truncated")),
                "limitations": input_payload.get("limitations") or [],
            },
            "token_estimate": max(1, len("\n".join(points)) // 4),
            "reasoning_summary": "Mock digest generated from file metadata and extracted text.",
            "warnings": [],
        }
        return LlmProviderResponse(
            output=output,
            output_preview=str(output["file_description"]),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class MockCaseCurrentSituationProvider:
    provider_name = "mock"
    model_name = "deterministic-case-current-situation-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_CASE_CURRENT_SITUATION_SUMMARY:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        case_payload = input_payload.get("case")
        case_data = case_payload if isinstance(case_payload, dict) else {}
        mail_threads = input_payload.get("mail_threads")
        mail_count = len(mail_threads) if isinstance(mail_threads, list) else 0
        files = input_payload.get("files")
        file_count = len(files) if isinstance(files, list) else 0
        calendar_status = input_payload.get("calendar_status")
        calendar_connected = (
            isinstance(calendar_status, dict) and calendar_status.get("connected") is True
        )
        task_status = input_payload.get("task_status")
        task_connected = (
            isinstance(task_status, dict) and task_status.get("connected") is True
        )
        title = str(case_data.get("name") or "Case")
        summary = (
            f"{title} は、関連メール {mail_count} 件と関連ファイル {file_count} 件をもとに状況確認中です。"
            if mail_count > 0 or file_count > 0
            else f"{title} は、概要をもとに状況確認中です。"
        )
        key_points = [
            f"関連メールThread: {mail_count}件",
            f"関連ファイルDigest: {file_count}件",
            "Task状況: 接続済み" if task_connected else "Task状況: 未接続",
            "Calendar状況: 接続済み" if calendar_connected else "Calendar状況: 未接続",
        ]
        if str(case_data.get("closed_when_text") or "").strip():
            key_points.append(f"終了条件: {case_data.get('closed_when_text')}")
        output = {
            "schema_version": "1.0",
            "summary": summary,
            "key_points": key_points[:5],
            "risks": [],
            "next_focus": "関連メールとOverviewを確認する。",
            "reasoning_summary": "Mock case current situation generated from metadata.",
            "warnings": [],
        }
        return LlmProviderResponse(
            output=output,
            output_preview=summary,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class MockTaskPrefillProvider:
    provider_name = "mock"
    model_name = "deterministic-task-prefill-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_TASK_PREFILL_GENERATION:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        prompt = compact_text(str(input_payload.get("prompt") or ""), 140)
        case_payload = input_payload.get("case")
        case_data = case_payload if isinstance(case_payload, dict) else {}
        case_name = compact_text(str(case_data.get("name") or "Case"), 80)
        title = prompt or f"{case_name} task"
        output = {
            "schema_version": "1.0",
            "summary": f"Task prefill for {title}",
            "title": title[:120],
            "description": prompt or f"Task generated for {case_name}.",
            "done_when_text": "The requested work is completed and confirmed.",
            "priority": "middle",
            "due_at": None,
            "estimate_minutes": None,
            "reasoning_summary": "Mock task prefill generated from prompt and Case context.",
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


class MockCalendarEventPrefillProvider:
    provider_name = "mock"
    model_name = "deterministic-calendar-event-prefill-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        prompt = compact_text(str(input_payload.get("prompt") or ""), 120)
        today = date.today()
        start_at = f"{today.isoformat()}T10:00"
        end_at = f"{today.isoformat()}T11:00"
        title = prompt or "メール由来の予定"
        output = {
            "schema_version": "1.0",
            "summary": title[:120],
            "description": prompt or "メール本文をもとに作成した予定候補です。",
            "location": None,
            "start_at": start_at,
            "end_at": end_at,
            "time_zone": "Asia/Tokyo",
            "reasoning_summary": "Mock calendar event prefill generated from mail context.",
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


class MockCasePrefillProvider:
    provider_name = "mock"
    model_name = "deterministic-case-prefill-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_CASE_PREFILL_GENERATION:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        prompt = compact_text(str(input_payload.get("prompt") or ""), 180)
        title = prompt or "New Case"
        output = {
            "schema_version": "1.0",
            "summary": f"Case prefill for {title}",
            "name": title[:120],
            "description": prompt or "Case generated from the user prompt.",
            "open_when_date": None,
            "closed_when_text": "This Case can be closed when the intended outcome is complete and confirmed.",
            "tags": [],
            "reasoning_summary": "Mock case prefill generated from prompt.",
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


class MockContactAiMemoUpdateProvider:
    provider_name = "mock"
    model_name = "deterministic-contact-ai-memo-update-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type != FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        current_memo = normalized_text(str(input_payload.get("current_ai_memo") or ""))
        messages = input_payload.get("messages")
        if isinstance(messages, list) and messages:
            recent_items: list[str] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                subject = compact_text(str(message.get("subject") or "No subject"), 100)
                received_at = str(message.get("received_at") or "")
                snippet = compact_text(
                    str(message.get("body_text") or message.get("snippet") or ""),
                    180,
                )
                item = f"({received_at}) {subject}"
                if snippet:
                    item = f"{item} / {snippet}"
                recent_items.append(item)
            recent_line = "Recent activity batch: " + " | ".join(recent_items)
        else:
            subject = compact_text(str(input_payload.get("subject") or "No subject"), 100)
            received_at = str(input_payload.get("received_at") or "")
            snippet = compact_text(
                str(input_payload.get("body_text") or input_payload.get("snippet") or ""),
                180,
            )
            recent_line = f"Recent activity ({received_at}): {subject}"
            if snippet:
                recent_line = f"{recent_line} / {snippet}"
        memo = recent_line if current_memo == "" else f"{current_memo}\n{recent_line}"
        output = {
            "schema_version": "1.0",
            "ai_memo": memo,
            "reasoning_summary": "Mock contact AI memo update focused on recent activity.",
        }
        return LlmProviderResponse(
            output=output,
            output_preview=memo[:200],
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )


class MockMailDraftGenerationProvider:
    provider_name = "mock"
    model_name = "deterministic-mail-draft-generation-v1"

    def complete_json(
        self,
        *,
        function_type: str,
        input_payload: dict[str, object],
    ) -> LlmProviderResponse:
        if function_type not in {
            FUNCTION_TYPE_REPLY_DRAFT_GENERATION,
            FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
        }:
            raise ValueError(f"Unsupported mock function type: {function_type}")

        instruction = compact_text(str(input_payload.get("instruction") or ""), 120)
        current_subject = compact_text(str(input_payload.get("current_subject") or ""), 120)
        subject = current_subject or (
            "Re: Generated reply"
            if function_type == FUNCTION_TYPE_REPLY_DRAFT_GENERATION
            else "Generated mail"
        )
        body_lines = [
            "LLM draft generated by mock provider.",
            f"Instruction: {instruction or '(none)'}",
        ]
        current_body = normalized_text(str(input_payload.get("current_body") or ""))
        if current_body:
            body_lines.append(f"Current body context: {compact_text(current_body, 240)}")
        output = {
            "schema_version": "1.0",
            "subject": subject,
            "body": "\n".join(body_lines),
            "reasoning_summary": "Mock draft generated from compose context.",
            "warnings": [],
        }
        return LlmProviderResponse(
            output=output,
            output_preview=str(output["body"])[:200],
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


class OpenAIContactAiMemoUpdateProvider:
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
        if function_type != FUNCTION_TYPE_CONTACT_AI_MEMO_UPDATE:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": contact_ai_memo_update_instructions(),
            "input": contact_ai_memo_update_input_text(input_payload),
            "max_output_tokens": 1200,
            "text": {
                "format": contact_ai_memo_update_response_format(),
            },
        }
        return openai_contact_ai_memo_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAIFileSummaryProvider:
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
        if function_type != FUNCTION_TYPE_FILE_SUMMARY:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": file_summary_instructions(),
            "input": file_summary_input_text(input_payload),
            "max_output_tokens": 3000,
            "text": {
                "format": file_summary_response_format(),
            },
        }
        return openai_file_summary_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAICaseCurrentSituationProvider:
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
        if function_type != FUNCTION_TYPE_CASE_CURRENT_SITUATION_SUMMARY:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": case_current_situation_instructions(),
            "input": case_current_situation_input_text(input_payload),
            "max_output_tokens": 1400,
            "text": {"format": case_current_situation_response_format()},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAITaskPrefillProvider:
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
        if function_type != FUNCTION_TYPE_TASK_PREFILL_GENERATION:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": task_prefill_instructions(),
            "input": task_prefill_input_text(input_payload),
            "max_output_tokens": 900,
            "text": {"format": task_prefill_response_format()},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAICalendarEventPrefillProvider:
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
        if function_type != FUNCTION_TYPE_CALENDAR_EVENT_PREFILL_GENERATION:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": calendar_event_prefill_instructions(),
            "input": calendar_event_prefill_input_text(input_payload),
            "max_output_tokens": 800,
            "text": {"format": calendar_event_prefill_response_format()},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAICasePrefillProvider:
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
        if function_type != FUNCTION_TYPE_CASE_PREFILL_GENERATION:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": case_prefill_instructions(),
            "input": case_prefill_input_text(input_payload),
            "max_output_tokens": 900,
            "text": {"format": case_prefill_response_format()},
        }
        return openai_structured_response(
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )


class OpenAIMailDraftGenerationProvider:
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
        if function_type not in {
            FUNCTION_TYPE_REPLY_DRAFT_GENERATION,
            FUNCTION_TYPE_NEW_MAIL_DRAFT_GENERATION,
        }:
            raise ValueError(f"Unsupported OpenAI function type: {function_type}")

        payload = {
            "model": self.model_name,
            "instructions": mail_draft_generation_instructions(function_type),
            "input": mail_draft_generation_input_text(input_payload),
            "max_output_tokens": 2500,
            "text": {
                "format": mail_draft_generation_response_format(function_type),
            },
        }
        return openai_mail_draft_generation_response(
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
    parsed_response = parse_openai_json_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output = parsed_response.output
    if not isinstance(output, dict):
        raise OpenAIProviderError("OpenAI response JSON was not an object.")
    summary = str(output.get("summary") or "").strip()
    if summary == "":
        raise OpenAIProviderError("OpenAI summary response did not include summary.")
    output["summary"] = summary
    return LlmProviderResponse(
        output=output,
        output_preview=summary,
        prompt_tokens=parsed_response.prompt_tokens,
        completion_tokens=parsed_response.completion_tokens,
        total_tokens=parsed_response.total_tokens,
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


def contact_ai_memo_update_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "contact_ai_memo_update",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "ai_memo": {"type": "string"},
                "reasoning_summary": {"type": "string"},
            },
            "required": ["schema_version", "ai_memo", "reasoning_summary"],
        },
    }


def case_current_situation_response_format() -> dict[str, object]:
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "json_schema",
        "name": "case_current_situation_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "summary": {"type": "string"},
                "key_points": string_array,
                "risks": string_array,
                "next_focus": {"type": "string"},
                "reasoning_summary": {"type": "string"},
                "warnings": string_array,
            },
            "required": [
                "schema_version",
                "summary",
                "key_points",
                "risks",
                "next_focus",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def task_prefill_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "task_prefill_generation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "summary": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "done_when_text": {"type": "string"},
                "priority": {"type": "string", "enum": ["high", "middle", "low"]},
                "due_at": {"type": ["string", "null"]},
                "estimate_minutes": {"type": ["integer", "null"]},
                "reasoning_summary": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "schema_version",
                "summary",
                "title",
                "description",
                "done_when_text",
                "priority",
                "due_at",
                "estimate_minutes",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def calendar_event_prefill_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "calendar_event_prefill_generation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": ["string", "null"]},
                "start_at": {"type": ["string", "null"]},
                "end_at": {"type": ["string", "null"]},
                "time_zone": {"type": "string"},
                "reasoning_summary": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "schema_version",
                "summary",
                "description",
                "location",
                "start_at",
                "end_at",
                "time_zone",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def case_prefill_response_format() -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": "case_prefill_generation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "summary": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "open_when_date": {"type": ["string", "null"]},
                "closed_when_text": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "reasoning_summary": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "schema_version",
                "summary",
                "name",
                "description",
                "open_when_date",
                "closed_when_text",
                "tags",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def file_summary_response_format() -> dict[str, object]:
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "json_schema",
        "name": "file_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "file_description": {"type": "string"},
                "summary_points": string_array,
                "llm_digest": {"type": "string"},
                "structured_digest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "document_type": {"type": "string"},
                        "facts": string_array,
                        "entities": string_array,
                        "dates": string_array,
                        "numbers": string_array,
                        "action_items": string_array,
                        "structure_notes": string_array,
                    },
                    "required": [
                        "document_type",
                        "facts",
                        "entities",
                        "dates",
                        "numbers",
                        "action_items",
                        "structure_notes",
                    ],
                },
                "coverage": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_kind": {"type": "string"},
                        "read_scope": {"type": "string"},
                        "truncated": {"type": "boolean"},
                        "limitations": string_array,
                    },
                    "required": [
                        "source_kind",
                        "read_scope",
                        "truncated",
                        "limitations",
                    ],
                },
                "token_estimate": {"type": "integer"},
                "reasoning_summary": {"type": "string"},
                "warnings": string_array,
            },
            "required": [
                "schema_version",
                "file_description",
                "summary_points",
                "llm_digest",
                "structured_digest",
                "coverage",
                "token_estimate",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def openai_file_summary_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> LlmProviderResponse:
    parsed_response = parse_openai_json_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output = parsed_response.output
    if not isinstance(output, dict):
        raise OpenAIProviderError("OpenAI response JSON was not an object.")
    file_description = str(output.get("file_description") or "").strip()
    llm_digest = str(output.get("llm_digest") or "").strip()
    if file_description == "":
        raise OpenAIProviderError(
            "OpenAI file summary response did not include file_description."
        )
    if llm_digest == "":
        raise OpenAIProviderError("OpenAI file summary response did not include llm_digest.")
    output["file_description"] = file_description
    output["llm_digest"] = llm_digest
    return LlmProviderResponse(
        output=output,
        output_preview=file_description,
        prompt_tokens=parsed_response.prompt_tokens,
        completion_tokens=parsed_response.completion_tokens,
        total_tokens=parsed_response.total_tokens,
        estimated_cost=None,
    )


def openai_contact_ai_memo_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> LlmProviderResponse:
    parsed_response = parse_openai_json_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output = parsed_response.output
    if not isinstance(output, dict):
        raise OpenAIProviderError("OpenAI response JSON was not an object.")
    ai_memo = str(output.get("ai_memo") or "").strip()
    if ai_memo == "":
        raise OpenAIProviderError("OpenAI contact memo response did not include ai_memo.")
    output["ai_memo"] = ai_memo
    return LlmProviderResponse(
        output=output,
        output_preview=ai_memo[:200],
        prompt_tokens=parsed_response.prompt_tokens,
        completion_tokens=parsed_response.completion_tokens,
        total_tokens=parsed_response.total_tokens,
        estimated_cost=None,
    )


def mail_draft_generation_response_format(function_type: str) -> dict[str, object]:
    return {
        "type": "json_schema",
        "name": function_type,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema_version": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "reasoning_summary": {"type": "string"},
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "schema_version",
                "subject",
                "body",
                "reasoning_summary",
                "warnings",
            ],
        },
    }


def openai_mail_draft_generation_response(
    payload: dict[str, object],
    *,
    api_key: str,
    timeout_seconds: float,
) -> LlmProviderResponse:
    parsed_response = parse_openai_json_response(
        payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    output = parsed_response.output
    if not isinstance(output, dict):
        raise OpenAIProviderError("OpenAI response JSON was not an object.")
    subject = str(output.get("subject") or "").strip()
    body = str(output.get("body") or "").strip()
    if subject == "":
        raise OpenAIProviderError("OpenAI draft response did not include subject.")
    if body == "":
        raise OpenAIProviderError("OpenAI draft response did not include body.")
    output["subject"] = subject
    output["body"] = body
    return LlmProviderResponse(
        output=output,
        output_preview=body[:200],
        prompt_tokens=parsed_response.prompt_tokens,
        completion_tokens=parsed_response.completion_tokens,
        total_tokens=parsed_response.total_tokens,
        estimated_cost=None,
    )


def mail_summary_instructions() -> str:
    return (
        "You summarize one email for a Japanese personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Write summary, next_action, and key_points in Japanese. "
        "Full-body translation is disabled; always set translation to null. "
        "Keep the summary concise but preserve deadlines, requests, and decisions. "
        "Summarize only the current/new message body. Treat quoted replies, "
        "forwarded history, previous messages, signatures, and mailing-list footers "
        "as context only, not as facts to summarize. If the current message is short "
        "or only acknowledges a previous message, summarize that short current "
        "message and do not fill the summary from quoted history. Use quoted reply "
        "context only to disambiguate references in the current message. "
        "When the email presents a website URL or homepage address that is useful "
        "for the recipient's next action or context, include that URL in the summary "
        "as much as possible without inventing or rewriting it. "
        "Do not include sensitive full body text unless it is necessary as a short fact."
    )


def contact_ai_memo_update_instructions() -> str:
    return (
        "You update an AI-owned memo for one contact in a Japanese personal "
        "work-support app. Return only JSON matching the schema. "
        "Use the existing AI memo and the newly received email or email batch. "
        "Focus on current, time-sensitive, and recent activity: what the person "
        "is working on, announcing, coordinating, requesting, scheduling, or "
        "recently involved in. Do not turn the memo into a static profile. "
        "Mention organization/role only when the new email changes or clarifies "
        "current context. Keep the memo concise, factual, and useful for future "
        "mail triage. Write ai_memo in Japanese."
    )


def mail_thread_summary_instructions() -> str:
    return (
        "You summarize an email thread for a Japanese personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Write summary, next_action, and key_points in Japanese. "
        "Full-body translation is disabled; always set translation to null. "
        "Write the summary as bullet points. "
        "Summarize the whole thread chronologically, including current status, "
        "open questions, deadlines, requests, and decisions. "
        "If summary_scope is incremental_update, update current_thread_summary "
        "using only the newly provided messages and return the updated full "
        "thread summary. "
        "If summary_scope is partial, summarize only that chunk. "
        "If summary_scope is incremental_partial, summarize only that chunk of "
        "new messages in relation to current_thread_summary. "
        "If summary_scope is final_from_partial_summaries, integrate the provided "
        "partial summaries into one coherent thread summary. "
        "Do not translate the full thread body."
    )


def case_current_situation_instructions() -> str:
    return (
        "You write a current situation note for one Case in a Japanese personal "
        "work-support app for a university faculty member. Return only JSON matching "
        "the provided schema. Write summary, key_points, risks, and next_focus in "
        "Japanese. The goal is to help the user quickly remember what this Case is "
        "about, what has happened recently, what is unresolved, and what to inspect "
        "next. Use the Case overview as the user's explicit intent. Use related mail "
        "thread summaries as evidence. Use calendar_status items when connected to "
        "identify upcoming meetings, deadlines, or date-bound context; if not "
        "connected, do not invent calendar events. Use file summaries/digests as "
        "supporting evidence for the contents of related documents, and mention when "
        "a file summary is not current only if that affects the situation. Use "
        "task_status only when connected; if it is not connected, explicitly avoid "
        "inventing task completion state. Do not invent facts, deadlines, decisions, "
        "or stakeholder roles that are not in the input. Keep summary to one short "
        "paragraph. key_points should have at most five items. risks should include "
        "only concrete uncertainties or blockers."
    )


def task_prefill_instructions() -> str:
    return (
        "You help a university faculty user draft a task record in a work-support app. "
        "Use the user's prompt and Case context to propose concise, directly editable "
        "Task fields. Do not invent external facts. Keep title short. Description should "
        "state what the task is about. Done when should describe the completion condition. "
        "Always write all user-facing generated Task text in Japanese, regardless of "
        "the language of the source mail, prompt, or Case context. This includes title, "
        "description, done_when_text, summary, reasoning_summary, and warnings. "
        "Keep JSON property names and enum values in the required schema language. "
        "Use priority high/middle/low. due_at must be YYYY-MM-DD when a clear due date is "
        "present; otherwise null. estimate_minutes must be a practical integer or null. "
        "Return only JSON matching the schema."
    )


def calendar_event_prefill_instructions() -> str:
    return (
        "You help a university faculty user draft a Google Calendar event from one "
        "selected email in a work-support app. Return only JSON matching the schema. "
        "Use the current/new message body as the primary source. Treat quoted reply "
        "history only as context; do not create an event solely from quoted history. "
        "Extract only a schedule that is clearly mentioned or strongly implied by the "
        "selected mail. Do not invent participants, locations, URLs, or dates. "
        "summary should be concise and useful on a weekly calendar. description should "
        "summarize why this event exists and preserve relevant URLs or meeting details. "
        "location should contain a room, venue, Zoom/Teams URL, or null. start_at and "
        "end_at should be local ISO-like values such as YYYY-MM-DDTHH:MM when clear; "
        "otherwise null. If only a start time is clear, choose a practical one-hour end "
        "and add a warning. Use Asia/Tokyo unless the mail clearly specifies another "
        "time zone. Write summary, description, reasoning_summary, and warnings in "
        "Japanese while preserving proper nouns, URLs, titles, and identifiers."
    )


def case_prefill_instructions() -> str:
    return (
        "You help a university faculty user draft a Case record in a work-support app. "
        "A Case is a work container that can later collect mails, tasks, calendar events, "
        "files, stakeholders, and external tools. Use the user's prompt and already typed "
        "fields to propose concise, directly editable Case fields. Do not invent external "
        "facts. Keep the name short. Description should explain the Case's purpose. "
        "Closed when should describe the condition for permanently closing the Case. "
        "open_when_date must be YYYY-MM-DD only when the user clearly gives a start date; "
        "otherwise null. Tags should be short lower-case labels when useful. Return only "
        "JSON matching the schema."
    )


def file_summary_instructions() -> str:
    return (
        "You prepare an LLM input digest for one stored file in a Japanese "
        "personal work-support app. Return only JSON matching the provided schema. "
        "The primary goal is not a pleasant explanation; it is an information-dense "
        "intermediate representation that lets later LLM calls understand the file "
        "without reading the full original. Minimize tokens while preserving coverage. "
        "Do not infer unsupported facts. Preserve names, dates, numbers, conditions, "
        "exceptions, deadlines, requirements, decisions, URLs, table columns, and file "
        "structure when present. Write file_description and summary_points in Japanese. "
        "file_description must be one short sentence. summary_points must contain at "
        "most five concise bullets. Write llm_digest in Japanese unless source content "
        "is mainly English; it may retain original technical terms. Note unread, "
        "unsupported, or truncated content in coverage.limitations. "
        "When generation_mode is incremental_from_digest, create the target file digest "
        "by updating the previous digest with every supplied diff in order. Treat removed "
        "lines as no longer present and added lines as newly present. Do not carry forward "
        "facts contradicted by the diffs."
    )


def mail_draft_generation_instructions(function_type: str) -> str:
    base = (
        "You draft an email for a Japanese personal work-support app. "
        "Return only JSON matching the provided schema. "
        "Generate a practical subject and body from the provided context. "
        "Prioritize the user's explicit instruction, then the standard prompt, "
        "then reply context, contact memos, case summaries, and the current draft. "
        "Use the current draft body as source material when useful, but improve it "
        "rather than merely echoing it. Do not invent facts, promises, attachments, "
        "or schedules that are not supported by the context. "
        "For reply emails, use the provided reply_language and language_policy. "
        "Reply in the same language as the source email unless the user explicitly "
        "requests another language. For new emails, write in the language implied "
        "by the instruction and recipient context; when unclear, write polite "
        "Japanese business email. "
        "Do not include a signature unless the user explicitly asks for one."
    )
    if function_type == FUNCTION_TYPE_REPLY_DRAFT_GENERATION:
        return (
            base
            + " This is a reply. Respect the auto body/reply quote context, answer "
            "the preceding email directly, and keep the generated body suitable as "
            "the editable reply body before any app-managed signature is appended."
        )
    return (
        base
        + " This is a new outgoing email. Create a self-contained message suitable "
        "for the specified recipients."
    )


def file_summary_input_text(input_payload: dict[str, object]) -> str:
    generation_mode = str(input_payload.get("generation_mode") or "full_source")
    if generation_mode == "incremental_from_digest":
        source_block = (
            "Incremental source JSON:\n"
            f"{truncated_text(json_text(input_payload.get('incremental_source') or {}), 60000)}"
        )
    else:
        source_block = (
            "Extracted source text or structural representation:\n"
            f"{truncated_text(input_payload.get('source_text'), 60000)}"
        )
    return "\n".join(
        [
            f"Generation mode: {generation_mode}",
            f"Storage object ID: {input_payload.get('storage_object_id') or ''}",
            f"Storage object version ID: {input_payload.get('storage_object_version_id') or ''}",
            f"Filename: {input_payload.get('filename') or ''}",
            f"Content type: {input_payload.get('content_type') or ''}",
            f"Byte size: {input_payload.get('byte_size') or 0}",
            f"SHA-256: {input_payload.get('sha256_hex') or ''}",
            f"Source kind: {input_payload.get('source_kind') or ''}",
            f"Read scope: {input_payload.get('read_scope') or ''}",
            f"Truncated: {input_payload.get('truncated') or False}",
            f"Limitations JSON: {json_text(input_payload.get('limitations') or [])}",
            source_block,
        ]
    )


def mail_draft_generation_input_text(input_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"Instruction: {truncated_text(input_payload.get('instruction'), 4000)}",
            (
                "Standard prompt: "
                f"{truncated_text(input_payload.get('standard_prompt'), 4000)}"
            ),
            (
                "Language generation prompt: "
                f"{input_payload.get('language_generation_prompt') or ''}"
            ),
            f"To: {input_payload.get('to_addresses') or []}",
            f"Cc: {input_payload.get('cc_addresses') or []}",
            f"Bcc: {input_payload.get('bcc_addresses') or []}",
            f"Current subject: {input_payload.get('current_subject') or ''}",
            f"Reply language: {input_payload.get('reply_language') or 'Unspecified'}",
            f"Language policy: {input_payload.get('language_policy') or ''}",
            (
                "Language retry instruction: "
                f"{input_payload.get('language_retry_instruction') or ''}"
            ),
            (
                "Reply auto body: "
                f"{truncated_text(input_payload.get('auto_body_text'), 12000)}"
            ),
            (
                "Recipient contact context JSON, grouped by recipient role "
                "(to/cc) with contact names, kind, status, email, and user memos: "
                f"{truncated_text(json_text(input_payload.get('recipient_contact_context')), 8000)}"
            ),
            (
                "Related case summaries JSON: "
                f"{truncated_text(json_text(input_payload.get('related_case_summaries')), 8000)}"
            ),
            f"Current body: {truncated_text(input_payload.get('current_body'), 16000)}",
        ]
    )


def contact_ai_memo_update_input_text(input_payload: dict[str, object]) -> str:
    lines = [
        f"Contact ID: {input_payload.get('contact_id') or ''}",
        f"Contact display name: {input_payload.get('contact_display_name') or ''}",
        f"Current AI memo: {truncated_text(input_payload.get('current_ai_memo'), 4000)}",
    ]
    messages = input_payload.get("messages")
    if isinstance(messages, list) and messages:
        lines.append(f"New message count: {len(messages)}")
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                continue
            lines.extend(
                [
                    f"\nMessage {index}",
                    f"Message ID: {message.get('message_id') or ''}",
                    f"Gmail message ID: {message.get('gmail_message_id') or ''}",
                    f"Received at: {message.get('received_at') or ''}",
                    f"Subject: {message.get('subject') or ''}",
                    f"From: {message.get('from_address') or ''}",
                    f"Snippet: {truncated_text(message.get('snippet'), 1000)}",
                    f"Body text: {truncated_text(message.get('body_text'), 8000)}",
                ]
            )
        return "\n".join(lines)
    lines.extend(
        [
            f"Message ID: {input_payload.get('message_id') or ''}",
            f"Gmail message ID: {input_payload.get('gmail_message_id') or ''}",
            f"Received at: {input_payload.get('received_at') or ''}",
            f"Subject: {input_payload.get('subject') or ''}",
            f"From: {input_payload.get('from_address') or ''}",
            f"Snippet: {truncated_text(input_payload.get('snippet'), 1000)}",
            f"Body text: {truncated_text(input_payload.get('body_text'), 12000)}",
        ]
    )
    return "\n".join(lines)


def task_prefill_input_text(input_payload: dict[str, object]) -> str:
    case_payload = input_payload.get("case")
    case_data = case_payload if isinstance(case_payload, dict) else {}
    current_payload = input_payload.get("current_fields")
    current_fields = current_payload if isinstance(current_payload, dict) else {}
    return "\n".join(
        [
            f"User prompt: {input_payload.get('prompt') or ''}",
            "",
            "Case context:",
            f"- Name: {case_data.get('name') or ''}",
            f"- Overview: {case_data.get('description') or ''}",
            f"- Open when: {case_data.get('open_when_date') or ''}",
            f"- Closed when: {case_data.get('closed_when_text') or ''}",
            "",
            "Current Task fields already typed by user:",
            json.dumps(current_fields, ensure_ascii=False, indent=2),
            "",
            "Fill sensible Task fields. The app will only apply fields that are blank in the UI.",
        ]
    )


def calendar_event_prefill_input_text(input_payload: dict[str, object]) -> str:
    case_payload = input_payload.get("case")
    case_data = case_payload if isinstance(case_payload, dict) else {}
    return "\n".join(
        [
            f"User prompt: {input_payload.get('prompt') or ''}",
            f"Current date: {input_payload.get('current_date') or ''}",
            "",
            "Related Case context:",
            f"- Name: {case_data.get('name') or ''}",
            f"- Overview: {case_data.get('description') or ''}",
            f"- Open when: {case_data.get('open_when_date') or ''}",
            f"- Closed when: {case_data.get('closed_when_text') or ''}",
            "",
            "Selected mail JSON:",
            truncated_text(json_text(input_payload.get("mail") or {}), 30000),
            "",
            "Stored mail/thread summary JSON:",
            truncated_text(json_text(input_payload.get("summaries") or {}), 10000),
        ]
    )


def case_prefill_input_text(input_payload: dict[str, object]) -> str:
    current_payload = input_payload.get("current_fields")
    current_fields = current_payload if isinstance(current_payload, dict) else {}
    return "\n".join(
        [
            f"User prompt: {input_payload.get('prompt') or ''}",
            "",
            "Current Case fields already typed by user:",
            json.dumps(current_fields, ensure_ascii=False, indent=2),
            "",
            "Fill sensible Case fields. The app will only apply fields that are blank in the UI.",
        ]
    )


def mail_summary_input_text(input_payload: dict[str, object]) -> str:
    current_body_text = input_payload.get("current_body_text")
    if current_body_text is None:
        current_body_text = input_payload.get("body_text")
    quoted_reply_context = input_payload.get("quoted_reply_context")
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
            (
                "Current message body to summarize: "
                f"{truncated_text(current_body_text, 16000)}"
            ),
            (
                "Quoted reply / previous-message context. Do not summarize this "
                "section as current mail content: "
                f"{truncated_text(quoted_reply_context, 8000)}"
            ),
        ]
    )


def mail_thread_summary_input_text(input_payload: dict[str, object]) -> str:
    messages = input_payload.get("messages")
    current_thread_summary = input_payload.get("current_thread_summary")
    partial_summaries = input_payload.get("partial_summaries")
    lines = [
        f"Thread ID: {input_payload.get('thread_id') or ''}",
        f"Gmail thread ID: {input_payload.get('gmail_thread_id') or ''}",
        f"Subject: {input_payload.get('subject') or ''}",
        f"Summary scope: {input_payload.get('summary_scope') or 'full'}",
    ]
    if input_payload.get("chunk_index") is not None:
        lines.append(
            f"Chunk: {input_payload.get('chunk_index')} / {input_payload.get('chunk_count')}"
        )
    if isinstance(current_thread_summary, dict):
        lines.extend(
            [
                "\nCurrent thread summary:",
                f"Summary: {truncated_text(current_thread_summary.get('summary'), 6000)}",
                f"Next action: {truncated_text(current_thread_summary.get('next_action'), 1000)}",
                f"Key points JSON: {truncated_text(json_text(current_thread_summary.get('key_points') or []), 3000)}",
                f"Needs action: {current_thread_summary.get('needs_action')}",
            ]
        )
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
    if isinstance(partial_summaries, list):
        lines.append("\nPartial summaries to integrate:")
        for index, summary in enumerate(partial_summaries, start=1):
            if not isinstance(summary, dict):
                continue
            lines.extend(
                [
                    f"\nPartial summary {index}",
                    f"Chunk index: {summary.get('chunk_index') or ''}",
                    f"Summary: {truncated_text(summary.get('summary'), 4000)}",
                    f"Next action: {truncated_text(summary.get('next_action'), 1000)}",
                    f"Key points JSON: {truncated_text(json_text(summary.get('key_points') or []), 3000)}",
                    f"Needs action: {summary.get('needs_action')}",
                ]
            )
    return "\n".join(lines)


def case_current_situation_input_text(input_payload: dict[str, object]) -> str:
    return "\n".join(
        [
            (
                "Case current situation input JSON:\n"
                f"{truncated_text(json_text(input_payload), 50000)}"
            )
        ]
    )


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


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
