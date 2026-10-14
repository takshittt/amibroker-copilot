"""Who may call what: the shared BFF key, session tokens, and other users' data."""

import uuid

import pytest
from fastapi.testclient import TestClient

from copilot.api.app import KEY_HEADER, create_app
from copilot.config import ConfigError

from .conftest import KEY, new_conversation, settings, sign_up

ROUTES = [
    ("GET", "/v1/health"),
    ("POST", "/v1/auth/signup"),
    ("POST", "/v1/auth/login"),
    ("GET", "/v1/markets"),
    ("GET", "/v1/me/usage"),
    ("POST", "/v1/conversations"),
    ("GET", "/v1/conversations"),
    ("GET", f"/v1/conversations/{uuid.uuid4()}"),
    ("POST", f"/v1/conversations/{uuid.uuid4()}/messages"),
    ("POST", f"/v1/messages/{uuid.uuid4()}/apply-fixes"),
    ("POST", f"/v1/messages/{uuid.uuid4()}/feedback"),
    ("GET", "/v1/no-such-route"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("key", [None, "", "wrong", KEY[:-1], KEY + "x"])
def test_every_route_refuses_a_request_without_the_right_key(client, method, path, key):
    headers = {KEY_HEADER: key} if key is not None else {}
    # Replace the client's default key header.
    response = client.request(method, path, headers={KEY_HEADER: ""} | headers, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_with_the_key_health_answers(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_key_is_checked_before_the_body_is_read(client):
    response = client.post("/v1/auth/login", content=b"not json", headers={KEY_HEADER: "wrong"})
    assert response.status_code == 401


def test_body_that_is_too_large_is_refused(make_client):
    client, _ = make_client(max_body_bytes=100)
    response = client.post("/v1/auth/login", json={"email": "a@b.in", "password": "x" * 200})
    assert response.status_code == 413


@pytest.mark.parametrize(
    "header",
    [None, "Bearer", "Bearer garbage", "Token abc", "bearer  "],
)
def test_routes_that_need_a_session_refuse_a_bad_token(client, header):
    headers = {"Authorization": header} if header is not None else {}
    for path in ("/v1/me/usage", "/v1/conversations", "/v1/markets"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Please sign in again."


def test_token_of_a_deleted_user_is_refused(client, pool):
    auth = sign_up(client)
    with pool.connection() as conn:
        conn.execute("delete from users")
    assert client.get("/v1/me/usage", headers=auth).status_code == 401


def test_another_users_conversation_looks_like_none(client):
    mine = sign_up(client, "one@example.in")
    theirs = sign_up(client, "two@example.in")
    conversation = new_conversation(client, mine)
    assert client.get(f"/v1/conversations/{conversation}", headers=theirs).status_code == 404
    response = client.post(
        f"/v1/conversations/{conversation}/messages", json={"text": "x"}, headers=theirs
    )
    assert response.status_code == 404
    assert client.get("/v1/conversations", headers=theirs).json() == []


def test_spend_cap_without_prices_stops_the_start(pool, redis_client, catalog):
    from copilot.api.app import Services
    from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
    from copilot.embeddings import FakeEmbedder
    from copilot.pipeline.llm import ScriptedLLM

    services = Services(
        settings(daily_spend_cap_usd=5.0, cheap_price_out=None),
        pool,
        redis_client,
        catalog,
        ScriptedLLM([]),
        FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS),
    )
    with pytest.raises(ConfigError, match="prices"):
        create_app(services)


def test_short_secret_stops_the_start(pool, redis_client, catalog):
    from copilot.api.app import Services
    from copilot.config import DEFAULT_EMBEDDING_DIMENSIONS
    from copilot.embeddings import FakeEmbedder
    from copilot.pipeline.llm import ScriptedLLM

    services = Services(
        settings(jwt_secret="too short"),
        pool,
        redis_client,
        catalog,
        ScriptedLLM([]),
        FakeEmbedder(DEFAULT_EMBEDDING_DIMENSIONS),
    )
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        TestClient(create_app(services))
