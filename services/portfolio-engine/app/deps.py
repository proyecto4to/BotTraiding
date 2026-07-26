"""Auth dependencies.

DB-free JWT verification via the shared trading_contracts.auth helper (same
JWT_SECRET as auth-service); roles come straight from the token.

- ``require_admin``: reconciliation, a human-initiated operation.
- ``require_caller``: the endpoints that MUTATE account state (execution
  ingest, marks). These drive cash, positions, PnL and peak equity — the same
  numbers the risk limits and the paper->live gate are measured against — so an
  unauthenticated caller could quietly rewrite the account's history. Accepts a
  service token from a sibling service or a real user token.

Reads stay open: they leak no secrets and the loopback binding keeps them off
the network.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def require_caller(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    """Any authenticated caller: a sibling service or a logged-in user."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
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
    return payload


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
