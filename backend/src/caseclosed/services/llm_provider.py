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
            for key in ("subject", "snippet", "body_text")
        ).lower()
        if any(token in text for token in ["urgent", "至急", "asap", "today"]):
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


def display_name_from_email(email_address: str) -> str:
    local_part = email_address.split("@", maxsplit=1)[0]
    words = [word for word in re.split(r"[._+\-]+", local_part) if word]
    if not words:
        return email_address
    return " ".join(word.capitalize() for word in words)


def suggested_tags_for_email(email_address: str) -> list[str]:
    local_part, _, domain = email_address.partition("@")
    low_value = f"{local_part} {domain}".lower()
    if any(token in low_value for token in ["no-reply", "noreply", "notification"]):
        return ["system-sender"]
    if any(token in low_value for token in ["list", "newsletter", "announce"]):
        return ["broadcast"]
    return ["unknown-domain"]
