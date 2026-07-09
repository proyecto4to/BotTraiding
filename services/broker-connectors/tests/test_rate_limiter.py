from __future__ import annotations

import asyncio

import pytest

from app.rate_limiter import TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_burst_up_to_capacity_is_immediate():
    limiter = TokenBucketRateLimiter(capacity=3, refill_per_second=1.0)
    for _ in range(3):
        await asyncio.wait_for(limiter.acquire(), timeout=0.05)
    assert limiter.available_tokens() < 1.0


@pytest.mark.asyncio
async def test_throttles_once_bucket_is_empty():
    limiter = TokenBucketRateLimiter(capacity=1, refill_per_second=5.0)  # refill every 0.2s
    await limiter.acquire()

    loop = asyncio.get_event_loop()
    start = loop.time()
    await limiter.acquire()
    elapsed = loop.time() - start

    assert elapsed >= 0.15


def test_invalid_capacity_rejected():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=0, refill_per_second=1.0)


def test_invalid_refill_rate_rejected():
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=1, refill_per_second=0)
