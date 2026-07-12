"""Shared token-bucket rate limiter reused by every broker connector.

One instance per (broker, account) is enough - each connector owns its own
bucket sized from ``app/broker_limits.py`` so brokers with different real
limits don't share state.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucketRateLimiter:
    """Async token-bucket: allows bursts up to ``capacity``, then throttles
    to ``refill_per_second`` sustained rate."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block (async) until ``tokens`` are available, then consume them.

        ``tokens`` doubles as a request *weight*: brokers that meter by
        request-weight instead of request-count (e.g. Binance's 1200
        weight/min) pass each endpoint's documented weight here so the
        bucket tracks the real budget.
        """
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait_seconds = deficit / self.refill_per_second
                await asyncio.sleep(wait_seconds)

    def drain(self) -> None:
        """Empty the bucket immediately.

        Called when the broker signals rate limiting (HTTP 429/418) so that
        subsequent ``acquire()`` calls wait for a real refill instead of
        burning through locally-remaining burst capacity while the broker is
        already throttling us.
        """
        self._refill()
        self._tokens = 0.0

    def available_tokens(self) -> float:
        """Non-blocking read of the current bucket level (for tests/diagnostics)."""
        self._refill()
        return self._tokens
