"""Runtime configuration for market-data (P2).

Read from the environment at call time so tests monkeypatch per case.

Env vars:
- REDIS_URL: optional; when set (and reachable) the bar cache is Redis-backed
  and shared across replicas, otherwise it falls back to an in-process cache.
- BROKER_CONNECTORS_URL: upstream for historical klines
  (GET /connectors/{broker}/historical).
- MARKET_DATA_DEFAULT_BROKER: broker used when a request omits it (default binance).
- MARKET_DATA_POLL_INTERVAL: seconds between background refreshes of every
  subscription (default 15). One fetch per (broker, symbol, timeframe) serves
  all bots — this is what protects the broker's rate limit.
- MARKET_DATA_MAX_BARS: bars kept per series (default 500).
- MARKET_DATA_CACHE_TTL: cache entry TTL in seconds (default 120).
- MARKET_DATA_SOURCE_TIMEOUT: HTTP timeout towards broker-connectors (default 10).
- MARKET_DATA_AUTOSTART_POLLER: start the background poller on app startup
  (default true; tests disable it to drive refreshes deterministically).
"""

from __future__ import annotations

import os


def redis_url() -> str | None:
    return os.environ.get("REDIS_URL") or None


def broker_connectors_url() -> str:
    return os.environ.get(
        "BROKER_CONNECTORS_URL", "http://broker-connectors:8000"
    ).rstrip("/")


def default_broker() -> str:
    return os.environ.get("MARKET_DATA_DEFAULT_BROKER", "binance")


def poll_interval() -> float:
    return float(os.environ.get("MARKET_DATA_POLL_INTERVAL", "15"))


def max_bars() -> int:
    return int(os.environ.get("MARKET_DATA_MAX_BARS", "500"))


def cache_ttl() -> int:
    return int(os.environ.get("MARKET_DATA_CACHE_TTL", "120"))


def source_timeout() -> float:
    return float(os.environ.get("MARKET_DATA_SOURCE_TIMEOUT", "10"))


def autostart_poller() -> bool:
    return os.environ.get("MARKET_DATA_AUTOSTART_POLLER", "true").lower() in (
        "1",
        "true",
        "yes",
    )
