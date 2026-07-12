"""Auth dependency for the admin-gated reconciliation endpoint.

DB-free JWT verification via the shared trading_contracts.auth helper (same
JWT_SECRET as auth-service); roles come straight from the token. Same
pattern as execution-engine's mode-override gate. Only the reconcile
endpoint is gated: the portfolio read/ingest endpoints stay open for the
risk-engine/execution-engine service-to-service calls.
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
            detail="reconciliation requires authentication",
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
            detail="reconciliation requires role 'admin'",
        )
    return payload
