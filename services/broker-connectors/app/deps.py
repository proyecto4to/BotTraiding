"""Admin auth dependency for the key-rotation endpoint.

DB-free JWT verification via the shared trading_contracts.auth helper (same
JWT_SECRET as auth-service); roles come straight from the token. Only the
credential-rotation endpoint is gated — connect/status/order endpoints keep
their service-to-service access.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    """401 without/with a bad token, 403 without the admin role."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="credential rotation requires authentication",
        )
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
    if "admin" not in payload.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="credential rotation requires role 'admin'",
        )
    return payload
