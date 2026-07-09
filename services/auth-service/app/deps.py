"""Reusable FastAPI dependencies: current user + role-based access control.

`get_current_user` verifies the bearer token via the shared, DB-free
`trading_contracts.auth.decode_token` helper, then loads the user row for
DB-backed checks (is_active, current roles). Other services that only need
pure token verification (no DB) should import `trading_contracts.auth`
directly instead of depending on auth-service.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from trading_contracts.auth import TokenError, decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if payload.type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not an access token")

    user = db.get(User, payload.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


def require_role(role_name: str):
    """Dependency factory: raises 403 unless the current user has `role_name`."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        role_names = {ur.role.name for ur in user.roles}
        if role_name not in role_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role '{role_name}'",
            )
        return user

    return _checker
