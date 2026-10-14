"""Applies the numbered SQL files in api/migrations, each once, in order.

    python -m copilot.db.migrate

A file that has been applied is never edited: a change to the schema is
a new file with the next number.
"""

import sys
from pathlib import Path

import psycopg

from copilot.config import ConfigError, load_settings
from copilot.db.connection import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
# Any fixed number: stops two runs from applying migrations at once.
_LOCK_KEY = 4_170_301


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Applies the migrations not yet recorded and returns their names.

    Each file runs in its own transaction with its record, so a failure
    leaves the database at the last good migration.
    """
    conn.execute(
        "create table if not exists schema_migrations ("
        "name text primary key, applied_at timestamptz not null default now())"
    )
    conn.commit()

    applied_now = []
    for path in sorted(directory.glob("*.sql")):
        with conn.transaction():
            conn.execute("select pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            done = conn.execute(
                "select 1 from schema_migrations where name = %s", (path.name,)
            ).fetchone()
            if done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
        applied_now.append(path.name)
    return applied_now


def main() -> int:
    try:
        conn = connect(load_settings())
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2
    with conn:
        applied = migrate(conn)
    if applied:
        print(f"Applied: {', '.join(applied)}")
    else:
        print("Nothing to apply; the database is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
