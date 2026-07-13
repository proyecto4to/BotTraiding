"""Fixtures: in-memory SQLite wired into app.db, fake downstream clients, and
admin/non-admin JWT builders. No network, no real Postgres."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)

import pytest
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.clients import Clients, DownstreamError
from app.models import Base


@pytest.fixture(autouse=True)
def _test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db_module.engine = engine
    db_module.SessionLocal = TestSession
    yield
    Base.metadata.drop_all(engine)


def _bar(i: float) -> dict:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "open": 100 + i,
        "high": 101 + i,
        "low": 99 + i,
        "close": 100 + i,
        "volume": 10.0,
        "timestamp": "2026-01-01T00:00:00Z",
    }


class FakeMarketData:
    def __init__(self, n_bars: int = 5) -> None:
        self.bars = [_bar(i) for i in range(n_bars)]
        self.calls: list[tuple] = []
        self.fail = False

    async def get_bars(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        if self.fail:
            raise DownstreamError("market-data down")
        return list(self.bars)


class FakeAi:
    def __init__(self, ranked=None, regime=None) -> None:
        self.regime_value = regime or {
            "trend": "up", "volatility": "normal", "confidence": 0.8
        }
        self.ranked_value = ranked if ranked is not None else [
            {"key": "sma_crossover", "category": "trend", "weight": 1.0}
        ]
        self.fail = False

    async def regime(self, bars):
        if self.fail:
            raise DownstreamError("ai down")
        return self.regime_value

    async def select(self, regime, market, timeframe, performance):
        return list(self.ranked_value)


class FakeTrading:
    def __init__(self) -> None:
        self.bots: list[dict] = []
        self._id = 0
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.created: list[str] = []
        self.fail_list = False

    async def list_bots(self, account_id):
        if self.fail_list:
            raise DownstreamError("trading-engine down")
        return [dict(b) for b in self.bots]

    async def create_bot(self, spec):
        self._id += 1
        bot = {"id": f"bot-{self._id}", "name": spec["name"], "status": "stopped"}
        self.bots.append(bot)
        self.created.append(spec["name"])
        return bot

    async def start_bot(self, bot_id):
        self.started.append(bot_id)
        for b in self.bots:
            if b["id"] == bot_id:
                b["status"] = "running"

    async def stop_bot(self, bot_id):
        self.stopped.append(bot_id)
        for b in self.bots:
            if b["id"] == bot_id:
                b["status"] = "stopped"


class FakePortfolio:
    """Aggregate risk snapshot for the global risk guard (P9)."""

    def __init__(self, drawdown=0.0, pnl_daily=0.0, equity=100000.0) -> None:
        self.drawdown = drawdown
        self.pnl_daily = pnl_daily
        self.equity = equity
        self.fail = False

    async def get_state(self, account_id):
        if self.fail:
            raise DownstreamError("portfolio down")
        return {
            "account": {"equity": self.equity},
            "drawdown": {"current_drawdown": self.drawdown},
            "pnl_daily": self.pnl_daily,
        }


class FakeClients(Clients):
    def __init__(self) -> None:
        super().__init__(FakeMarketData(), FakeAi(), FakeTrading(), FakePortfolio())


@pytest.fixture()
def fake_clients():
    return FakeClients()


def make_token(roles, token_type="access"):
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


@pytest.fixture()
def client(fake_clients):
    from fastapi.testclient import TestClient

    from app.clients import get_clients
    from app.main import app

    app.dependency_overrides[get_clients] = lambda: fake_clients
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
