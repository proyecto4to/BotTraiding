"""Shared fixtures: in-memory SQLite wired into app.db (auth-service
pattern), fake transports/forwarder injected through FastAPI dependency
overrides, JWT builders and Order/RiskDecision payload builders."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)  # events fall back to logging in tests

import pytest
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.models import Base
from app.portfolio_client import get_portfolio_forwarder
from app.router import ExecutionRouter, get_router
from trading_contracts import ExecutionMode, ExecutionReport, Order, OrderStatus

# Env vars individual tests monkeypatch; scrub so config never leaks.
_ENV_VARS = [
    "EXECUTION_MODE",
    "EXECUTION_LIVE_ENABLED",
    "EXECUTION_MAX_CHILD_SIZE",
    "EXECUTION_RETRY_MAX_ATTEMPTS",
    "EXECUTION_RETRY_BASE_DELAY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ENV_VARS:
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


def full_fill(order: Order, market_price: float | None) -> ExecutionReport:
    """Default fake behavior: full fill at the market price."""
    return ExecutionReport(
        order_id=order.id,
        status=OrderStatus.FILLED,
        filled_quantity=order.quantity,
        average_fill_price=market_price or order.price or 100.0,
        broker="fake",
        reported_at=datetime.now(timezone.utc),
        raw={"commission": 0.0},
    )


class FakeTransport:
    """Recording in-memory ExecutionTransport."""

    def __init__(self, mode: ExecutionMode, behavior=None) -> None:
        self.mode = mode
        self.name = f"fake-{mode.value}"
        self.behavior = behavior or full_fill
        self.orders: list[tuple[Order, float | None]] = []
        self.cancels: list[str] = []

    async def place_order(self, order: Order, market_price: float | None) -> ExecutionReport:
        self.orders.append((order, market_price))
        result = self.behavior(order, market_price)
        if isinstance(result, Exception):
            raise result
        return result

    async def cancel_order(self, order_id: str, *, broker: str, account_id: str) -> bool:
        self.cancels.append(order_id)
        return True


class RecordingForwarder:
    """Recording portfolio-engine forwarder fake."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def forward(self, account_id: str, payload: dict) -> bool:
        self.calls.append((account_id, payload))
        return True


async def _no_sleep(_delay: float) -> None:
    return None


class Harness:
    def __init__(self, client, paper, live, forwarder):
        self.client = client
        self.paper = paper
        self.live = live
        self.forwarder = forwarder


@pytest.fixture()
def harness():
    """TestClient wired with fake transports (no sleeps) and a recording
    portfolio forwarder."""
    from fastapi.testclient import TestClient

    from app.main import app

    paper = FakeTransport(ExecutionMode.PAPER)
    live = FakeTransport(ExecutionMode.LIVE)
    forwarder = RecordingForwarder()

    app.dependency_overrides[get_router] = lambda: ExecutionRouter(
        {ExecutionMode.PAPER: paper, ExecutionMode.LIVE: live},
        max_attempts=3,
        base_delay=0.0,
        max_delay=0.0,
        jitter=0.0,
        sleep=_no_sleep,
    )
    app.dependency_overrides[get_portfolio_forwarder] = lambda: forwarder

    with TestClient(app) as client:
        yield Harness(client, paper, live, forwarder)

    app.dependency_overrides.clear()


@pytest.fixture()
def client(harness):
    return harness.client


def make_token(roles: list[str], token_type: str = "access") -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "roles": roles,
        "type": token_type,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.fixture()
def admin_headers():
    return {"Authorization": f"Bearer {make_token(['admin'])}"}


@pytest.fixture()
def trader_headers():
    return {"Authorization": f"Bearer {make_token(['trader'])}"}


def make_execution_payload(
    mode: str = "paper",
    quantity: float = 10.0,
    market_price: float | None = 100.0,
    account_id: str = "acct-1",
    approved: bool = True,
    signal_id: str | None = None,
    decision_signal_id: str | None = None,
    symbol: str = "BTCUSD",
) -> dict:
    signal_id = signal_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "order": {
            "id": str(uuid.uuid4()),
            "signal_id": signal_id,
            "symbol": symbol,
            "side": "buy",
            "quantity": quantity,
            "order_type": "market",
            "price": None,
            "status": "pending",
            "broker": "binance",
            "account_id": account_id,
            "execution_mode": mode,
            "created_at": now,
        },
        "risk_decision": {
            "signal_id": decision_signal_id or signal_id,
            "approved": approved,
            "reason": "within limits" if approved else "max_daily_loss breached",
            "max_size_allowed": quantity,
            "risk_checks_passed": ["max_risk_per_trade"],
            "risk_checks_failed": [] if approved else ["max_daily_loss"],
            "decided_at": now,
        },
    }
    if market_price is not None:
        payload["market_price"] = market_price
    return payload
