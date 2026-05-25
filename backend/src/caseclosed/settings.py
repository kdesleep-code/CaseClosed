from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///./data/caseclosed.sqlite3"
DEFAULT_LLM_MODEL_PROFILES_DIR = (
    Path(__file__).resolve().parents[2] / "llm_model_profiles"
)


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


def get_openai_api_key() -> str | None:
    return os.environ.get("CASECLOSED_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")


def get_llm_model_profiles_dir() -> Path:
    configured_path = os.environ.get("CASECLOSED_LLM_MODEL_PROFILES_DIR")
    if configured_path is not None and configured_path.strip() != "":
        return Path(configured_path)

    return DEFAULT_LLM_MODEL_PROFILES_DIR


def get_llm_profile_id(function_type: str) -> str | None:
    env_key = f"CASECLOSED_LLM_PROFILE_{function_type.upper()}"
    configured_profile = os.environ.get(env_key)
    if configured_profile is None or configured_profile.strip() == "":
        return None

    return configured_profile.strip()


def get_llm_profile_env_key(function_type: str) -> str:
    return f"CASECLOSED_LLM_PROFILE_{function_type.upper()}"


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    parsed = int(value)
    return max(minimum, min(maximum, parsed))


def env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    parsed = float(value)
    return max(minimum, min(maximum, parsed))


def is_background_worker_enabled() -> bool:
    return env_bool("CASECLOSED_BACKGROUND_WORKER_ENABLED", True)


def get_background_worker_count() -> int:
    return env_int("CASECLOSED_BACKGROUND_WORKER_COUNT", 2, minimum=1, maximum=8)


def get_background_worker_idle_sleep_seconds() -> float:
    return env_float(
        "CASECLOSED_BACKGROUND_WORKER_IDLE_SLEEP_SECONDS",
        1.0,
        minimum=0.1,
        maximum=30.0,
    )


def get_background_worker_stale_timeout_seconds() -> int:
    return env_int(
        "CASECLOSED_BACKGROUND_WORKER_STALE_TIMEOUT_SECONDS",
        90,
        minimum=30,
        maximum=86400,
    )


def get_background_worker_stale_check_seconds() -> int:
    return env_int(
        "CASECLOSED_BACKGROUND_WORKER_STALE_CHECK_SECONDS",
        30,
        minimum=5,
        maximum=3600,
    )
