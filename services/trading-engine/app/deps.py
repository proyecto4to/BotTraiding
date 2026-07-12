"""Auth dependencies for bot management endpoints.

DB-free JWT verification via the shared trading_contracts.auth helper
(same JWT_SECRET as auth-service); roles come straight from the token.

Policy (task spec): any authenticated user may manage PAPER bots; anything
touching a LIVE bot (create, switch to live, start/stop, run-once) requires
role 'admin' — going live is an explicit, privileged act (architecture
section 10).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts import ExecutionMode
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


def require_mode_role(token: TokenPayload, execution_mode: str | ExecutionMode) -> None:
    """403 unless the token may act on a bot with this execution mode."""
    mode = (
        execution_mode.value
        if isinstance(execution_mode, ExecutionMode)
        else str(execution_mode)
    )
    if mode == ExecutionMode.LIVE.value and "admin" not in token.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="live-mode bots require role 'admin'",
        )
