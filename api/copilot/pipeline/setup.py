"""Builds what the pipeline needs from the settings: database, catalog, model, embeddings."""

from copilot.config import ConfigError, Settings
from copilot.db import connect
from copilot.db.kb import load_catalog_from_db
from copilot.embeddings import OpenAIEmbedder
from copilot.pipeline.llm import OpenAILLM
from copilot.pipeline.orchestrator import Deps


def connect_deps(settings: Settings) -> Deps:
    """Raises ConfigError when a setting is missing, and KBError when the
    database has not been indexed."""
    missing = [
        name
        for name, value in (
            ("STRONG_MODEL", settings.strong_model),
            ("CHEAP_MODEL", settings.cheap_model),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            f"{' and '.join(missing)} must be set to the exact OpenAI model ids. "
            "There are no defaults; take the ids from your account's model list."
        )
    llm = OpenAILLM.from_settings(settings)
    embedder = OpenAIEmbedder.from_settings(settings)
    conn = connect(settings)
    try:
        catalog = load_catalog_from_db(conn)
    except Exception:
        conn.close()
        raise
    return Deps(conn=conn, catalog=catalog, llm=llm, embedder=embedder, settings=settings)
