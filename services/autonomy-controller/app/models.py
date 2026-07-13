"""SQLAlchemy models for autonomy-controller.

- AutonomyStateRow: single row holding the current state-machine state.
- AutonomyDecisionRow: an audit trail of every tick (regime, selection,
  actions taken, errors) so every automated decision is explainable.

Dialect-agnostic (Postgres via Alembic version_table="alembic_version_autonomy",
SQLite locally via create_all).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# The state machine is a singleton; this fixed id holds it.
STATE_SINGLETON_ID = "singleton"


class AutonomyStateRow(Base):
    __tablename__ = "autonomy_state"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default=STATE_SINGLETON_ID)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AutonomyDecisionRow(Base):
    __tablename__ = "autonomy_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    regime: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selection: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
