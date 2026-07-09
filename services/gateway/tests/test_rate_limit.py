"""Rate limiting: token bucket unit behavior + 429 enforcement on the proxy."""

from __future__ import annotations

import httpx
import respx

from app import rate_limit
from tests.conftest import auth_headers


def test_token_bucket_allows_burst_then_blocks() -> None:
    limiter = rate_limit.TokenBucketRateLimiter(capacity=3, refill_per_second=0.0)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_token_bucket_keys_are_independent() -> None:
    limiter = rate_limit.TokenBucketRateLimiter(capacity=1, refill_per_second=0.0)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_token_bucket_refills_over_time(monkeypatch) -> None:
    fake_now = [100.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: fake_now[0])

    limiter = rate_limit.TokenBucketRateLimiter(capacity=1, refill_per_second=1.0)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    fake_now[0] += 1.5  # 1.5s later -> 1 token refilled (capped at capacity)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_token_bucket_reset() -> None:
    limiter = rate_limit.TokenBucketRateLimiter(capacity=1, refill_per_second=0.0)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    limiter.reset()
    assert limiter.allow("k") is True


@respx.mock
def test_proxy_throttles_after_burst(client) -> None:
    rate_limit.set_rate_limiter(
        rate_limit.TokenBucketRateLimiter(capacity=3, refill_per_second=0.0)
    )
    respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[])
    )
    headers = auth_headers(sub="throttled-user")

    for _ in range(3):
        assert client.get("/api/strategies/list", headers=headers).status_code == 200

    response = client.get("/api/strategies/list", headers=headers)
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "1"


@respx.mock
def test_rate_limit_is_per_user(client) -> None:
    rate_limit.set_rate_limiter(
        rate_limit.TokenBucketRateLimiter(capacity=1, refill_per_second=0.0)
    )
    respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[])
    )

    assert (
        client.get("/api/strategies/list", headers=auth_headers(sub="user-a")).status_code
        == 200
    )
    assert (
        client.get("/api/strategies/list", headers=auth_headers(sub="user-a")).status_code
        == 429
    )
    # a different user still has a full bucket
    assert (
        client.get("/api/strategies/list", headers=auth_headers(sub="user-b")).status_code
        == 200
    )


@respx.mock
def test_unauthenticated_auth_traffic_limited_by_ip(client) -> None:
    rate_limit.set_rate_limiter(
        rate_limit.TokenBucketRateLimiter(capacity=2, refill_per_second=0.0)
    )
    respx.post("http://auth-service:8000/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "bad credentials"})
    )

    assert client.post("/api/auth/login", json={}).status_code == 401
    assert client.post("/api/auth/login", json={}).status_code == 401
    assert client.post("/api/auth/login", json={}).status_code == 429
