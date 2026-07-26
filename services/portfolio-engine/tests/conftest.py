"""Shared pytest fixtures: an in-memory SQLite DB wired into app.db, so the
full test suite runs without a real Postgres instance (auth-service pattern)."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("DEFAULT_STARTING_CASH", "100000")
# Signing key for the service tokens the state-mutating endpoints now require.
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app import portfolio
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
    portfolio.reset_memory_state()

    yield

    portfolio.reset_memory_state()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    """Speaks as execution-engine does: the ingest/mark endpoints reject
    unauthenticated callers. `anon_client` covers the rejection itself."""
    from fastapi.testclient import TestClient

    from app.main import app
    from trading_contracts.auth import service_auth_header

    return TestClient(app, headers=service_auth_header("execution-engine"))


@pytest.fixture()
def anon_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
