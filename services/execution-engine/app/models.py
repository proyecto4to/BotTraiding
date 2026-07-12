"""SQLAlchemy models for execution-engine (Fases 9/10).

`executions` is the parent record of one approved Order submitted for
execution (with its RiskDecision context frozen in for audit),
`execution_child_orders` are the sequentially executed slices produced by
order splitting, and `execution_reports` persists every ExecutionReport a
transport produced (also forwarded to portfolio-engine and published on the
event bus). Migrations use version_table="alembic_version_execution".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ExecutionRow(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # RiskDecision context frozen at submission time (auditability invariant).
    risk_decision: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChildOrderRow(Base):
    __tablename__ = "execution_child_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id"), nullable=False, index=True
    )
    # Deterministic idempotency key sent to the venue (Binance clientOrderId /
    # paper order id): uuid5(namespace, f"{execution_id}:{sequence}"), persisted
    # BEFORE any transport attempt so retries always reuse the same id.
    client_order_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, unique=True, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ExecutionReportRow(Base):
    __tablename__ = "execution_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("executions.id"), nullable=False, index=True
    )
    child_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    report_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # The idempotency key of the child order this report belongs to; forwarded
    # to portfolio-engine so ingestion can dedupe on it.
    client_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    forwarded_to_portfolio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
