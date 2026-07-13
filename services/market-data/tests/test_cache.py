"""Cache backends: in-memory TTL semantics and the Redis wrapper round-trip."""

from __future__ import annotations

import time

import pytest

from app.cache import InMemoryBarCache, RedisBarCache, cache_key

from .conftest import FakeRedis, make_bar


def test_cache_key_shape():
    assert cache_key("binance", "BTCUSD", "1h") == "bars:binance:BTCUSD:1h"


async def test_in_memory_set_get_delete():
    cache = InMemoryBarCache()
    bars = [make_bar(close=100), make_bar(close=101)]
    await cache.set("bars:binance:BTCUSD:1h", bars, ttl=60)

    got = await cache.get("bars:binance:BTCUSD:1h")
    assert got is not None and len(got) == 2
    assert [b.close for b in got] == [100, 101]
    assert await cache.keys() == ["bars:binance:BTCUSD:1h"]

    await cache.delete("bars:binance:BTCUSD:1h")
    assert await cache.get("bars:binance:BTCUSD:1h") is None


async def test_in_memory_ttl_expiry(monkeypatch):
    cache = InMemoryBarCache()
    await cache.set("k", [make_bar()], ttl=1)

    base = time.monotonic()
    monkeypatch.setattr("app.cache.time.monotonic", lambda: base + 2)
    assert await cache.get("k") is None  # expired


async def test_in_memory_miss_returns_none():
    cache = InMemoryBarCache()
    assert await cache.get("nope") is None


async def test_redis_cache_roundtrip():
    cache = RedisBarCache(FakeRedis())
    bars = [make_bar(symbol="ETHUSD", close=50)]
    await cache.set("bars:binance:ETHUSD:1h", bars, ttl=60)

    got = await cache.get("bars:binance:ETHUSD:1h")
    assert got is not None and got[0].symbol == "ETHUSD" and got[0].close == 50
    assert await cache.keys() == ["bars:binance:ETHUSD:1h"]

    await cache.delete("bars:binance:ETHUSD:1h")
    assert await cache.get("bars:binance:ETHUSD:1h") is None


async def test_redis_cache_degrades_on_client_error():
    class BrokenRedis(FakeRedis):
        async def get(self, key):
            raise RuntimeError("connection reset")

    cache = RedisBarCache(BrokenRedis())
    # A Redis blip is a miss, not a crash.
    assert await cache.get("bars:binance:BTCUSD:1h") is None
