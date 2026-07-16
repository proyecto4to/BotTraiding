"""Shared fixtures: in-memory SQLite wired into app.db (auth-service
pattern), JWT builders and recording fake downstream clients so the
orchestrator cycle is testable without any network."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)  # events fall back to logging in tests
os.environ.pop("REDIS_URL", None)  # bot locks default to in-memory in tests
os.environ.pop("BOT_LOCK_BACKEND", None)

import pytest
from app import db as db_module
from app.clients import Clients, DownstreamError
from app.models import Base
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Env vars individual tests monkeypatch; scrub so config never leaks.
_ENV_VARS = [
    "BOT_MAX_CONSECUTIVE_ERRORS",
    "BOT_BAR_LOOKBACK",
    "TRADING_HTTP_TIMEOUT",
    "BOT_LOCK_BACKEND",
    "BOT_LOCK_TTL_SECONDS",
    "REDIS_URL",
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


@pytest.fixture()
def db_session():
    with db_module.SessionLocal() as session:
        yield session


# --- JWT helpers -------------------------------------------------------------


def make_token(roles: list[str], token_type: str = "access", sub: str | None = None) -> str:
    payload = {
        "sub": sub or str(uuid.uuid4()),
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


# --- synthetic market data ----------------------------------------------------


def make_bars(
    symbol: str = "BTCUSD",
    timeframe: str = "1h",
    closes: list[float] | None = None,
) -> list[dict[str, Any]]:
    closes = closes or [100.0 + i * 0.1 for i in range(50)]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, close in enumerate(closes):
        bars.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
                "timestamp": (start + timedelta(hours=i)).isoformat(),
            }
        )
    return bars


def make_signal(
    symbol: str = "BTCUSD",
    side: str = "buy",
    strategy_id: str = "sma_crossover",
    stop_loss: float | None = 98.0,
    metadata: dict | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "strategy_id": strategy_id,
        "symbol": symbol,
        "market": "crypto",
        "side": side,
        "confidence": 0.7,
        "timeframe": "1h",
        "suggested_size": 1.0,
        "stop_loss": stop_loss,
        "take_profit": 110.0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }


def make_decision(
    signal_id: str,
    approved: bool = True,
    max_size_allowed: float = 5.0,
    adjusted_stop: float | None = 98.5,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "approved": approved,
        "reason": reason or ("approved" if approved else "max_daily_loss breached"),
        "max_size_allowed": max_size_allowed,
        "adjusted_stop": adjusted_stop,
        "risk_checks_passed": ["per_trade_risk"] if approved else [],
        "risk_checks_failed": [] if approved else ["max_daily_loss"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "account_id": "acct-1",
        "circuit_breaker_state": "NORMAL",
    }


# --- recording fake clients ---------------------------------------------------


class FakeMarketData:
    """Returns preset bars per symbol; raises preset errors."""

    def __init__(self, bars_by_symbol: dict[str, list[dict]] | None = None) -> None:
        self.bars_by_symbol = bars_by_symbol or {}
        self.error: Optional[Exception] = None
        self.calls: list[tuple] = []

    async def get_bars(self, broker, symbol, timeframe, lookback=None, account_id="default"):
        self.calls.append((broker, symbol, timeframe))
        if self.error is not None:
            raise self.error
        return self.bars_by_symbol.get(symbol, make_bars(symbol=symbol))


class FakeStrategy:
    """signal_by_key: strategy_key -> signal dict | None | Exception."""

    def __init__(self, signal_by_key: dict[str, Any] | None = None) -> None:
        self.signal_by_key = signal_by_key or {}
        self.calls: list[dict] = []

    async def evaluate(self, strategy_key, bars, params=None, user_id=None,
                       account_id=None, market=None):
        self.calls.append(
            {"strategy_key": strategy_key, "params": params, "bars": len(bars)}
        )
        result = self.signal_by_key.get(strategy_key)
        if isinstance(result, Exception):
            raise result
        return result


class FakeRisk:
    """Configurable breaker state and per-signal decision behavior."""

    def __init__(
        self,
        breaker_state: str = "NORMAL",
        approved: bool = True,
        max_size_allowed: float = 5.0,
    ) -> None:
        self.breaker_state = breaker_state
        self.breaker_error: Optional[Exception] = None
        self.validate_error: Optional[Exception] = None
        self.approved = approved
        self.max_size_allowed = max_size_allowed
        self.breaker_calls: list[str] = []
        self.validate_calls: list[dict] = []

    async def get_circuit_breaker(self, account_id):
        self.breaker_calls.append(account_id)
        if self.breaker_error is not None:
            raise self.breaker_error
        return {"account_id": account_id, "state": self.breaker_state, "reason": "test"}

    async def validate(self, signal, account_id, risk_per_trade_override=None):
        self.validate_calls.append(
            {
                "signal": signal,
                "account_id": account_id,
                "risk_per_trade_override": risk_per_trade_override,
            }
        )
        if self.validate_error is not None:
            raise self.validate_error
        return make_decision(
            signal["id"], approved=self.approved, max_size_allowed=self.max_size_allowed
        )


class FakeExecution:
    """Records submitted orders; returns a filled ExecutionOut-like dict."""

    def __init__(self) -> None:
        self.error: Optional[Exception] = None
        self.submissions: list[dict] = []

    async def submit(self, order, risk_decision, market_price=None):
        self.submissions.append(
            {"order": order, "risk_decision": risk_decision, "market_price": market_price}
        )
        if self.error is not None:
            raise self.error
        return {
            "id": str(uuid.uuid4()),
            "order_id": order["id"],
            "status": "filled",
            "filled_quantity": order["quantity"],
            "average_fill_price": market_price or 100.0,
        }


class FakeClientsBundle:
    def __init__(self, market_data=None, strategy=None, risk=None, execution=None):
        self.market_data = market_data or FakeMarketData()
        self.strategy = strategy or FakeStrategy()
        self.risk = risk or FakeRisk()
        self.execution = execution or FakeExecution()


@pytest.fixture()
def fake_clients() -> Clients:
    return FakeClientsBundle()  # type: ignore[return-value]


def downstream_timeout(service: str = "strategy-engine") -> DownstreamError:
    return DownstreamError(service, "unreachable: timeout")


# --- bot helpers ---------------------------------------------------------------


def make_bot_payload(
    mode: str = "paper",
    symbols: list[str] | None = None,
    strategy_keys: list[str] | None = None,
    account_id: str = "acct-1",
    cycle_interval_seconds: float = 60.0,
) -> dict:
    return {
        "name": "test-bot",
        "account_id": account_id,
        "broker": "binance",
        "execution_mode": mode,
        "symbols": symbols or ["BTCUSD"],
        "timeframe": "1h",
        "strategy_keys": strategy_keys or ["sma_crossover"],
        "params_overrides": {},
        "cycle_interval_seconds": cycle_interval_seconds,
    }


@pytest.fixture()
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
