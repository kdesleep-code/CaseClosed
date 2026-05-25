from __future__ import annotations

from email.utils import getaddresses
from email.utils import parseaddr


def extract_email_address(value: str) -> str:
    parsed_name, parsed_address = parseaddr(value.strip())
    del parsed_name
    return (parsed_address or value).strip()


def normalize_email_address(value: str) -> str:
    return extract_email_address(value).lower()


def normalize_address_list(values: list[str] | None) -> list[str]:
    if values is None:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for address in getaddresses(values):
        email_address = address[1].strip()
        if email_address == "":
            continue
        key = normalize_email_address(email_address)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(email_address)
    return normalized
