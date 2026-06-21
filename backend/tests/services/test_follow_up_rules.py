from caseclosed.db.models import GmailMessage
from caseclosed.services.follow_up_rules import first_matched_phrase


def message_with_body(body_text: str, subject: str = "Re: report") -> GmailMessage:
    return GmailMessage(subject=subject, body_text=body_text)


def test_follow_up_phrase_ignores_auto_body_quote() -> None:
    message = message_with_body(
        "承知しました。\n\n"
        "On 2026/06/20 10:00, sender@example.com wrote:\n"
        "> ご確認ください"
    )

    assert first_matched_phrase(message) is None


def test_follow_up_phrase_matches_manual_body_before_auto_body() -> None:
    message = message_with_body(
        "資料をご確認ください。\n\n"
        "On 2026/06/20 10:00, sender@example.com wrote:\n"
        "> 元の本文です"
    )

    assert first_matched_phrase(message) == "ご確認"
