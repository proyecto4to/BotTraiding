"""Per-caller rate limiting for proxied /api/* traffic.

Two implementations satisfy the `RateLimiter` protocol:

- ``TokenBucketRateLimiter``: in-memory token bucket keyed by user id (or
  client IP for unauthenticated auth endpoints). Per-process only.
- ``RedisTokenBucketRateLimiter`` (P3): same token-bucket semantics with the
  bucket state in Redis, so every gateway replica enforces one shared limit
  per caller and restarts don't reset it (ARCHITECTURE.md section 7 puts rate
  limiting state in Redis).

Backend selection (``_limiter_from_env``):

- ``RATE_LIMIT_BACKEND=memory``: force the in-memory limiter.
- ``RATE_LIMIT_BACKEND=redis``: use Redis at ``REDIS_URL``.
- unset / ``auto``: Redis when ``REDIS_URL`` is set, in-memory otherwise.

If Redis is selected but unavailable (no URL, import error, connection
refused) the gateway logs a warning and degrades to the in-memory limiter --
it never fails to start. A Redis blip at request time falls back to a
per-process bucket for that call (fail-limited, not fail-open).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Protocol

logger = logging.getLogger("gateway.rate_limit")


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


class RedisTokenBucketRateLimiter:
    """Token bucket whose state lives in Redis: replicas share one budget.

    Each caller key maps to a Redis hash ``{prefix}{key}`` holding the token
    count and the last-refill wall-clock timestamp (wall clock, not monotonic,
    because the state is shared across processes). The read-refill-consume
    step runs inside an optimistic WATCH/MULTI transaction so two replicas
    can never spend the same token.

    Any Redis failure is logged and the decision is delegated to an embedded
    in-memory ``TokenBucketRateLimiter`` -- per-process limiting keeps
    working during a Redis outage instead of dropping to no limiting at all.
    """

    def __init__(
        self,
        client,
        capacity: int,
        refill_per_second: float,
        *,
        key_prefix: str = "ratelimit:",
        fallback: RateLimiter | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._client = client
        self._prefix = key_prefix
        self._fallback = fallback or TokenBucketRateLimiter(capacity, refill_per_second)
        # Expire idle buckets once they would have fully refilled anyway.
        if refill_per_second > 0:
            self._ttl = max(1, int(capacity / refill_per_second)) + 60
        else:
            self._ttl = 24 * 3600

    @staticmethod
    def _as_float(value, default: float) -> float:
        if value is None:
            return default
        if isinstance(value, bytes):
            value = value.decode()
        return float(value)

    def allow(self, key: str) -> bool:
        bucket_key = f"{self._prefix}{key}"
        now = time.time()

        def _consume(pipe) -> bool:
            raw = pipe.hgetall(bucket_key)
            data = {
                (k.decode() if isinstance(k, bytes) else k): v for k, v in (raw or {}).items()
            }
            tokens = self._as_float(data.get("tokens"), float(self.capacity))
            last = self._as_float(data.get("ts"), now)
            tokens = min(
                float(self.capacity), tokens + max(0.0, now - last) * self.refill_per_second
            )
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            pipe.multi()
            pipe.hset(bucket_key, mapping={"tokens": tokens, "ts": now})
            pipe.expire(bucket_key, self._ttl)
            return allowed

        try:
            return bool(
                self._client.transaction(_consume, bucket_key, value_from_callable=True)
            )
        except Exception as exc:  # noqa: BLE001 - a Redis blip must never 500 the gateway
            logger.warning("redis rate limiter failed (%s); using in-process fallback", exc)
            return self._fallback.allow(key)

    def reset(self) -> None:
        """Test helper: drop every bucket under this limiter's prefix."""
        try:
            keys = list(self._client.scan_iter(f"{self._prefix}*"))
            if keys:
                self._client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis rate limiter reset failed (%s)", exc)
        reset_fallback = getattr(self._fallback, "reset", None)
        if reset_fallback is not None:
            reset_fallback()


def _connect_redis(url: str):
    """Build a pinged sync Redis client (import deferred: redis is optional)."""
    import redis

    client = redis.Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0
    )
    client.ping()
    return client


def _limiter_from_env() -> RateLimiter:
    capacity = int(os.environ.get("RATE_LIMIT_CAPACITY", "60"))
    refill = float(os.environ.get("RATE_LIMIT_REFILL_PER_SECOND", "1.0"))
    backend = os.environ.get("RATE_LIMIT_BACKEND", "auto").strip().lower()
    url = os.environ.get("REDIS_URL") or None

    if backend == "redis" or (backend == "auto" and url):
        try:
            if not url:
                raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
            client = _connect_redis(url)
            logger.info("rate limiter backend: redis (%s)", url)
            return RedisTokenBucketRateLimiter(
                client, capacity=capacity, refill_per_second=refill
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never crash startup
            logger.warning(
                "redis rate limiter unavailable (%s); degrading to in-memory "
                "per-process limits",
                exc,
            )
    return TokenBucketRateLimiter(capacity=capacity, refill_per_second=refill)


_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = _limiter_from_env()
    return _rate_limiter


def set_rate_limiter(limiter: RateLimiter | None) -> None:
    """Swap the process-wide limiter (tests; alternative backends)."""
    global _rate_limiter
    _rate_limiter = limiter
