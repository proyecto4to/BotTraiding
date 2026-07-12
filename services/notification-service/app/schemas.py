"""Pydantic schemas for notification-service.

NotificationOut is the frontend contract for the dashboard alerts page:
{id, subject, severity, title, body, created_at, status} (+ user_id so the
admin feed can attribute rows). Keep it flat and stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]


class EventIn(BaseModel):
    """Internal REST intake (POST /notifications/ingest) — the fallback for
    services that cannot reach NATS. Mirrors what the NATS subscriber builds
    from a bus message."""

    subject: str = Field(min_length=1, max_length=255)
    severity: Severity | None = None  # explicit override; else derived by rules
    account_id: str | None = None
    user_id: str | None = None
    payload: dict = Field(default_factory=dict)


class NotificationOut(BaseModel):
    id: str
    user_id: str | None = None
    subject: str
    severity: str
    title: str
    body: str
    created_at: datetime
    status: str

    model_config = {"from_attributes": True}


class IngestResponse(BaseModel):
    accepted: bool
    notification_ids: list[str]


class PreferencesIn(BaseModel):
    subjects: list[str] = Field(default_factory=list)
    account_ids: list[str] = Field(default_factory=list)

    email_enabled: bool = False
    email_address: str | None = None
    email_min_severity: Severity = "info"

    telegram_enabled: bool = False
    telegram_chat_id: str | None = None
    telegram_min_severity: Severity = "info"

    webhook_enabled: bool = False
    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_min_severity: Severity = "info"


class PreferencesOut(PreferencesIn):
    user_id: str

    model_config = {"from_attributes": True}


class TestSendIn(BaseModel):
    user_id: str
    channel: Literal["email", "telegram", "webhook"]
    message: str = "Test notification from notification-service"


class TestSendResponse(BaseModel):
    notification_id: str
    channel: str
    status: str
    error: str | None = None
