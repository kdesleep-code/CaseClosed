from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "sqlite:///./data/caseclosed.sqlite3"


def get_database_url() -> str:
    return os.environ.get("CASECLOSED_DATABASE_URL", DEFAULT_DATABASE_URL)

