"""Fixtures for tests that need a real Postgres with pgvector.

They use TEST_DATABASE_URL (the Makefile sets a local default). When the
database cannot be reached the tests are skipped with the reason shown,
unless REQUIRE_DB is set, as it is in CI, where they then fail.
"""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from copilot.db.migrate import migrate
from copilot.kb import load_catalog, load_notes

KB_DIR = Path(__file__).resolve().parents[3] / "kb"


def _unavailable(reason: str):
    if os.environ.get("REQUIRE_DB"):
        pytest.fail(f"REQUIRE_DB is set but the test database is not usable: {reason}")
    pytest.skip(f"database tests skipped: {reason}")


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        _unavailable("TEST_DATABASE_URL is not set")
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            name = conn.execute("select current_database()").fetchone()[0]
    except psycopg.Error as error:
        _unavailable(f"cannot connect ({' '.join(str(error).split())})")
    # The schema is wiped below, so refuse anything not named as a test database.
    if not name.endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL points at {name!r}; its name must end with _test")
    return url


@pytest.fixture(scope="session")
def migrated(database_url):
    """Wipes the test database and applies every migration, once for the run."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.commit()
        applied = migrate(conn)
    return applied


@pytest.fixture(scope="session")
def base(database_url, migrated):
    """The one connection the database tests share. Nothing on it is ever
    committed, so every test starts from the empty, migrated tables."""
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def db(base):
    """The shared connection inside a savepoint that is undone after the test."""
    with base.transaction(force_rollback=True):
        yield base


@pytest.fixture(scope="session")
def catalog():
    return load_catalog(KB_DIR)


@pytest.fixture(scope="session")
def notes():
    return load_notes(KB_DIR)


@pytest.fixture(scope="module")
def indexed(base, catalog, notes):
    """The shared connection with the real knowledge base indexed, for the
    tests in a module that only read. Undone when the module is finished.
    A module that uses this must not also use `db`."""
    from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
    from copilot.embeddings import FakeEmbedder
    from copilot.indexer import index_kb

    with base.transaction(force_rollback=True):
        index_kb(base, catalog, notes, FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS))
        yield base
