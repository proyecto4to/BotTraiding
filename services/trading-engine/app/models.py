"""SQLAlchemy models for trading-engine (Fase 16).

`trading_bots` is the bot registry: one row per configured bot (account,
broker, execution mode, symbols, strategies, cycle interval, status).
`trading_cycle_reports` is the audit trail: one row per orchestrator cycle
with the signals/decisions/orders/errors recorded during that cycle
(architecture principle 5: auditable by design).

Migrations use version_table="alembic_version_trading".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class BotRow(Base):
    __tablename__ = "trading_bots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    broker: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="paper")
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_keys: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    params_overrides: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Capital/risk allocation for this bot (P7): e.g.
    # {"capital_fraction": 0.6, "risk_per_trade": 0.006}. Set by the autonomy
    # controller from the AI weights; null for manually-created bots.
    risk_allocation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cycle_interval_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="stopped")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CycleReportRow(Base):
    __tablename__ = "trading_cycle_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trading_bots.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # ok|degraded|skipped|error
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    signals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decisions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    orders: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
