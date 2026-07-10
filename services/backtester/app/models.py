"""SQLAlchemy models for the backtester (Fase 8).

Column shapes mirror infra/docker/init.sql `backtest_runs` /
`backtest_results` where compatible (status, parameters, started_at,
finished_at; metrics, created_at, backtest_run_id FK). Table names are
prefixed `backtester_` because init.sql's `backtest_runs` is keyed by
`strategy_version_id UUID REFERENCES strategy_versions(id)`, a registry the
backtester does not own in Fase 8 - runs here are keyed by the registry
`strategy_key` string instead (same precedent as portfolio-engine's
prefixed tables). Migrations live in services/backtester/alembic/ with
version_table="alembic_version_backtester".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class BacktestRun(Base):
    """One backtest execution: inputs + lifecycle (init.sql-compatible
    status/parameters/started_at/finished_at columns)."""

    __tablename__ = "backtester_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    friction: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    data_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BacktestResult(Base):
    """Results of a completed run (init.sql-compatible metrics/created_at/
    backtest_run_id columns) plus the equity curve and trade list."""

    __tablename__ = "backtester_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    backtest_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("backtester_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    equity_curve: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    trades: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
