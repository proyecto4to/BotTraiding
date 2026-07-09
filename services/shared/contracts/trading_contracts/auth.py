"""Pure JWT verification helper shared across services (Fase 2).

No DB access, no FastAPI dependency on auth-service internals. Any service
that needs to verify a bearer token issued by auth-service can import
``decode_token``/``TokenPayload`` from here instead of duplicating the JWT
logic. Requires the same ``JWT_SECRET`` env var (or explicit secret) as
auth-service uses to sign tokens.
"""

from __future__ import annotations

import os
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel

ALGORITHM = "HS256"


class TokenPayload(BaseModel):
    """Decoded claims of an access token issued by auth-service."""

    sub: str  # user_id
    roles: list[str] = []
    type: str = "access"
    exp: int | None = None
    mfa_pending: bool = False


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or invalid."""


def _resolve_secret(secret: str | None) -> str:
    resolved = secret or os.environ.get("JWT_SECRET")
    if not resolved:
        raise TokenError("JWT_SECRET is not configured")
    return resolved


def decode_token(token: str, secret: str | None = None) -> TokenPayload:
    """Decode and verify a JWT, raising TokenError on any failure."""
    resolved_secret = _resolve_secret(secret)
    try:
        payload: dict[str, Any] = jwt.decode(
            token, resolved_secret, algorithms=[ALGORITHM]
        )
    except JWTError as exc:
        raise TokenError(str(exc)) from exc

    try:
        return TokenPayload(**payload)
    except Exception as exc:  # pydantic ValidationError
        raise TokenError(f"malformed token payload: {exc}") from exc
