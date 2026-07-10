"""SQLAlchemy models for ai-engine (Fase 11).

One table, owned by this service's own Alembic migration
(version_table "alembic_version_ai", never editing init.sql):
`ai_recommendations` persists every recommendation the AI engine emits
(e.g. "disable strategy X"). The AI engine NEVER acts on them itself -
consumers (strategy-engine operators, the frontend, the scheduler) read
them via GET /ai/recommendations or the `ai.recommendation.created`
NATS event and decide what to do. La IA no sustituye las reglas de
trading (docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class RecommendationRecord(Base):
    """A persisted AI recommendation. Advisory only; never auto-applied."""

    __tablename__ = "ai_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    #: e.g. "disable" | "review" - what the consumer is advised to do.
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    #: machine-readable rule id, e.g. "rolling_sharpe_below_threshold".
    rule: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
