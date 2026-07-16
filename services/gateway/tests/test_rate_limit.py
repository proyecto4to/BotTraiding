"""Rate limiting: token bucket unit behavior + 429 enforcement on the proxy,
plus the Redis-backed bucket (shared across replicas) and backend selection."""

from __future__ import annotations

import fakeredis
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


# --- Redis-backed limiter (P3) ------------------------------------------------


def _redis_client(server: fakeredis.FakeServer | None = None) -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=server or fakeredis.FakeServer(), decode_responses=True)


def test_redis_bucket_allows_burst_then_blocks() -> None:
    limiter = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(), capacity=3, refill_per_second=0.0
    )
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_redis_bucket_keys_are_independent() -> None:
    limiter = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(), capacity=1, refill_per_second=0.0
    )
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True


def test_redis_bucket_refills_over_time(monkeypatch) -> None:
    fake_now = [1_000.0]
    monkeypatch.setattr(rate_limit.time, "time", lambda: fake_now[0])

    limiter = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(), capacity=1, refill_per_second=1.0
    )
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    fake_now[0] += 1.5  # 1.5s later -> 1 token refilled (capped at capacity)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


def test_two_replicas_share_the_budget() -> None:
    """The point of P3: two gateway replicas draw from ONE bucket per caller."""
    server = fakeredis.FakeServer()
    replica_a = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(server), capacity=3, refill_per_second=0.0
    )
    replica_b = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(server), capacity=3, refill_per_second=0.0
    )

    assert replica_a.allow("user-1") is True
    assert replica_b.allow("user-1") is True
    assert replica_a.allow("user-1") is True
    # combined budget (3) exhausted: BOTH replicas now refuse
    assert replica_a.allow("user-1") is False
    assert replica_b.allow("user-1") is False
    # an unrelated caller still has a full shared bucket
    assert replica_b.allow("user-2") is True


def test_redis_bucket_reset_clears_shared_state() -> None:
    server = fakeredis.FakeServer()
    limiter = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(server), capacity=1, refill_per_second=0.0
    )
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    limiter.reset()
    assert limiter.allow("k") is True


def test_redis_failure_degrades_to_in_process_fallback() -> None:
    class BrokenRedis:
        def transaction(self, *args, **kwargs):
            raise ConnectionError("redis is down")

    limiter = rate_limit.RedisTokenBucketRateLimiter(
        BrokenRedis(), capacity=2, refill_per_second=0.0
    )
    # A Redis outage never 500s or fails open: per-process limiting continues.
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False


# --- backend selection from the environment ------------------------------------


def test_backend_memory_forced(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    limiter = rate_limit._limiter_from_env()
    assert isinstance(limiter, rate_limit.TokenBucketRateLimiter)


def test_backend_auto_without_redis_url_uses_memory(monkeypatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    limiter = rate_limit._limiter_from_env()
    assert isinstance(limiter, rate_limit.TokenBucketRateLimiter)


def test_backend_auto_with_redis_url_uses_redis(monkeypatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_BACKEND", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(rate_limit, "_connect_redis", lambda url: _redis_client())
    limiter = rate_limit._limiter_from_env()
    assert isinstance(limiter, rate_limit.RedisTokenBucketRateLimiter)


def test_backend_redis_unavailable_degrades_to_memory(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")

    def _boom(url):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(rate_limit, "_connect_redis", _boom)
    # test_migration's alembic fileConfig() disables pre-existing loggers;
    # re-enable ours so the degrade warning is observable in full-suite runs.
    monkeypatch.setattr(rate_limit.logger, "disabled", False)
    with caplog.at_level("WARNING", logger="gateway.rate_limit"):
        limiter = rate_limit._limiter_from_env()
    assert isinstance(limiter, rate_limit.TokenBucketRateLimiter)
    assert any("degrading to in-memory" in rec.message for rec in caplog.records)


def test_backend_redis_without_url_degrades_to_memory(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    limiter = rate_limit._limiter_from_env()
    assert isinstance(limiter, rate_limit.TokenBucketRateLimiter)


@respx.mock
def test_proxy_throttles_through_redis_limiter(client) -> None:
    """End-to-end: the proxy 429s when the SHARED Redis budget runs out."""
    server = fakeredis.FakeServer()
    rate_limit.set_rate_limiter(
        rate_limit.RedisTokenBucketRateLimiter(
            _redis_client(server), capacity=2, refill_per_second=0.0
        )
    )
    # Another "replica" already spent one token of this user's shared budget.
    other_replica = rate_limit.RedisTokenBucketRateLimiter(
        _redis_client(server), capacity=2, refill_per_second=0.0
    )
    assert other_replica.allow("user-shared") is True

    respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[])
    )
    headers = auth_headers(sub="user-shared")
    assert client.get("/api/strategies/list", headers=headers).status_code == 200
    response = client.get("/api/strategies/list", headers=headers)
    assert response.status_code == 429
