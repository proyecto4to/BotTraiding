"""Shared fixtures: in-memory SQLite wired into app.db (auth-service
pattern) plus helpers to create accounts and place simulated orders."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.models import Base

# Fill-model env vars that individual tests monkeypatch; scrub them so one
# test's configuration never leaks into another.
_FILL_ENV_VARS = [
    "PAPER_SPREAD_BPS",
    "PAPER_SLIPPAGE_BPS",
    "PAPER_SIZE_IMPACT_BPS_PER_UNIT",
    "PAPER_COMMISSION_BPS",
    "PAPER_COMMISSION_PER_UNIT",
    "PAPER_MAX_FILL_QUANTITY",
    "PAPER_LATENCY_MS",
    "PAPER_DEFAULT_STARTING_CASH",
    "PAPER_ALLOW_SHORT",
]


@pytest.fixture(autouse=True)
def _clean_fill_env(monkeypatch):
    for name in _FILL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


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


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def make_order_payload(
    account_id: str = "acct-1",
    symbol: str = "BTCUSD",
    side: str = "buy",
    quantity: float = 10.0,
    price: float = 100.0,
    order_id: str | None = None,
) -> dict:
    return {
        "order_id": order_id or str(uuid.uuid4()),
        "signal_id": str(uuid.uuid4()),
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_type": "market",
        "price": price,
    }


@pytest.fixture()
def account(client):
    """A paper account with 100,000 starting cash."""
    response = client.post(
        "/paper/accounts", json={"account_id": "acct-1", "starting_cash": 100_000.0}
    )
    assert response.status_code == 201, response.text
    return response.json()
