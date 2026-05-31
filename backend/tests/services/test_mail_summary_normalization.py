from __future__ import annotations

from caseclosed.services import mail_summary
from caseclosed.services import mail_thread_summary


def test_mail_summary_string_or_none_treats_literal_null_as_none() -> None:
    assert mail_summary.string_or_none("null") is None
    assert mail_summary.string_or_none(" None ") is None
    assert mail_summary.string_or_none("actual translation") == "actual translation"


def test_mail_thread_summary_string_or_none_treats_literal_null_as_none() -> None:
    assert mail_thread_summary.string_or_none("null") is None
    assert mail_thread_summary.string_or_none(" None ") is None
    assert mail_thread_summary.string_or_none("actual translation") == "actual translation"
