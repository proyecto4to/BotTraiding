"""Auth dependencies for the scheduler: pure JWT verification, no DB.

Uses the shared, DB-free ``trading_contracts.auth.decode_token`` (Fase 2),
same pattern as the gateway: roles are enforced from the token claims;
auth-service (which mints the tokens) stays the source of truth.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    """FastAPI dependency: verified access-token claims of the caller."""
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
    if payload.mfa_pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA verification pending"
        )
    return payload


def require_admin(
    payload: TokenPayload = Depends(get_token_payload),
) -> TokenPayload:
    if "admin" not in payload.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Requires role 'admin'"
        )
    return payload
