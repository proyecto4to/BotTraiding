"""Pydantic request/response schemas for auth-service endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    id: str
    email: str
    is_active: bool
    mfa_enabled: bool
    roles: list[str]

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MfaPendingOut(BaseModel):
    mfa_pending_token: str
    mfa_required: bool = True


class LoginResponse(BaseModel):
    """Either a full token pair, or an MFA-pending challenge."""

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_pending_token: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MfaVerifyRequest(BaseModel):
    code: str


class MfaEnableResponse(BaseModel):
    secret: str
    provisioning_uri: str


class LoginMfaRequest(BaseModel):
    mfa_pending_token: str
    code: str


class RoleAssignRequest(BaseModel):
    role: str
    action: str = Field(default="assign", pattern="^(assign|revoke)$")


class AuditLogOut(BaseModel):
    id: str
    actor: str
    action: str
    reason: str | None
    audit_metadata: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int


class OAuthCallbackQuery(BaseModel):
    code: str
    state: str | None = None
