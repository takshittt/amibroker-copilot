"""Settings read from the environment. Limits and model names live here, not in code."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Must match the vector(...) size in api/migrations/0001_initial.sql.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536


class ConfigError(Exception):
    """A setting is missing or cannot be understood."""


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    # Off for a pooler that cannot hold prepared statements (Supabase transaction mode).
    db_prepared_statements: bool = True
    openai_api_key: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ConfigError(f"{name} must be true or false, not {env[name]!r}")


def _whole_number(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < 1:
        raise ConfigError(f"{name} must be a whole number, 1 or more, not {env[name]!r}")
    return int(raw)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        database_url=env.get("DATABASE_URL", "").strip() or None,
        db_prepared_statements=_flag(env, "DB_PREPARED_STATEMENTS", True),
        openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
        embedding_model=env.get("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions=_whole_number(
            env, "EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS
        ),
    )
