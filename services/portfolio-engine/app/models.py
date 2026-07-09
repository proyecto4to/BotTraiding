"""SQLAlchemy models for portfolio-engine (Fase 7).

Column shapes mirror infra/docker/init.sql `positions` and `executions`
where relevant (quantity, average_price, unrealized_pnl, filled_quantity,
average_fill_price, raw, reported_at). Table names are prefixed with
`portfolio_` because init.sql already creates `positions`/`executions`
keyed by `symbol_id UUID REFERENCES symbols(id)` in the shared Fase 1
Postgres instance; portfolio-engine has no symbol registry to resolve those
FKs, so it owns its own string-keyed tables instead (see report).
Migrations live in services/portfolio-engine/alembic/ with
version_table="alembic_version_portfolio".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class PortfolioAccount(Base):
    """Per-account cash / realized PnL / peak-equity tracking."""

    __tablename__ = "portfolio_accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PortfolioPosition(Base):
    """Mirrors init.sql `positions` columns (quantity/average_price/
    unrealized_pnl/updated_at) with string symbol + extra mark/sector
    columns portfolio-engine needs."""

    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_portfolio_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("portfolio_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PortfolioExecution(Base):
    """Mirrors init.sql `executions` columns (status/filled_quantity/
    average_fill_price/raw/reported_at) plus the symbol/side context the
    shared ExecutionReport contract does not carry."""

    __tablename__ = "portfolio_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("portfolio_accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
