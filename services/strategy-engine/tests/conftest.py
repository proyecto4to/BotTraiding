"""Shared pytest fixtures: an in-memory SQLite DB wired into app.db, so the
full test suite runs without a real Postgres instance, and no NATS_URL so
the signal publisher always uses the logging fallback."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app import events
from app.models import Base


@pytest.fixture(autouse=True)
def _test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    db_module.engine = engine
    db_module.SessionLocal = TestSession

    yield

    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _reset_publisher():
    events.set_publisher(None)
    yield
    events.set_publisher(None)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    # Context manager runs the lifespan (registry -> DB sync on startup).
    with TestClient(app) as test_client:
        yield test_client
