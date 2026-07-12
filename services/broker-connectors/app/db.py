"""Database engine/session wiring for broker-connectors (P1).

Only used when CREDENTIAL_STORE=db (the default store is still the in-memory
one, so tests and Fase 3 behaviour are unchanged). DATABASE_URL defaults to
the docker-compose Postgres; local dev points it at a SQLite file and the
tables are created via Base.metadata.create_all (Alembic migrations use
Postgres types under version_table="alembic_version_broker").
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@postgres:5432/trading"
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

if DATABASE_URL.startswith("sqlite:///"):
    _db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    if str(_db_path) not in ("", ":memory:"):
        _db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def create_all() -> None:
    """Create the credential table for local/SQLite dev (Postgres uses Alembic)."""
    from app.models import Base

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
