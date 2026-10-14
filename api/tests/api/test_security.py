import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from copilot.api import security
from copilot.config import ConfigError, Settings

SETTINGS = Settings(jwt_secret="s" * 40, bff_shared_secret="k" * 40)


def test_password_hash_is_argon2id_and_verifies():
    stored = security.hash_password("a long passphrase")
    assert stored.startswith("$argon2id$")
    assert security.verify_password(stored, "a long passphrase")
    assert not security.verify_password(stored, "a long passphrasE")
    assert not security.verify_password("not a hash", "anything")


def test_same_password_hashes_differently_each_time():
    assert security.hash_password("a long passphrase") != security.hash_password(
        "a long passphrase"
    )


@pytest.mark.parametrize(
    ("password", "ok"), [("x" * 9, False), ("x" * 10, True), ("x" * 128, True), ("x" * 129, False)]
)
def test_password_length_rules(password, ok):
    assert (security.password_problem(password) is None) == ok


def test_token_round_trip():
    user = uuid.uuid4()
    token = security.issue_token(SETTINGS, user)
    assert security.user_from_token(SETTINGS, token) == user
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


def test_expired_token_is_refused():
    old = datetime.now(UTC) - timedelta(days=8)
    token = security.issue_token(SETTINGS, uuid.uuid4(), now=old)
    assert security.user_from_token(SETTINGS, token) is None


def test_token_signed_with_another_secret_is_refused():
    other = Settings(jwt_secret="t" * 40, bff_shared_secret="k" * 40)
    token = security.issue_token(other, uuid.uuid4())
    assert security.user_from_token(SETTINGS, token) is None


def test_unsigned_and_other_algorithm_tokens_are_refused():
    claims = {"sub": str(uuid.uuid4()), "iat": 0, "exp": 9999999999}
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert security.user_from_token(SETTINGS, unsigned) is None
    other_alg = jwt.encode(claims, "s" * 40, algorithm="HS512")
    assert security.user_from_token(SETTINGS, other_alg) is None


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
def test_malformed_token(token):
    assert security.user_from_token(SETTINGS, token) is None


def test_token_without_expiry_is_refused():
    token = jwt.encode({"sub": str(uuid.uuid4()), "iat": 0}, "s" * 40, algorithm="HS256")
    assert security.user_from_token(SETTINGS, token) is None


def test_key_comparison():
    assert security.key_matches(SETTINGS, "k" * 40)
    assert not security.key_matches(SETTINGS, "k" * 39)
    assert not security.key_matches(SETTINGS, None)
    assert not security.key_matches(Settings(), "")


@pytest.mark.parametrize(
    "changes",
    [{"jwt_secret": None}, {"jwt_secret": "short"}, {"bff_shared_secret": "x" * 31}],
)
def test_short_or_missing_secrets_stop_the_start(changes):
    values = {"jwt_secret": "s" * 40, "bff_shared_secret": "k" * 40, **changes}
    with pytest.raises(ConfigError):
        security.check_secrets(Settings(**values))


def test_random_password_is_long_enough():
    assert security.password_problem(security.random_password()) is None
