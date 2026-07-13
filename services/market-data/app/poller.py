"""Background poller: one upstream fetch per subscription, shared by all bots.

The registry holds the set of (broker, symbol, timeframe) tuples other
services care about. ``refresh_once`` fetches each once from the source and
writes it to the cache; ``run`` loops that on an interval. Because reads are
served from the cache, N bots watching BTCUSD/1h cost one broker request per
interval, not N — this is the rate-limit protection P2 exists for.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from . import config
from .cache import BarCache, cache_key
from .schemas import SubscriptionStatus
from .source import MarketDataSource, MarketDataSourceError

logger = logging.getLogger("market-data.poller")


class SubscriptionRegistry:
    def __init__(self) -> None:
        self._status: dict[tuple[str, str, str], SubscriptionStatus] = {}

    def add(self, broker: str, symbol: str, timeframe: str) -> SubscriptionStatus:
        key = (broker, symbol, timeframe)
        if key not in self._status:
            self._status[key] = SubscriptionStatus(
                broker=broker, symbol=symbol, timeframe=timeframe
            )
        return self._status[key]

    def remove(self, broker: str, symbol: str, timeframe: str) -> bool:
        return self._status.pop((broker, symbol, timeframe), None) is not None

    def all(self) -> list[SubscriptionStatus]:
        return list(self._status.values())

    def get(self, broker: str, symbol: str, timeframe: str) -> SubscriptionStatus | None:
        return self._status.get((broker, symbol, timeframe))


class MarketDataPoller:
    def __init__(
        self,
        source: MarketDataSource,
        cache: BarCache,
        registry: SubscriptionRegistry,
        *,
        interval: float | None = None,
        max_bars: int | None = None,
        ttl: int | None = None,
    ) -> None:
        self._source = source
        self._cache = cache
        self._registry = registry
        self._interval = interval if interval is not None else config.poll_interval()
        self._max_bars = max_bars if max_bars is not None else config.max_bars()
        self._ttl = ttl if ttl is not None else config.cache_ttl()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def refresh_one(self, status: SubscriptionStatus) -> bool:
        """Fetch one series from upstream and cache it. Returns success."""
        try:
            bars = await self._source.fetch(
                status.broker, status.symbol, status.timeframe, self._max_bars
            )
        except MarketDataSourceError as exc:
            status.last_error = str(exc)
            logger.warning(
                "refresh failed for %s/%s/%s: %s",
                status.broker, status.symbol, status.timeframe, exc,
            )
            return False
        await self._cache.set(
            cache_key(status.broker, status.symbol, status.timeframe),
            bars,
            self._ttl,
        )
        status.bar_count = len(bars)
        status.last_refresh = datetime.now(timezone.utc)
        status.last_error = None
        return True

    async def refresh_once(self) -> tuple[int, int]:
        """Refresh every subscription once. Returns (refreshed, errors)."""
        refreshed = errors = 0
        for status in self._registry.all():
            if await self.refresh_one(status):
                refreshed += 1
            else:
                errors += 1
        return refreshed, errors

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.refresh_once()
            except Exception:  # noqa: BLE001 - a poll cycle must never kill the loop
                logger.exception("poll cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
