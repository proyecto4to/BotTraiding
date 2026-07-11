"""Database engine/session wiring for auth-service.

DATABASE_URL defaults to the Fase 1 docker-compose postgres instance. Tests
override it (see tests/conftest.py) to an in-memory SQLite database so no
running Postgres is required to run the test suite.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///C:/Users/Dell Vostro/OneDrive/Documentos/GitHub/BotTraiding/.local/auth-service.db",
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

if DATABASE_URL.startswith("sqlite"):
    db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

from app.models import Base

Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
