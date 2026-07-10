"""SQLAlchemy models for optimizer (Fase 12).

Mirrors infra/docker/init.sql's `optimization_runs`/`optimization_results`
where compatible, extended via this service's own Alembic migration
(version_table "alembic_version_optimizer", init.sql is never edited):

- init.sql keys runs by strategy_version_id (FK to strategy-engine's
  strategy_versions). Services never reach into each other's tables
  (docs/ARCHITECTURE.md, principle 1), so this service keys runs by the
  shared code-registry `strategy_key` and keeps the plugin version as a
  plain string for audit.
- runs additionally persist the walk-forward inputs and the promotion
  decision (Fase 12: nunca promover sin validacion out-of-sample).
- results keep init.sql's shape (parameters/metrics/out_of_sample) plus
  the walk-forward `window_index` and a `role` (candidate|baseline).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class OptimizationRunRecord(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    search_type: Mapped[str] = mapped_column(String(10), nullable=False, default="grid")
    budget: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    #: pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    search_space: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    baseline_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    best_params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    #: the OOS validation gate passed (a promotion was RECOMMENDED).
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: params were actually pushed to strategy-engine (only if the caller
    #: asked with promote=true AND the gate passed).
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: full PromotionDecision dump: promote, reasons, metrics, threshold.
    decision: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["OptimizationResultRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class OptimizationResultRecord(Base):
    __tablename__ = "optimization_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    optimization_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("optimization_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    out_of_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    window_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: candidate | baseline (current params evaluated on the same OOS data)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    run: Mapped["OptimizationRunRecord"] = relationship(back_populates="results")
