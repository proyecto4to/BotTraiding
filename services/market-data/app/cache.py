"""Bar cache: Redis-backed when available, in-process otherwise.

The cache is the fan-out point of P2: the background poller writes each
(broker, symbol, timeframe) series once, and every bot reads it from here
instead of hitting the broker. A Redis backend additionally shares the cache
across replicas; without Redis a per-process dict is used (single-instance
dev, or a graceful degrade when Redis is down).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Protocol

from trading_contracts import Bar

logger = logging.getLogger("market-data.cache")


def cache_key(broker: str, symbol: str, timeframe: str) -> str:
    return f"bars:{broker}:{symbol}:{timeframe}"


def _dump(bars: list[Bar]) -> str:
    return json.dumps([b.model_dump(mode="json") for b in bars])


def _load(blob: str) -> list[Bar]:
    return [Bar.model_validate(item) for item in json.loads(blob)]


class BarCache(Protocol):
    async def get(self, key: str) -> list[Bar] | None: ...
    async def set(self, key: str, bars: list[Bar], ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def keys(self) -> list[str]: ...


class InMemoryBarCache:
    """Per-process cache with TTL expiry. Always available."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, list[Bar]]] = {}

    async def get(self, key: str) -> list[Bar] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, bars = entry
        if expires_at and expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return list(bars)

    async def set(self, key: str, bars: list[Bar], ttl: int) -> None:
        expires_at = time.monotonic() + ttl if ttl > 0 else 0.0
        self._data[key] = (expires_at, list(bars))

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self) -> list[str]:
        return list(self._data.keys())


class RedisBarCache:
    """Redis-backed cache. Serialises bar lists to JSON under a string key.

    Takes an injected async client (redis.asyncio-compatible) so tests can
    supply a fake. Any client error degrades to a miss/no-op and is logged —
    market-data must keep serving even if Redis blips.
    """

    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> list[Bar] | None:
        try:
            blob = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 - Redis outage must not break reads
            logger.warning("redis get failed (%s); treating as miss", exc)
            return None
        if blob is None:
            return None
        if isinstance(blob, bytes):
            blob = blob.decode()
        try:
            return _load(blob)
        except (ValueError, TypeError) as exc:
            logger.warning("corrupt cache entry %s (%s); dropping", key, exc)
            return None

    async def set(self, key: str, bars: list[Bar], ttl: int) -> None:
        try:
            if ttl > 0:
                await self._client.set(key, _dump(bars), ex=ttl)
            else:
                await self._client.set(key, _dump(bars))
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis set failed (%s); cache not updated", exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis delete failed (%s)", exc)

    async def keys(self) -> list[str]:
        try:
            found = await self._client.keys("bars:*")
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis keys failed (%s)", exc)
            return []
        return [k.decode() if isinstance(k, bytes) else k for k in found]


async def build_cache(url: str | None) -> BarCache:
    """Return a Redis cache when REDIS_URL is set and reachable, else in-memory."""
    if not url:
        return InMemoryBarCache()
    try:
        import redis.asyncio as redis  # type: ignore

        client = redis.from_url(url)
        await client.ping()
        logger.info("market-data cache: redis at %s", url)
        return RedisBarCache(client)
    except Exception as exc:  # noqa: BLE001 - ImportError / connection refused / ...
        logger.warning(
            "redis unavailable (%s); using in-process bar cache", exc
        )
        return InMemoryBarCache()
