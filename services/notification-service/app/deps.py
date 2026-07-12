"""Auth dependencies (risk-engine pattern): DB-free JWT verification via the
shared trading_contracts.auth helper (same JWT_SECRET as auth-service);
roles come straight from the token."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
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


def require_admin(payload: TokenPayload = Depends(get_token_payload)) -> TokenPayload:
    if "admin" not in payload.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Requires role 'admin'"
        )
    return payload


def is_admin(payload: TokenPayload) -> bool:
    return "admin" in payload.roles
