"""Poller: one fetch per subscription warms the shared cache; errors recorded."""

from __future__ import annotations

import pytest

from app.cache import cache_key


async def test_refresh_once_warms_cache_one_fetch_per_sub(poller, source, cache, registry):
    registry.add("binance", "BTCUSD", "1h")
    registry.add("binance", "ETHUSD", "4h")

    refreshed, errors = await poller.refresh_once()

    assert (refreshed, errors) == (2, 0)
    assert len(source.calls) == 2  # exactly one fetch per subscription
    assert await cache.get(cache_key("binance", "BTCUSD", "1h")) is not None
    assert await cache.get(cache_key("binance", "ETHUSD", "4h")) is not None

    btc = registry.get("binance", "BTCUSD", "1h")
    assert btc.bar_count == 1 and btc.last_refresh is not None and btc.last_error is None


async def test_refresh_records_error_and_keeps_going(poller, source, registry):
    registry.add("binance", "BTCUSD", "1h")
    source.fail = True

    refreshed, errors = await poller.refresh_once()

    assert (refreshed, errors) == (0, 1)
    status = registry.get("binance", "BTCUSD", "1h")
    assert status.last_error is not None and status.last_refresh is None


def test_registry_add_is_idempotent_and_remove(registry):
    registry.add("binance", "BTCUSD", "1h")
    registry.add("binance", "BTCUSD", "1h")
    assert len(registry.all()) == 1

    assert registry.remove("binance", "BTCUSD", "1h") is True
    assert registry.remove("binance", "BTCUSD", "1h") is False
    assert registry.all() == []
