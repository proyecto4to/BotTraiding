"""SQLAlchemy models for broker-connectors (P1: encrypted credentials).

The service had no persistence in Fase 3 (credentials lived in memory). This
adds a single table, `broker_credentials`, holding the API key/secret as a
Fernet-encrypted blob — plaintext secrets never touch the database, logs or
API responses. `demo` and timestamps are non-sensitive and stored in the
clear. Models are dialect-agnostic (String/Text/Boolean/DateTime) so the same
definitions back Postgres (docker, via Alembic
`version_table="alembic_version_broker"`) and local SQLite (create_all).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class BrokerCredentialRow(Base):
    """One encrypted credential set per (broker, account_id).

    `encrypted_blob` is a Fernet token over the JSON {api_key, api_secret,
    extra}. Rotating the encryption key re-encrypts this column in place and
    bumps `rotated_at`."""

    __tablename__ = "broker_credentials"
    __table_args__ = (
        UniqueConstraint("broker", "account_id", name="uq_broker_credentials_broker_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    broker: Mapped[str] = mapped_column(String(50), nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    encrypted_blob: Mapped[str] = mapped_column(Text, nullable=False)
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
