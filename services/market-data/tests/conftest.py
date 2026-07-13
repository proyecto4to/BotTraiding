"""Shared fixtures: bar builders, a fake upstream source, a fake async Redis
client, and a TestClient whose app.state is swapped for in-memory test doubles
(no network, no real Redis)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.cache import InMemoryBarCache
from app.poller import MarketDataPoller, SubscriptionRegistry
from app.source import MarketDataSource, MarketDataSourceError
from trading_contracts import Bar


def make_bar(symbol="BTCUSD", timeframe="1h", close=100.0, ts=None) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=10.0,
        timestamp=ts or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class FakeSource(MarketDataSource):
    """Records calls; returns scripted bars or raises."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []
        self.bars_by_key: dict[tuple[str, str, str], list[Bar]] = {}
        self.fail = False

    async def fetch(self, broker, symbol, timeframe, limit):
        self.calls.append((broker, symbol, timeframe, limit))
        if self.fail:
            raise MarketDataSourceError("upstream boom")
        return list(
            self.bars_by_key.get(
                (broker, symbol, timeframe), [make_bar(symbol, timeframe)]
            )
        )


class FakeRedis:
    """Minimal async redis stand-in for RedisBarCache tests."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def keys(self, pattern="*"):
        return [k for k in self.store if k.startswith("bars:")]

    async def ping(self):
        return True


@pytest.fixture()
def source():
    return FakeSource()


@pytest.fixture()
def cache():
    return InMemoryBarCache()


@pytest.fixture()
def registry():
    return SubscriptionRegistry()


@pytest.fixture()
def poller(source, cache, registry):
    return MarketDataPoller(
        source, cache, registry, interval=0.01, max_bars=10, ttl=60
    )


@pytest.fixture()
def client(monkeypatch, source, cache, registry, poller):
    """TestClient with app.state swapped for the in-memory doubles above.

    The endpoint dependencies read app.state per request, so replacing it after
    startup wires every route to the fakes. The poller does not auto-start."""
    monkeypatch.setenv("MARKET_DATA_AUTOSTART_POLLER", "false")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        app.state.cache = cache
        app.state.source = source
        app.state.registry = registry
        app.state.poller = poller
        yield test_client
