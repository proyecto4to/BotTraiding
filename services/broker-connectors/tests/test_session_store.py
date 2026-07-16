"""P3: Redis-backed session registry.

Two "replicas" are two ``RedisConnectorRegistry`` instances pointing at the
same (fake) Redis server: a session opened through one must be visible and
servable from the other, and closing it anywhere closes it everywhere.
"""

from __future__ import annotations

import fakeredis
import pytest
from app import registry as registry_module
from app.connectors.http_base import BrokerConfig
from app.registry import ConnectorRegistry, RedisConnectorRegistry, build_registry
from fastapi.testclient import TestClient

from .conftest import default_handler, make_mock_client


@pytest.fixture()
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


def make_registry(server: fakeredis.FakeServer) -> RedisConnectorRegistry:
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    return RedisConnectorRegistry(client)


def make_config(account_id: str = "default") -> BrokerConfig:
    return BrokerConfig(
        broker="bybit",
        api_key="key-1",
        api_secret="secret-1",
        demo=True,
        account_id=account_id,
    )


# --- replicas share the session ------------------------------------------------


def test_second_replica_sees_connected_session(redis_server) -> None:
    replica_a = make_registry(redis_server)
    replica_b = make_registry(redis_server)

    connector_a = replica_a.get_or_create(
        "bybit", make_config(), client=make_mock_client(default_handler)
    )
    assert replica_b.get("bybit") is not None  # descriptor is shared already
    assert replica_b.get("bybit").is_connected() is False  # but not connected yet

    connector_a._connected = True  # what a successful connect() does locally
    replica_a.mark_connected("bybit", "default", True)

    # drop replica_b's cached instance so it rehydrates from the descriptor
    replica_b._instances.clear()
    rebuilt = replica_b.get("bybit")
    assert rebuilt is not None
    assert rebuilt.is_connected() is True
    assert rebuilt.config.api_key == "key-1"
    assert rebuilt.config.api_secret == "secret-1"
    assert rebuilt.config.demo is True


def test_remove_on_one_replica_closes_session_everywhere(redis_server) -> None:
    replica_a = make_registry(redis_server)
    replica_b = make_registry(redis_server)

    replica_a.get_or_create("bybit", make_config(), client=make_mock_client(default_handler))
    replica_a.mark_connected("bybit", "default", True)
    assert replica_b.get("bybit") is not None  # B now has a local instance too

    replica_a.remove("bybit")
    # B must notice the shared session is gone and drop its stale instance.
    assert replica_b.get("bybit") is None


def test_sessions_are_per_account(redis_server) -> None:
    replica_a = make_registry(redis_server)
    replica_b = make_registry(redis_server)

    replica_a.get_or_create(
        "bybit", make_config(account_id="acct-1"), client=make_mock_client(default_handler)
    )
    assert replica_b.get("bybit", "acct-1") is not None
    assert replica_b.get("bybit", "acct-2") is None


def test_reset_clears_shared_descriptors(redis_server) -> None:
    replica_a = make_registry(redis_server)
    replica_b = make_registry(redis_server)

    replica_a.get_or_create("bybit", make_config(), client=make_mock_client(default_handler))
    replica_a.reset()
    assert replica_b.get("bybit") is None


def test_connect_endpoint_shares_session_with_other_replica(
    redis_server, monkeypatch
) -> None:
    """End-to-end: POST /connectors/bybit/connect on replica A -> replica B
    reports the session as connected (the /connect handler persists the flag
    via registry.mark_connected)."""
    import app.main as main_module

    replica_a = make_registry(redis_server)
    replica_b = make_registry(redis_server)
    monkeypatch.setattr(main_module, "registry", replica_a)

    # Seed the connector with a mocked transport so connect() pings the mock.
    replica_a.get_or_create("bybit", make_config(), client=make_mock_client(default_handler))

    client = TestClient(main_module.app)
    response = client.post(
        "/connectors/bybit/connect",
        json={"api_key": "key-1", "api_secret": "secret-1", "demo": True},
    )
    assert response.status_code == 200
    assert response.json()["connected"] is True

    rebuilt = replica_b.get("bybit")
    assert rebuilt is not None
    assert rebuilt.is_connected() is True


# --- degradation ----------------------------------------------------------------


class BrokenRedis:
    def get(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    def set(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    def delete(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    def scan_iter(self, *args, **kwargs):
        raise ConnectionError("redis is down")


def test_redis_blip_degrades_to_local_behaviour() -> None:
    registry = RedisConnectorRegistry(BrokenRedis())

    connector = registry.get_or_create(
        "bybit", make_config(), client=make_mock_client(default_handler)
    )
    assert connector is not None
    # get() serves the local instance when Redis cannot be consulted.
    assert registry.get("bybit") is connector
    registry.mark_connected("bybit")  # must not raise
    registry.remove("bybit")  # must not raise
    assert registry._instances == {}


# --- backend selection from the environment --------------------------------------


def test_build_registry_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.delenv("SESSION_STORE", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    built = build_registry()
    assert type(built) is ConnectorRegistry


def test_build_registry_memory_forced(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_STORE", "memory")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    built = build_registry()
    assert type(built) is ConnectorRegistry


def test_build_registry_auto_uses_redis_when_url_set(monkeypatch, redis_server) -> None:
    monkeypatch.delenv("SESSION_STORE", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(
        registry_module,
        "_connect_redis",
        lambda url: fakeredis.FakeRedis(server=redis_server, decode_responses=True),
    )
    built = build_registry()
    assert isinstance(built, RedisConnectorRegistry)


def test_build_registry_degrades_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_STORE", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")

    def _boom(url):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(registry_module, "_connect_redis", _boom)
    built = build_registry()
    assert type(built) is ConnectorRegistry  # degraded, service still boots


def test_build_registry_redis_without_url_degrades(monkeypatch) -> None:
    monkeypatch.setenv("SESSION_STORE", "redis")
    monkeypatch.delenv("REDIS_URL", raising=False)
    built = build_registry()
    assert type(built) is ConnectorRegistry
