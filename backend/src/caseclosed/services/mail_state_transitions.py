from __future__ import annotations

from caseclosed.db.models import MailUserState


def mark_skip_mail_done(
    user_state: MailUserState,
    *,
    effective_importance: str,
    now: str,
) -> bool:
    if effective_importance != "skip" or user_state.processed_status == "processed":
        return False
    user_state.processed_status = "processed"
    user_state.processed_at = now
    return True


def clear_done_after_leaving_skip(
    user_state: MailUserState,
    *,
    previous_importance: str,
    new_importance: str,
) -> bool:
    if (
        previous_importance != "skip"
        or new_importance == "skip"
        or user_state.processed_status != "processed"
    ):
        return False
    user_state.processed_status = "unprocessed"
    user_state.processed_at = None
    return True
