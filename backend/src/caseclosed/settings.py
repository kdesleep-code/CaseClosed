from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "sqlite:///./data/caseclosed.sqlite3"


def get_database_url() -> str:
    return os.environ.get("CASECLOSED_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_bootstrap_password() -> str | None:
    return os.environ.get("CASECLOSED_BOOTSTRAP_PASSWORD")


def is_secure_cookie_enabled() -> bool:
    return os.environ.get("CASECLOSED_ENV", "development") == "production"


def get_session_lifetime_override_minutes() -> int | None:
    configured_minutes = os.environ.get("CASECLOSED_SESSION_LIFETIME_MINUTES")
    if configured_minutes is not None:
        return int(configured_minutes)

    return None
