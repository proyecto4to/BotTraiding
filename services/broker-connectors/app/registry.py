"""Connector registry/factory.

Given a broker name + config (demo/real, API keys), returns the right
``BrokerConnector`` instance. This is what other services (execution-engine,
backtester) will eventually call instead of importing a concrete connector
class directly.
"""

from __future__ import annotations

from typing import Optional

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

    def reset(self) -> None:
        """Test helper: clear all cached connector instances."""
        self._instances.clear()


registry = ConnectorRegistry()
