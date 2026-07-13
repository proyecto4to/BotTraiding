"""Password hashing + JWT issuing for auth-service.

Token *verification* logic that other services need lives in the shared
`trading_contracts.auth` module (pure, DB-free). This module additionally
knows how to *issue* tokens, which is auth-service's own responsibility.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from trading_contracts.auth import ALGORITHM

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-insecure-secret-change-me")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
MFA_PENDING_TOKEN_EXPIRE_MINUTES = int(
    os.environ.get("MFA_PENDING_TOKEN_EXPIRE_MINUTES", "5")
)

# bcrypt is the primary scheme (the operator's OPERATOR_PASSWORD_HASH is a
# bcrypt hash); pbkdf2_sha256 stays accepted so any previously-hashed
# passwords still verify.
pwd_context = CryptContext(schemes=["bcrypt", "pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def _create_token(subject: str, roles: list[str], expires_delta: timedelta, **extra) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "roles": roles,
        "exp": int((now + expires_delta).timestamp()),
        "iat": int(now.timestamp()),
        "jti": uuid.uuid4().hex,
        **extra,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def create_access_token(user_id: str, roles: list[str]) -> str:
    return _create_token(
        user_id, roles, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), type="access"
    )


def create_refresh_token(user_id: str, roles: list[str]) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token = _create_token(
        user_id, roles, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), type="refresh"
    )
    return token, expires_at


def create_mfa_pending_token(user_id: str) -> str:
    return _create_token(
        user_id,
        [],
        timedelta(minutes=MFA_PENDING_TOKEN_EXPIRE_MINUTES),
        type="mfa_pending",
        mfa_pending=True,
    )
