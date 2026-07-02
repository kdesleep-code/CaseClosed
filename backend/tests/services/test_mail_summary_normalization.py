from __future__ import annotations

from caseclosed.services import mail_summary
from caseclosed.services import mail_thread_summary
from caseclosed.services.llm_provider import mail_summary_input_text
from caseclosed.services.llm_provider import mail_summary_instructions


def test_mail_summary_string_or_none_treats_literal_null_as_none() -> None:
    assert mail_summary.string_or_none("null") is None
    assert mail_summary.string_or_none(" None ") is None
    assert mail_summary.string_or_none("actual translation") == "actual translation"


def test_mail_thread_summary_string_or_none_treats_literal_null_as_none() -> None:
    assert mail_thread_summary.string_or_none("null") is None
    assert mail_thread_summary.string_or_none(" None ") is None
    assert mail_thread_summary.string_or_none("actual translation") == "actual translation"


def test_split_quoted_reply_sections_keeps_quote_as_context() -> None:
    body_text = "\n".join(
        [
            "Current request: please review the attached draft.",
            "",
            "On May 31, sender@example.com wrote:",
            "> Old request: please submit the report today.",
        ]
    )

    current_body_text, quoted_context = mail_thread_summary.split_quoted_reply_sections(
        body_text
    )

    assert "Current request" in current_body_text
    assert "Old request" not in current_body_text
    assert "sender@example.com wrote" in quoted_context
    assert "Old request" in quoted_context


def test_mail_summary_prompt_marks_quoted_reply_as_context_only() -> None:
    prompt_text = mail_summary_input_text(
        {
            "message_id": "mail_1",
            "gmail_message_id": "gmail_1",
            "thread_id": "thread_1",
            "subject": "Review",
            "current_body_text": "Please review the attached draft.",
            "quoted_reply_context": "On May 31, sender@example.com wrote: Old request.",
        }
    )

    assert "Current message body to summarize" in prompt_text
    assert "Please review the attached draft." in prompt_text
    assert "Quoted reply / previous-message context" in prompt_text
    assert "Do not summarize this section as current mail content" in prompt_text

    instructions = mail_summary_instructions()
    assert "Summarize only the current/new message body" in instructions
    assert "quoted replies" in instructions
    assert "reference/supporting material" in instructions
