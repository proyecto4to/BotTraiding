"""SQLAlchemy models for risk-engine (Fase 7).

`risk_engine_limits` mirrors infra/docker/init.sql `risk_limits` column-for-
column (the ten numeric limits + circuit_breaker_thresholds JSONB) but is a
service-owned table: init.sql's `risk_limits` FKs account_id to
`broker_accounts(id)`, which risk-engine cannot satisfy in Fase 7 (no
account registry), and init.sql is read-only. Extra service-specific limits
(liquidity/slippage/volatility/total exposure) live in the `extra_limits`
JSON column so the contract columns stay exactly aligned with init.sql.

`risk_events` (audit trail of every rejection/halt) and `circuit_breakers`
(per-account breaker state machine) are risk-engine-owned tables.
Migrations use version_table="alembic_version_risk".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class RiskLimitsRow(Base):
    __tablename__ = "risk_engine_limits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    max_risk_per_trade: Mapped[float] = mapped_column(Float, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_weekly_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_monthly_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    max_floating_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    max_leverage: Mapped[float] = mapped_column(Float, nullable=False)
    max_correlation: Mapped[float] = mapped_column(Float, nullable=False)
    max_exposure_per_symbol: Mapped[float] = mapped_column(Float, nullable=False)
    max_exposure_per_sector: Mapped[float] = mapped_column(Float, nullable=False)
    circuit_breaker_thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extra_limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CircuitBreakerRow(Base):
    __tablename__ = "circuit_breakers"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
