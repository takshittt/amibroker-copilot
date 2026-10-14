import pytest

from .conftest import sign_up


def test_sign_up_then_log_in(client):
    auth = sign_up(client, "Trader@Example.in")
    assert client.get("/v1/me/usage", headers=auth).status_code == 200
    response = client.post(
        "/v1/auth/login", json={"email": " trader@example.IN ", "password": "a long passphrase"}
    )
    assert response.status_code == 200
    assert response.json()["token"]


def test_email_is_stored_lower_case_and_password_only_as_a_hash(client, pool):
    sign_up(client, "Trader@Example.in")
    with pool.connection() as conn:
        row = conn.execute("select email, password_hash from users").fetchone()
    assert row["email"] == "trader@example.in"
    assert row["password_hash"].startswith("$argon2id$")
    assert "a long passphrase" not in row["password_hash"]


def test_second_account_with_the_same_email_whatever_its_case(client):
    sign_up(client, "trader@example.in")
    response = client.post(
        "/v1/auth/signup",
        json={"email": "TRADER@example.in", "password": "another passphrase", "name": "X"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"email": "not-an-email", "password": "a long passphrase", "name": "A"}, "email"),
        ({"email": "a@b.in", "password": "short", "name": "A"}, "at least 10"),
        ({"email": "a@b.in", "password": "a long passphrase", "name": "   "}, "name"),
        ({"email": "a@b.in", "password": "a long passphrase"}, "name"),
        ({"email": "a@b.in", "password": "a long passphrase", "name": "A", "admin": True}, "admin"),
    ],
)
def test_bad_sign_up(client, body, words):
    response = client.post("/v1/auth/signup", json=body)
    assert response.status_code == 422
    assert words in response.json()["error"]["message"]


def test_wrong_password_and_unknown_email_get_the_same_answer(client):
    sign_up(client)
    wrong = client.post("/v1/auth/login", json={"email": "trader@example.in", "password": "x" * 12})
    unknown = client.post("/v1/auth/login", json={"email": "who@example.in", "password": "x" * 12})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_attempts_are_limited_per_email(make_client):
    client, _ = make_client(login_attempts=3)
    sign_up(client)
    body = {"email": "trader@example.in", "password": "wrong password"}
    codes = [
        client.post("/v1/auth/login", json=body, headers={"X-Client-IP": f"10.0.0.{n}"}).status_code
        for n in range(4)
    ]
    assert codes == [401, 401, 401, 429]
    # Even the right password is refused until the window passes.
    right = {"email": "trader@example.in", "password": "a long passphrase"}
    assert (
        client.post("/v1/auth/login", json=right, headers={"X-Client-IP": "10.0.0.9"}).status_code
        == 429
    )


def test_login_attempts_are_limited_per_ip(make_client):
    client, _ = make_client(login_attempts=3)
    codes = [
        client.post(
            "/v1/auth/login",
            json={"email": f"user{n}@example.in", "password": "wrong password"},
            headers={"X-Client-IP": "203.0.113.7"},
        ).status_code
        for n in range(4)
    ]
    assert codes == [401, 401, 401, 429]
    other_ip = client.post(
        "/v1/auth/login",
        json={"email": "user9@example.in", "password": "wrong password"},
        headers={"X-Client-IP": "203.0.113.8"},
    )
    assert other_ip.status_code == 401


def test_successful_login_clears_the_count_for_that_email(make_client):
    client, _ = make_client(login_attempts=3)
    sign_up(client)
    wrong = {"email": "trader@example.in", "password": "wrong password"}
    right = {"email": "trader@example.in", "password": "a long passphrase"}
    client.post("/v1/auth/login", json=wrong, headers={"X-Client-IP": "1.1.1.1"})
    client.post("/v1/auth/login", json=wrong, headers={"X-Client-IP": "1.1.1.2"})
    assert (
        client.post("/v1/auth/login", json=right, headers={"X-Client-IP": "1.1.1.3"}).status_code
        == 200
    )
    assert (
        client.post("/v1/auth/login", json=wrong, headers={"X-Client-IP": "1.1.1.4"}).status_code
        == 401
    )


def test_sign_ups_are_limited_per_ip(make_client):
    client, _ = make_client(signups_per_ip_per_hour=2)
    codes = [
        client.post(
            "/v1/auth/signup",
            json={"email": f"u{n}@example.in", "password": "a long passphrase", "name": "U"},
            headers={"X-Client-IP": "198.51.100.1"},
        ).status_code
        for n in range(3)
    ]
    assert codes == [201, 201, 429]
