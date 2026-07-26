"""Auth dependencies. DB-free JWT verification via the shared helper.

- ``require_admin``: the operator-facing controls (enable/disable/halt/reset/
  promote-live) — decisions only a person should make.
- ``require_caller``: /autonomy/tick, driven by the scheduler. A cycle creates,
  starts, stops and rebalances real bots, so it needs an identity even though
  no human is behind it.
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
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
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
    payload: TokenPayload = Depends(require_caller),
) -> TokenPayload:
    if "admin" not in payload.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="requires role 'admin'"
        )
    return payload
