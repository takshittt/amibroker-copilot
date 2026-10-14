"""Starts the API from the environment.

    uvicorn copilot.api.main:create_from_env --factory --host 0.0.0.0 --port 8000

Refuses to start if a secret, a model id, the database, Redis or the
indexed knowledge base is missing.
"""

import redis
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from copilot.api.app import Services, create_app
from copilot.config import ConfigError, load_settings
from copilot.db.kb import load_catalog_from_db
from copilot.embeddings import OpenAIEmbedder
from copilot.pipeline.llm import OpenAILLM


def create_from_env():
    settings = load_settings()
    for name, value in (
        ("DATABASE_URL", settings.database_url),
        ("REDIS_URL", settings.redis_url),
        ("STRONG_MODEL", settings.strong_model),
        ("CHEAP_MODEL", settings.cheap_model),
    ):
        if not value:
            raise ConfigError(f"{name} must be set")
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.db_pool_size,
        kwargs={
            "row_factory": dict_row,
            "prepare_threshold": 5 if settings.db_prepared_statements else None,
        },
        open=True,
    )
    with pool.connection() as conn:
        catalog = load_catalog_from_db(conn)
    services = Services(
        settings=settings,
        pool=pool,
        redis=redis.Redis.from_url(settings.redis_url),
        catalog=catalog,
        llm=OpenAILLM.from_settings(settings),
        embedder=OpenAIEmbedder.from_settings(settings),
    )
    return create_app(services)
