"""Pure JWT verification helper shared across services (Fase 2).

No DB access, no FastAPI dependency on auth-service internals. Any service
that needs to verify a bearer token issued by auth-service can import
``decode_token``/``TokenPayload`` from here instead of duplicating the JWT
logic. Requires the same ``JWT_SECRET`` env var (or explicit secret) as
auth-service uses to sign tokens.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel

ALGORITHM = "HS256"

# Role carried by machine-to-machine tokens. Services mint these for their own
# outbound calls; no human ever holds one. Kept distinct from "admin" so an
# internal endpoint can accept a service without accepting every admin user,
# and so audit logs can tell a person apart from a background job.
SERVICE_ROLE = "service"

# Service tokens are minted per call and only need to survive one request.
SERVICE_TOKEN_TTL_SECONDS = 120


class TokenPayload(BaseModel):
    """Decoded claims of an access token issued by auth-service."""

    sub: str  # user_id, or "service:<name>" for machine-to-machine tokens
    roles: list[str] = []
    type: str = "access"
    exp: int | None = None
    mfa_pending: bool = False

    @property
    def is_service(self) -> bool:
        return SERVICE_ROLE in self.roles


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


def mint_service_token(service_name: str, secret: str | None = None) -> str:
    """Mint a short-lived machine-to-machine token for `service_name`.

    Internal services call each other directly (risk-engine -> portfolio-engine,
    execution-engine -> broker-connectors, ...). Those calls used to be
    unauthenticated, which meant anything that could reach the port could place
    an order straight at a broker connector, bypassing the risk engine. Every
    internal call now carries one of these instead.

    The signing key is the same JWT_SECRET the whole platform shares, so this is
    authentication between components, not a defence against an attacker who has
    already read the secret. It closes the "reachable == authorised" hole; the
    secret still has to be protected by deployment.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"service:{service_name}",
        "roles": [SERVICE_ROLE],
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=SERVICE_TOKEN_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, _resolve_secret(secret), algorithm=ALGORITHM)


def service_auth_header(service_name: str, secret: str | None = None) -> dict[str, str]:
    """`Authorization` header carrying a fresh service token, ready to splat
    into an httpx call: `headers=service_auth_header("risk-engine")`."""
    return {"Authorization": f"Bearer {mint_service_token(service_name, secret)}"}
