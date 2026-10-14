"""Opening a database connection."""

import psycopg
from psycopg.rows import dict_row

from copilot.config import ConfigError, Settings


def connect(settings: Settings) -> psycopg.Connection:
    """Opens a connection whose rows are dicts. The caller commits and closes."""
    if not settings.database_url:
        raise ConfigError("DATABASE_URL is not set")
    return psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        # None switches prepared statements off altogether.
        prepare_threshold=5 if settings.db_prepared_statements else None,
    )
