"""SQLAlchemy models for the gateway (Fase 4 - Mercados).

Mirrors infra/docker/init.sql's `markets` and `symbols` tables and extends
them with the columns Fase 4 needs (code, asset_class, enabled,
trading_hours on markets; name, is_active on symbols). It also adds a
gateway-owned `user_market_settings` table for per-user market activation.
The Alembic migration (services/gateway/alembic/) applies the schema changes
against the shared Postgres instance without touching init.sql.

`user_market_settings.user_id` intentionally has NO foreign key to `users`:
the users table is owned by auth-service and may be migrated in any order
relative to the gateway (each service migrates independently with its own
alembic version table).
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Market(Base):
    """A market category (stocks, forex, crypto...) that can be switched
    on/off globally by an admin without any code change."""

    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trading_hours: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    symbols: Mapped[list["Symbol"]] = relationship(
        back_populates="market", cascade="all, delete-orphan"
    )


class Symbol(Base):
    """A tradable instrument belonging to exactly one market."""

    __tablename__ = "symbols"
    __table_args__ = (UniqueConstraint("market_id", "ticker"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    market_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("markets.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    market: Mapped["Market"] = relationship(back_populates="symbols")


class UserMarketSetting(Base):
    """Per-user market activation: a user can opt out of a globally-enabled
    market. Missing row == the user follows the market's global flag."""

    __tablename__ = "user_market_settings"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    market_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("markets.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    market: Mapped["Market"] = relationship()
