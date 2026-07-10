"""Auth dependency for the admin-gated execution-mode override.

DB-free JWT verification via the shared trading_contracts.auth helper
(same JWT_SECRET as auth-service); roles come straight from the token.
The token is optional at the endpoint level: it is only *required* when a
request overrides the environment's default execution mode (see main.py).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload | None:
    """None when no bearer token was sent; 401 when one was sent but is bad."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    if payload.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an access token"
        )
    return payload


def require_admin_override(token: TokenPayload | None) -> TokenPayload:
    """Enforce the admin gate for execution-mode overrides."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="execution_mode override requires authentication",
        )
    if "admin" not in token.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="execution_mode override requires role 'admin'",
        )
    return token
