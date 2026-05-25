from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol


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


def display_name_from_email(email_address: str) -> str:
    local_part = email_address.split("@", maxsplit=1)[0]
    words = [word for word in re.split(r"[._+\-]+", local_part) if word]
    if not words:
        return email_address
    return " ".join(word.capitalize() for word in words)


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
