"""Shared pytest fixtures: in-memory SQLite wired into app.db, logging
event publisher, and clean client-injection seams per test. The
BacktesterClient is ALWAYS faked here - backtester code is never
imported (it is a separate service reached over REST in production)."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)
os.environ.pop("PROMOTION_THRESHOLD", None)
os.environ.pop("MAX_DRAWDOWN_TOLERANCE", None)

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import clients, db as db_module, events
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
def _reset_seams():
    events.set_publisher(None)
    clients.set_backtester(None)
    clients.set_strategy_engine(None)
    yield
    events.set_publisher(None)
    clients.set_backtester(None)
    clients.set_strategy_engine(None)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
