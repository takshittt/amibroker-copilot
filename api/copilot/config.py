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

    # The exact OpenAI model ids. There are no defaults: they must be
    # confirmed against the account's model list and set in the environment.
    strong_model: str | None = None  # Generate, Review, apply fixes, Fix-from-error
    cheap_model: str | None = None  # Brief, Rerank

    # Pipeline limits.
    max_attempts: int = 3  # generate-and-check rounds for one request
    search_limit: int = 30  # rows taken from each search, for each query
    candidate_limit: int = 40  # merged candidates handed to the reranker
    rerank_keep: int = 10  # candidates kept after reranking
    max_request_chars: int = 4000  # longest request text accepted
    max_output_tokens: int = 4000  # cap on one model reply
    llm_timeout_seconds: int = 60

    # US dollars for a million tokens, to work out what a run cost.
    # Left unset, the cost of a run is reported as unknown.
    strong_price_in: float | None = None
    strong_price_out: float | None = None
    cheap_price_in: float | None = None
    cheap_price_out: float | None = None


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


def _price(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value < 0:
        raise ConfigError(f"{name} must be a number, 0 or more, not {env[name]!r}")
    return value


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
        strong_model=env.get("STRONG_MODEL", "").strip() or None,
        cheap_model=env.get("CHEAP_MODEL", "").strip() or None,
        max_attempts=_whole_number(env, "MAX_ATTEMPTS", Settings.max_attempts),
        search_limit=_whole_number(env, "SEARCH_LIMIT", Settings.search_limit),
        candidate_limit=_whole_number(env, "CANDIDATE_LIMIT", Settings.candidate_limit),
        rerank_keep=_whole_number(env, "RERANK_KEEP", Settings.rerank_keep),
        max_request_chars=_whole_number(env, "MAX_REQUEST_CHARS", Settings.max_request_chars),
        max_output_tokens=_whole_number(env, "MAX_OUTPUT_TOKENS", Settings.max_output_tokens),
        llm_timeout_seconds=_whole_number(env, "LLM_TIMEOUT_SECONDS", Settings.llm_timeout_seconds),
        strong_price_in=_price(env, "STRONG_PRICE_IN"),
        strong_price_out=_price(env, "STRONG_PRICE_OUT"),
        cheap_price_in=_price(env, "CHEAP_PRICE_IN"),
        cheap_price_out=_price(env, "CHEAP_PRICE_OUT"),
    )
