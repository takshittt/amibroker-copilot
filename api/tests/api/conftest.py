"""Fixtures for the API tests: the real app, a real Postgres and Redis,
and a scripted model. Nothing here calls OpenAI.

The API commits what it writes, so these tests use their own database,
named after TEST_DATABASE_URL with `_api_test` in place of `_test`, and
Redis database number from TEST_REDIS_URL. Both are wiped as needed.
"""

import json
import os
from pathlib import Path

import psycopg
import pytest
import redis
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from copilot.api.app import KEY_HEADER, Services, create_app
from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS, Settings
from copilot.db.kb import load_catalog_from_db
from copilot.db.migrate import migrate
from copilot.embeddings import FakeEmbedder
from copilot.indexer import index_kb
from copilot.kb import load_catalog, load_notes
from copilot.pipeline.llm import ScriptedLLM

KB_DIR = Path(__file__).resolve().parents[3] / "kb"
KEY = "k" * 40
SECRET = "s" * 40


def _unavailable(reason: str):
    if os.environ.get("REQUIRE_DB"):
        pytest.fail(f"REQUIRE_DB is set but a test service is not usable: {reason}")
    pytest.skip(f"API tests skipped: {reason}")


@pytest.fixture(scope="session")
def api_database_url():
    base = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not base:
        _unavailable("TEST_DATABASE_URL is not set")
    try:
        with psycopg.connect(base, autocommit=True, connect_timeout=5) as conn:
            name = conn.execute("select current_database()").fetchone()[0]
            if not name.endswith("_test"):
                pytest.fail(f"TEST_DATABASE_URL points at {name!r}; it must end with _test")
            api_name = name.removesuffix("_test") + "_api_test"
            exists = conn.execute(
                "select 1 from pg_database where datname = %s", (api_name,)
            ).fetchone()
            if not exists:
                conn.execute(f'create database "{api_name}"')
    except psycopg.Error as error:
        _unavailable(f"cannot connect ({' '.join(str(error).split())})")
    url = base.rsplit("/", 1)[0] + "/" + api_name
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("drop schema public cascade")
        conn.execute("create schema public")
        conn.commit()
        migrate(conn)
        index_kb(
            conn,
            load_catalog(KB_DIR),
            load_notes(KB_DIR),
            FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS),
        )
        conn.commit()
    return url


@pytest.fixture(scope="session")
def pool(api_database_url):
    made = ConnectionPool(
        api_database_url, min_size=1, max_size=4, kwargs={"row_factory": dict_row}, open=True
    )
    yield made
    made.close()


@pytest.fixture(scope="session")
def redis_client():
    url = os.environ.get("TEST_REDIS_URL", "").strip()
    if not url:
        _unavailable("TEST_REDIS_URL is not set")
    client = redis.Redis.from_url(url)
    try:
        client.ping()
    except redis.RedisError as error:
        _unavailable(f"cannot reach Redis ({error})")
    # Each test wipes this database, so never the one in everyday use.
    if client.connection_pool.connection_kwargs.get("db", 0) == 0:
        pytest.fail("TEST_REDIS_URL must name a Redis database other than 0, such as /15")
    return client


@pytest.fixture(scope="session")
def catalog(pool):
    with pool.connection() as conn:
        return load_catalog_from_db(conn)


@pytest.fixture(autouse=True)
def clean(request, pool, redis_client):
    with pool.connection() as conn:
        conn.execute("truncate users cascade")
    redis_client.flushdb()
    yield


def settings(**changes) -> Settings:
    values = {
        "jwt_secret": SECRET,
        "bff_shared_secret": KEY,
        "strong_model": "strong-model",
        "cheap_model": "cheap-model",
        "strong_price_in": 2.0,
        "strong_price_out": 8.0,
        "cheap_price_in": 0.1,
        "cheap_price_out": 0.4,
        "keepalive_seconds": 5,
    }
    values.update(changes)
    return Settings(**values)


@pytest.fixture
def make_client(pool, redis_client, catalog):
    """Builds the app around a scripted model. Returns (client, model)."""

    def _make(script=None, **setting_changes):
        model = ScriptedLLM(script if script is not None else [])
        services = Services(
            settings=settings(**setting_changes),
            pool=pool,
            redis=redis_client,
            catalog=catalog,
            llm=model,
            embedder=FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS),
        )
        client = TestClient(create_app(services), headers={KEY_HEADER: KEY})
        return client, model

    return _make


@pytest.fixture
def client(make_client):
    return make_client()[0]


def sign_up(client, email="trader@example.in", password="a long passphrase", name="Trader"):
    response = client.post(
        "/v1/auth/signup", json={"email": email, "password": password, "name": name}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def new_conversation(client, auth, mode="write", market="nse_eq", timeframe="daily"):
    response = client.post(
        "/v1/conversations",
        json={"mode": mode, "market_id": market, "timeframe": timeframe},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def stream(client, path, auth, body=None):
    """Posts and reads the event stream. Returns (status code, [(event, data)])."""
    with client.stream("POST", path, json=body, headers=auth) as response:
        if response.status_code != 200:
            response.read()
            return response.status_code, response.json()
        events = []
        event = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                events.append((event, json.loads(line.removeprefix("data: "))))
        return 200, events
