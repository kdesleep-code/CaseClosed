from __future__ import annotations

import re


GENERATED_INLINE_IMAGE_MAX_BYTES = 32 * 1024
GENERATED_INLINE_IMAGE_FILENAME_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def is_probable_generated_inline_image(
    *,
    filename: str,
    mime_type: str | None,
    byte_size: int,
    content_disposition: str | None = None,
    content_id: str | None = None,
) -> bool:
    """Hide only the small, generated inline images previously treated as noise.

    Gmail may label a user-visible image attachment as inline when the sender
    inserts it into the message body. A meaningful filename or a larger image
    must therefore remain available as an attachment.
    """

    if not (mime_type or "").strip().lower().startswith("image/"):
        return False
    if byte_size > GENERATED_INLINE_IMAGE_MAX_BYTES:
        return False
    if GENERATED_INLINE_IMAGE_FILENAME_PATTERN.fullmatch(filename.strip()) is None:
        return False

    # Older rows do not retain MIME disposition metadata. Their UUID-only,
    # small-image shape is sufficient to preserve the legacy hiding behavior.
    if content_disposition is None and content_id is None:
        return True

    disposition = (content_disposition or "").strip().lower()
    if disposition == "attachment" or disposition.startswith("attachment;"):
        return False
    declared_inline = disposition == "inline" or disposition.startswith("inline;")
    return declared_inline or (content_id or "").strip() != ""
