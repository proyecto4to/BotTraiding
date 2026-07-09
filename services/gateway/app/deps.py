"""Auth dependencies for the gateway: pure JWT verification, no DB.

Uses the shared, DB-free `trading_contracts.auth.decode_token` helper (Fase 2)
so the gateway never touches auth-service's tables. Roles are enforced from
the token claims; the source of truth for role assignment stays in
auth-service, which mints the tokens.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from trading_contracts.auth import TokenError, TokenPayload, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def _payload_from_raw_token(token: str) -> TokenPayload:
    try:
        payload = decode_token(token)
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


def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    """FastAPI dependency: verified access-token claims of the caller."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return _payload_from_raw_token(credentials.credentials)


def payload_from_request(request: Request) -> TokenPayload:
    """Same verification as `get_token_payload` but callable outside the
    dependency system (used by the reverse proxy catch-all route)."""
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return _payload_from_raw_token(token)


def require_role(role_name: str):
    """Dependency factory: raises 403 unless the token carries `role_name`."""

    def _checker(payload: TokenPayload = Depends(get_token_payload)) -> TokenPayload:
        if role_name not in payload.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{role_name}'",
            )
        return payload

    return _checker


require_admin = require_role("admin")
