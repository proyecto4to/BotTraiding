"""auth-service - Fase 2: full user system (registro, login, OAuth, JWT, MFA,
roles, auditoria, historial).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): Usuarios, JWT, OAuth, MFA, roles, auditoria
"""

from __future__ import annotations

from datetime import datetime, timezone

import pyotp
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import oauth, security
from app.audit import record as audit_record
from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import AuditLog, OAuthAccount, RefreshToken, Role, User, UserRole
from app.schemas import (
    AuditLogOut,
    AuditLogPage,
    LoginMfaRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MfaEnableResponse,
    MfaVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    RoleAssignRequest,
    UserOut,
)
from trading_contracts.auth import TokenError, decode_token

SERVICE_NAME = "auth-service"
DEFAULT_ROLE = "viewer"
VALID_ROLES = {"admin", "trader", "viewer", "auditor"}

app = FastAPI(title="auth-service", version="0.2.0")


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        roles=[ur.role.name for ur in user.roles],
    )


def _get_or_create_role(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.commit()
        db.refresh(role)
    return role


def _issue_token_pair(db: Session, user: User) -> tuple[str, str]:
    role_names = [ur.role.name for ur in user.roles]
    access = security.create_access_token(user.id, role_names)
    refresh, expires_at = security.create_refresh_token(user.id, role_names)
    db.add(RefreshToken(user_id=user.id, token=refresh, expires_at=expires_at))
    db.commit()
    return access, refresh


# --------------------------------------------------------------------------
# Registro / Login / Refresh / Logout
# --------------------------------------------------------------------------


@app.post("/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> UserOut:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, password_hash=security.hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    role = _get_or_create_role(db, DEFAULT_ROLE)
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    db.refresh(user)

    audit_record(
        db,
        actor=user.id,
        action="register",
        metadata={"email": user.email, "ip": _client_ip(request)},
    )
    return _user_out(user)


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or not security.verify_password(payload.password, user.password_hash or ""):
        audit_record(
            db,
            actor=payload.email,
            action="login-failure",
            metadata={"ip": _client_ip(request)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.mfa_enabled:
        pending = security.create_mfa_pending_token(user.id)
        audit_record(
            db,
            actor=user.id,
            action="login-mfa-pending",
            metadata={"ip": _client_ip(request)},
        )
        return LoginResponse(mfa_required=True, mfa_pending_token=pending)

    access, refresh = _issue_token_pair(db, user)
    audit_record(db, actor=user.id, action="login", metadata={"ip": _client_ip(request)})
    return LoginResponse(access_token=access, refresh_token=refresh)


@app.post("/auth/login/mfa", response_model=LoginResponse)
def login_mfa(payload: LoginMfaRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        pending_payload = decode_token(payload.mfa_pending_token)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if not pending_payload.mfa_pending or pending_payload.type != "mfa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA challenge token")

    user = db.get(User, pending_payload.sub)
    if user is None or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA not enabled for user")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(payload.code, valid_window=1):
        audit_record(
            db,
            actor=user.id,
            action="login-failure",
            reason="invalid mfa code",
            metadata={"ip": _client_ip(request)},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")

    access, refresh = _issue_token_pair(db, user)
    audit_record(db, actor=user.id, action="login", metadata={"ip": _client_ip(request), "mfa": True})
    return LoginResponse(access_token=access, refresh_token=refresh)


@app.post("/auth/refresh", response_model=LoginResponse)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        decoded = decode_token(payload.refresh_token)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if decoded.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    stored = db.scalar(select(RefreshToken).where(RefreshToken.token == payload.refresh_token))
    if stored is None or stored.revoked or stored.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or expired")

    user = db.get(User, decoded.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    role_names = [ur.role.name for ur in user.roles]
    access = security.create_access_token(user.id, role_names)
    return LoginResponse(access_token=access, refresh_token=payload.refresh_token)


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> None:
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token == payload.refresh_token))
    if stored is not None and not stored.revoked:
        stored.revoked = True
        db.commit()
        audit_record(db, actor=stored.user_id, action="logout", metadata={})
    return None


# --------------------------------------------------------------------------
# MFA
# --------------------------------------------------------------------------


@app.post("/auth/mfa/enable", response_model=MfaEnableResponse)
def mfa_enable(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MfaEnableResponse:
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.commit()

    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="TradingPlatform")
    audit_record(db, actor=user.id, action="mfa-change", reason="enable-requested", metadata={})
    return MfaEnableResponse(secret=secret, provisioning_uri=uri)


@app.post("/auth/mfa/verify")
def mfa_verify(
    payload: MfaVerifyRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA not initialized; call /auth/mfa/enable first")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")

    user.mfa_enabled = True
    db.commit()
    audit_record(db, actor=user.id, action="mfa-change", reason="enabled", metadata={})
    return {"mfa_enabled": True}


# --------------------------------------------------------------------------
# OAuth (Google)
# --------------------------------------------------------------------------


@app.get("/auth/oauth/google/login")
def oauth_google_login(state: str | None = None) -> RedirectResponse:
    return RedirectResponse(oauth.build_authorize_url(state=state))


@app.get("/auth/oauth/google/callback", response_model=LoginResponse)
async def oauth_google_callback(
    code: str = Query(...), db: Session = Depends(get_db)
) -> LoginResponse:
    try:
        profile = await oauth.exchange_code(code)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth exchange failed: {exc}") from exc

    email = profile["email"]
    provider_user_id = profile["provider_user_id"]

    oauth_account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google",
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    if oauth_account is not None:
        user = db.get(User, oauth_account.user_id)
    else:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=None)
            db.add(user)
            db.commit()
            db.refresh(user)
            role = _get_or_create_role(db, DEFAULT_ROLE)
            db.add(UserRole(user_id=user.id, role_id=role.id))
            db.commit()
            db.refresh(user)
        db.add(OAuthAccount(user_id=user.id, provider="google", provider_user_id=provider_user_id))
        db.commit()

    audit_record(db, actor=user.id, action="login", metadata={"provider": "google"})
    access, refresh = _issue_token_pair(db, user)
    return LoginResponse(access_token=access, refresh_token=refresh)


# --------------------------------------------------------------------------
# Roles / RBAC / me
# --------------------------------------------------------------------------


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@app.post("/auth/users/{user_id}/roles")
def assign_role(
    user_id: str,
    payload: RoleAssignRequest,
    admin: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
) -> UserOut:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role '{payload.role}'")

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = _get_or_create_role(db, payload.role)
    existing = db.get(UserRole, {"user_id": target.id, "role_id": role.id})

    if payload.action == "assign":
        if existing is None:
            db.add(UserRole(user_id=target.id, role_id=role.id))
            db.commit()
    else:
        if existing is not None:
            db.delete(existing)
            db.commit()

    db.refresh(target)
    audit_record(
        db,
        actor=admin.id,
        action="role-change",
        metadata={"target": target.id, "role": payload.role, "action": payload.action},
    )
    return _user_out(target)


# --------------------------------------------------------------------------
# Auditoria / Historial
# --------------------------------------------------------------------------


@app.get("/auth/audit", response_model=AuditLogPage)
def audit_list(
    user_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, le=200, ge=1),
    offset: int = Query(default=0, ge=0),
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogPage:
    role_names = {ur.role.name for ur in _actor.roles}
    if not ({"admin", "auditor"} & role_names):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires role 'admin' or 'auditor'")

    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.actor == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if date_from is not None:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditLog.created_at <= date_to)

    total = len(db.scalars(stmt).all())
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    items = db.scalars(stmt).all()

    return AuditLogPage(
        items=[AuditLogOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get("/auth/me/history", response_model=AuditLogPage)
def my_history(
    limit: int = Query(default=50, le=200, ge=1),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditLogPage:
    session_actions = [
        "login",
        "login-failure",
        "login-mfa-pending",
        "logout",
        "register",
        "mfa-change",
    ]
    stmt = select(AuditLog).where(AuditLog.actor == user.id, AuditLog.action.in_(session_actions))
    total = len(db.scalars(stmt).all())
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    items = db.scalars(stmt).all()

    return AuditLogPage(
        items=[AuditLogOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
