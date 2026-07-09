"""Per-caller rate limiting for proxied /api/* traffic.

Fase 4 ships an in-memory token bucket keyed by user id (or client IP for
unauthenticated auth endpoints). This is per-process only; the `RateLimiter`
protocol below is the seam for the future Redis-backed implementation
(ARCHITECTURE.md section 7 puts rate limiting state in Redis) -- swap it in
via `set_rate_limiter()` without touching the proxy code.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Protocol


class RateLimiter(Protocol):
    """Anything that can answer 'may this caller do one more request?'."""

    def allow(self, key: str) -> bool:  # pragma: no cover - protocol
        ...


class TokenBucketRateLimiter:
    """Classic token bucket: `capacity` burst, `refill_per_second` sustained."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.refill_per_second)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True
            self._buckets[key] = (tokens, now)
            return False

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def _limiter_from_env() -> TokenBucketRateLimiter:
    capacity = int(os.environ.get("RATE_LIMIT_CAPACITY", "60"))
    refill = float(os.environ.get("RATE_LIMIT_REFILL_PER_SECOND", "1.0"))
    return TokenBucketRateLimiter(capacity=capacity, refill_per_second=refill)


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = _limiter_from_env()
    return _rate_limiter


def set_rate_limiter(limiter: RateLimiter | None) -> None:
    """Swap the process-wide limiter (tests; future Redis-backed impl)."""
    global _rate_limiter
    _rate_limiter = limiter
