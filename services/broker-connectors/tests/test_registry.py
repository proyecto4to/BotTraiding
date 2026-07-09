from __future__ import annotations

import pytest

from app.connectors.binance import BinanceConnector
from app.connectors.http_base import BrokerConfig
from app.registry import ConnectorRegistry, UnknownBrokerError


def test_create_known_broker_returns_expected_class():
    registry = ConnectorRegistry()
    config = BrokerConfig(broker="binance", demo=True)
    connector = registry.create_connector("binance", config)
    assert isinstance(connector, BinanceConnector)


def test_create_unknown_broker_raises():
    registry = ConnectorRegistry()
    config = BrokerConfig(broker="not-a-broker", demo=True)
    with pytest.raises(UnknownBrokerError):
        registry.create_connector("not-a-broker", config)


def test_get_or_create_caches_by_broker_and_account():
    registry = ConnectorRegistry()
    config = BrokerConfig(broker="binance", demo=True, account_id="acct1")
    first = registry.get_or_create("binance", config)
    second = registry.get_or_create("binance", config)
    assert first is second

    other_account = BrokerConfig(broker="binance", demo=True, account_id="acct2")
    third = registry.get_or_create("binance", other_account)
    assert third is not first


def test_remove_and_get():
    registry = ConnectorRegistry()
    config = BrokerConfig(broker="binance", demo=True)
    registry.get_or_create("binance", config)
    assert registry.get("binance") is not None
    registry.remove("binance")
    assert registry.get("binance") is None


def test_available_brokers_lists_all_eight_connectors():
    registry = ConnectorRegistry()
    assert len(registry.available_brokers()) == 8
    assert set(registry.available_brokers()) == {
        "interactive_brokers",
        "binance",
        "bybit",
        "kraken",
        "okx",
        "oanda",
        "metatrader5",
        "alpaca",
    }
