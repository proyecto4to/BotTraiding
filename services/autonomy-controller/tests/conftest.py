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
from app import db as db_module
from app.clients import Clients, DownstreamError
from app.models import Base
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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
        self.recommendations_value: list[dict] = []
        self.fail = False
        self.fail_recommendations = False

    async def regime(self, bars):
        if self.fail:
            raise DownstreamError("ai down")
        return self.regime_value

    async def select(self, regime, market, timeframe, performance):
        return list(self.ranked_value)

    async def recommendations(self, limit=100):
        if self.fail_recommendations:
            raise DownstreamError("ai down")
        return [dict(r) for r in self.recommendations_value[:limit]]


class FakeTrading:
    def __init__(self) -> None:
        self.bots: list[dict] = []
        self._id = 0
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.created: list[str] = []
        self.specs: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.fail_list = False

    async def list_bots(self, account_id):
        if self.fail_list:
            raise DownstreamError("trading-engine down")
        return [dict(b) for b in self.bots]

    async def create_bot(self, spec):
        self._id += 1
        bot = {
            "id": f"bot-{self._id}",
            "name": spec["name"],
            "status": "stopped",
            "risk_allocation": spec.get("risk_allocation"),
        }
        self.bots.append(bot)
        self.created.append(spec["name"])
        self.specs.append(spec)
        return bot

    async def update_bot(self, bot_id, patch):
        self.updated.append((bot_id, patch))
        for b in self.bots:
            if b["id"] == bot_id:
                b.update(patch)
                return dict(b)
        return {}

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
    """Aggregate risk snapshot for the risk guard (P9) and promotion gates (P18)."""

    def __init__(
        self,
        drawdown=0.0,
        pnl_daily=0.0,
        equity=100000.0,
        realized=0.0,
        unrealized=0.0,
        max_drawdown=None,
        closed_trades=100,
        trade_sharpe=1.0,
    ) -> None:
        self.drawdown = drawdown
        self.pnl_daily = pnl_daily
        self.equity = equity
        self.realized = realized
        self.unrealized = unrealized
        # Worst drawdown of the period; defaults to the current one so a test
        # that only sets `drawdown` still describes one coherent account.
        self.max_drawdown = max_drawdown
        # Comfortably above the min_closed_trades gate by default, so a test is
        # never accidentally measuring that gate; lower it to exercise it.
        self.closed_trades = closed_trades
        # Per-trade Sharpe, comfortably above the default gate; set to None to
        # exercise the "metric unavailable => fail closed" path.
        self.trade_sharpe = trade_sharpe
        self.fail = False

    async def get_state(self, account_id):
        if self.fail:
            raise DownstreamError("portfolio down")
        worst = self.max_drawdown if self.max_drawdown is not None else self.drawdown
        return {
            "account": {"equity": self.equity},
            "drawdown": {"current_drawdown": self.drawdown, "max_drawdown": worst},
            "pnl_daily": self.pnl_daily,
            "realized_pnl": self.realized,
            "unrealized_pnl": self.unrealized,
            "closed_trades": self.closed_trades,
            "trade_sharpe": self.trade_sharpe,
        }


class FakeStrategies:
    """Strategy catalog fake: key -> enabled, records every toggle."""

    def __init__(self) -> None:
        self.catalog: dict[str, bool] = {
            "sma_crossover": True,
            "rsi2_reversion": True,
        }
        self.toggled: list[tuple[str, bool]] = []
        self.list_calls = 0
        self.fail = False
        self.fail_toggle = False

    async def list_strategies(self):
        self.list_calls += 1
        if self.fail:
            raise DownstreamError("strategy-engine down")
        return [{"key": k, "enabled": v} for k, v in sorted(self.catalog.items())]

    async def set_enabled(self, strategy_key, enabled):
        if self.fail_toggle:
            raise DownstreamError("strategy-engine down")
        self.catalog[strategy_key] = enabled
        self.toggled.append((strategy_key, enabled))
        return {"key": strategy_key, "enabled": enabled}


class FakeClients(Clients):
    def __init__(self) -> None:
        super().__init__(
            FakeMarketData(), FakeAi(), FakeTrading(), FakePortfolio(),
            FakeStrategies(),
        )


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
def service_headers():
    """How the scheduler calls /autonomy/tick: an authenticated machine, with
    no admin rights (the operator controls stay admin-only)."""
    from trading_contracts.auth import service_auth_header

    return service_auth_header("scheduler")


@pytest.fixture()
def client(fake_clients):
    from app.clients import get_clients
    from app.main import app
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_clients] = lambda: fake_clients
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
