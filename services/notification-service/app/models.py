"""SQLAlchemy models for notification-service (Fase 16).

init.sql already ships a generic `notifications` table (FK to users(id),
one row per channel) that does not match this service's routing model and is
read-only, so — following risk-engine's precedent with `risk_engine_limits` —
the service owns its own tables:

- `notification_messages`     one row per (event x target user); what the
                              dashboard alerts page polls.
- `notification_preferences`  per-user routing config: subject filters,
                              account filters, per-channel enable/target/
                              min-severity.
- `notification_dead_letters` undeliverable sends (channel, target, error,
                              retry count) for later inspection/replay.

Migrations use version_table="alembic_version_notification".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    # Naive UTC: the columns are DateTime-without-timezone (execution-engine
    # convention), so a tz-aware value would be dialect-dependent.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class NotificationRow(Base):
    __tablename__ = "notification_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # NULL user_id = unrouted/broadcast event kept for the admin audit feed.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # pending -> sent (all routed channels ok, or none routed)
    #         -> failed (some channels ok, some dead-lettered)
    #         -> dead (every routed channel exhausted retries)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now(), onupdate=func.now()
    )


class PreferenceRow(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # NATS-style subject patterns ("risk.>", "execution.live_order", "*.report").
    # Empty list = subscribe to everything.
    subjects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Restrict account-scoped events to these account ids. Empty = all accounts.
    account_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_min_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")

    telegram_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_min_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")

    webhook_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_min_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now(), onupdate=func.now()
    )


class DeadLetterRow(Base):
    __tablename__ = "notification_dead_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    notification_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notification_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    target: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now()
    )
