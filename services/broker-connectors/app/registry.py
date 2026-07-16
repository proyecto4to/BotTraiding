"""Connector registry/factory.

Given a broker name + config (demo/real, API keys), returns the right
``BrokerConnector`` instance. This is what other services (execution-engine,
backtester) will eventually call instead of importing a concrete connector
class directly.

P3: session state can be shared through Redis. Live connector objects cannot
cross process boundaries, so every replica keeps its own instance cache; what
Redis holds is the *session descriptor* (broker config + connected flag) so
another replica -- or this process after a restart -- rebuilds an equivalent
connector on demand. Selection (``build_registry``):

- ``SESSION_STORE=memory``: per-process sessions (previous behaviour).
- ``SESSION_STORE=redis``: sessions shared via ``REDIS_URL``.
- unset / ``auto``: Redis when ``REDIS_URL`` is set, memory otherwise.

Redis missing/unreachable at startup degrades to the in-memory registry with
a warning -- the service never fails to start over the session store.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from trading_contracts.broker_connector import BrokerConnector

from .connectors.alpaca import AlpacaConnector
from .connectors.binance import BinanceConnector
from .connectors.bybit import BybitConnector
from .connectors.http_base import BrokerConfig
from .connectors.interactive_brokers import InteractiveBrokersConnector
from .connectors.kraken import KrakenConnector
from .connectors.metatrader5 import MetaTrader5Connector
from .connectors.oanda import OandaConnector
from .connectors.okx import OkxConnector

logger = logging.getLogger("broker-connectors.registry")

CONNECTOR_CLASSES: dict[str, type[BrokerConnector]] = {
    "interactive_brokers": InteractiveBrokersConnector,
    "binance": BinanceConnector,
    "bybit": BybitConnector,
    "kraken": KrakenConnector,
    "okx": OkxConnector,
    "oanda": OandaConnector,
    "metatrader5": MetaTrader5Connector,
    "alpaca": AlpacaConnector,
}


class UnknownBrokerError(KeyError):
    """Raised when a broker name has no registered connector."""


class ConnectorRegistry:
    """Factory + per (broker, account) instance cache for connectors."""

    def __init__(self) -> None:
        self._instances: dict[tuple[str, str], BrokerConnector] = {}

    def available_brokers(self) -> list[str]:
        return sorted(CONNECTOR_CLASSES)

    def create_connector(
        self, broker: str, config: BrokerConfig, client: Optional[object] = None
    ) -> BrokerConnector:
        try:
            connector_cls = CONNECTOR_CLASSES[broker]
        except KeyError as exc:
            raise UnknownBrokerError(broker) from exc
        return connector_cls(config, client=client)

    def get_or_create(
        self, broker: str, config: BrokerConfig, client: Optional[object] = None
    ) -> BrokerConnector:
        key = (broker, config.account_id)
        if key not in self._instances:
            self._instances[key] = self.create_connector(broker, config, client=client)
        return self._instances[key]

    def get(self, broker: str, account_id: str = "default") -> Optional[BrokerConnector]:
        return self._instances.get((broker, account_id))

    def remove(self, broker: str, account_id: str = "default") -> None:
        self._instances.pop((broker, account_id), None)

    def mark_connected(
        self, broker: str, account_id: str = "default", connected: bool = True
    ) -> None:
        """Session-state hook called after a successful connect/disconnect.

        The in-memory registry tracks connection state on the live connector
        itself, so there is nothing to record; the Redis registry overrides
        this to share the flag with other replicas."""

    def reset(self) -> None:
        """Test helper: clear all cached connector instances."""
        self._instances.clear()


class RedisConnectorRegistry(ConnectorRegistry):
    """Registry whose session descriptors are shared through Redis (P3).

    A descriptor (``broker_sessions:{broker}:{account_id}``) stores the
    ``BrokerConfig`` fields plus the connected flag. ``get()`` rebuilds a
    local connector from the descriptor when this process has none -- that is
    what lets a second replica (or a restarted one) serve requests for a
    session another replica opened. Every Redis failure is logged and the
    call degrades to the in-memory behaviour, never raises.

    Note: descriptors carry the API key/secret (Redis is the designated
    session store, ARCHITECTURE.md section 7); protect the Redis instance
    accordingly.
    """

    def __init__(self, client, *, key_prefix: str = "broker_sessions:") -> None:
        super().__init__()
        self._client = client
        self._prefix = key_prefix

    def _key(self, broker: str, account_id: str) -> str:
        return f"{self._prefix}{broker}:{account_id}"

    def _load_session(self, broker: str, account_id: str) -> Optional[dict[str, Any]]:
        raw = self._client.get(self._key(broker, account_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "corrupt session descriptor for %s/%s (%s); ignoring", broker, account_id, exc
            )
            return None

    def _save_session(self, broker: str, config: BrokerConfig, connected: bool) -> None:
        payload = json.dumps(
            {
                "api_key": config.api_key,
                "api_secret": config.api_secret,
                "demo": config.demo,
                "extra": config.extra,
                "connected": connected,
            }
        )
        self._client.set(self._key(broker, config.account_id), payload)

    def get_or_create(
        self, broker: str, config: BrokerConfig, client: Optional[object] = None
    ) -> BrokerConnector:
        connector = super().get_or_create(broker, config, client=client)
        try:
            self._save_session(broker, config, connector.is_connected())
        except Exception as exc:  # noqa: BLE001 - degrade to per-process session
            logger.warning("could not persist session to redis (%s)", exc)
        return connector

    def get(self, broker: str, account_id: str = "default") -> Optional[BrokerConnector]:
        local = super().get(broker, account_id)
        try:
            descriptor = self._load_session(broker, account_id)
        except Exception as exc:  # noqa: BLE001 - serve local state on a Redis blip
            logger.warning("redis session lookup failed (%s); serving local state", exc)
            return local
        if descriptor is None:
            if local is not None:
                # Session closed by another replica: drop the stale instance.
                super().remove(broker, account_id)
            return None
        if local is not None:
            return local
        # Another replica opened this session: rebuild a local connector.
        config = BrokerConfig(
            broker=broker,
            api_key=descriptor.get("api_key", ""),
            api_secret=descriptor.get("api_secret", ""),
            demo=bool(descriptor.get("demo", True)),
            account_id=account_id,
            extra=descriptor.get("extra") or {},
        )
        connector = self.create_connector(broker, config)
        if descriptor.get("connected"):
            # The cluster-wide session is live; the HTTP client is built
            # lazily on first request (see BaseHTTPConnector._ensure_client).
            connector._connected = True  # noqa: SLF001 - registry owns its connectors
        self._instances[(broker, account_id)] = connector
        return connector

    def mark_connected(
        self, broker: str, account_id: str = "default", connected: bool = True
    ) -> None:
        try:
            descriptor = self._load_session(broker, account_id)
            if descriptor is None:
                return
            descriptor["connected"] = connected
            self._client.set(self._key(broker, account_id), json.dumps(descriptor))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not update session state in redis (%s)", exc)

    def remove(self, broker: str, account_id: str = "default") -> None:
        super().remove(broker, account_id)
        try:
            self._client.delete(self._key(broker, account_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not remove session from redis (%s)", exc)

    def reset(self) -> None:
        """Test helper: clear local instances AND every shared descriptor."""
        super().reset()
        try:
            keys = list(self._client.scan_iter(f"{self._prefix}*"))
            if keys:
                self._client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not reset sessions in redis (%s)", exc)


def _connect_redis(url: str):
    """Build a pinged sync Redis client (import deferred: redis is optional)."""
    import redis

    client = redis.Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0
    )
    client.ping()
    return client


def build_registry() -> ConnectorRegistry:
    """Pick the session backend from the environment (see module docstring)."""
    backend = os.environ.get("SESSION_STORE", "auto").strip().lower()
    url = os.environ.get("REDIS_URL") or None
    if backend == "redis" or (backend == "auto" and url):
        try:
            if not url:
                raise RuntimeError("SESSION_STORE=redis requires REDIS_URL")
            client = _connect_redis(url)
            logger.info("session store backend: redis (%s)", url)
            return RedisConnectorRegistry(client)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash startup
            logger.warning(
                "redis session store unavailable (%s); degrading to in-memory "
                "per-process sessions",
                exc,
            )
    return ConnectorRegistry()


registry = build_registry()
