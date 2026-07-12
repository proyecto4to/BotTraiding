"""SQLAlchemy models for paper-trading (Fase 9).

Service-owned tables for the simulated broker: accounts (cash), positions
and orders. Migrations use version_table="alembic_version_paper" so this
service's Alembic history never collides with other services sharing the
same Postgres database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class PaperAccountRow(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    starting_cash: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PaperPositionRow(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_paper_position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PaperOrderRow(Base):
    __tablename__ = "paper_orders"

    # Caller-supplied order UUID (execution-engine child order id).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Caller idempotency key (execution-engine's deterministic child
    # client_order_id): duplicates replay the stored result, never re-fill.
    client_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="market")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    filled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    average_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_price: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    raw: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
