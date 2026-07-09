"""SQLAlchemy models for strategy-engine (Fase 5).

Mirrors infra/docker/init.sql's `strategies`, `strategy_versions` and
`strategy_configs`, extended (via this service's own Alembic migration,
never by editing init.sql) with the Fase 6 catalogue columns:
strategy_key, description, markets, timeframes, enabled, updated_at.

Ownership note: `user_id`/`account_id` are plain UUID columns without
cross-service foreign keys - auth-service owns `users` and
broker-connectors owns `broker_accounts`, and services never reach into
each other's tables (docs/ARCHITECTURE.md, principle 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class StrategyRecord(Base):
    """One row per code-registry strategy. The registry is the source of
    truth for code/metadata; the DB owns operational state (enabled)."""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    markets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["StrategyVersionRecord"]] = relationship(
        back_populates="strategy", cascade="all, delete-orphan"
    )


class StrategyVersionRecord(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    strategy: Mapped["StrategyRecord"] = relationship(back_populates="versions")
    configs: Mapped[list["StrategyConfigRecord"]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class StrategyConfigRecord(Base):
    """Per-user (optionally per-account) parameter overrides."""

    __tablename__ = "strategy_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("strategy_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    overrides: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    version: Mapped["StrategyVersionRecord"] = relationship(back_populates="configs")
