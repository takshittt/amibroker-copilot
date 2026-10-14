"""Passwords, session tokens and the shared BFF key.

Hashing and signing use established libraries (argon2-cffi, PyJWT); none
of the cryptography is written here. There is no auth framework.
"""

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from copilot.config import ConfigError, Settings

MIN_SECRET_BYTES = 32
MIN_PASSWORD = 10
MAX_PASSWORD = 128
_ALGORITHM = "HS256"
_hasher = PasswordHasher()  # argon2id with the library's recommended costs


def check_secrets(settings: Settings) -> None:
    """Refuses to go on with a missing or short secret."""
    for name, value in (
        ("JWT_SECRET", settings.jwt_secret),
        ("BFF_SHARED_SECRET", settings.bff_shared_secret),
    ):
        if not value or len(value.encode("utf-8")) < MIN_SECRET_BYTES:
            raise ConfigError(f"{name} must be set to at least {MIN_SECRET_BYTES} random bytes")


def password_problem(password: str) -> str | None:
    """Why a new password is not acceptable, or None. Length is what counts."""
    if len(password) < MIN_PASSWORD:
        return f"The password must be at least {MIN_PASSWORD} characters long."
    if len(password) > MAX_PASSWORD:
        return f"The password must be at most {MAX_PASSWORD} characters long."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def random_password() -> str:
    return secrets.token_urlsafe(18)


def issue_token(settings: Settings, user_id: uuid.UUID, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.token_days)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM)


def user_from_token(settings: Settings, token: str) -> uuid.UUID | None:
    """The user id in a valid token, or None. Only HS256 is accepted."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None


def key_matches(settings: Settings, given: str | None) -> bool:
    """Constant-time comparison with the shared BFF key."""
    expected = settings.bff_shared_secret or ""
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))
