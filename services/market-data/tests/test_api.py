"""API: subscription lifecycle and cache-vs-upstream read semantics."""

from __future__ import annotations


def test_subscribe_warms_cache_then_reads_are_cached(client, source):
    resp = client.post(
        "/subscriptions", json={"broker": "binance", "symbol": "BTCUSD", "timeframe": "1h"}
    )
    assert resp.status_code == 201
    assert resp.json()["bar_count"] == 1
    assert len(source.calls) == 1  # subscribe triggered one warm-up fetch

    read = client.get("/market-data/BTCUSD", params={"timeframe": "1h"})
    assert read.status_code == 200
    body = read.json()
    assert body["source"] == "cache"
    assert body["count"] == 1
    # No extra upstream call: the bot read from the shared cache.
    assert len(source.calls) == 1


def test_uncached_read_fetches_upstream_once_then_caches(client, source):
    first = client.get("/market-data/ETHUSD", params={"broker": "binance", "timeframe": "1h"})
    assert first.status_code == 200
    assert first.json()["source"] == "upstream"
    assert len(source.calls) == 1

    second = client.get("/market-data/ETHUSD", params={"broker": "binance", "timeframe": "1h"})
    assert second.json()["source"] == "cache"
    assert len(source.calls) == 1  # served from cache, no second fetch


def test_read_upstream_error_is_502(client, source):
    source.fail = True
    resp = client.get("/market-data/DOGEUSD", params={"timeframe": "1h"})
    assert resp.status_code == 502


def test_list_and_remove_subscription(client):
    client.post(
        "/subscriptions", json={"broker": "binance", "symbol": "BTCUSD", "timeframe": "1h"}
    )
    listed = client.get("/subscriptions").json()
    assert len(listed) == 1 and listed[0]["symbol"] == "BTCUSD"

    removed = client.request(
        "DELETE",
        "/subscriptions",
        json={"broker": "binance", "symbol": "BTCUSD", "timeframe": "1h"},
    )
    assert removed.status_code == 200
    assert client.get("/subscriptions").json() == []

    missing = client.request(
        "DELETE",
        "/subscriptions",
        json={"broker": "binance", "symbol": "NONE", "timeframe": "1h"},
    )
    assert missing.status_code == 404


def test_refresh_all_endpoint(client, registry, source):
    registry.add("binance", "BTCUSD", "1h")
    registry.add("binance", "ETHUSD", "1h")
    resp = client.post("/subscriptions/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"refreshed": 2, "errors": 0}
