from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.connectors.alpaca import AlpacaConnector
from app.connectors.binance import BinanceConnector
from app.connectors.bybit import BybitConnector
from app.connectors.http_base import BrokerConfig
from app.connectors.interactive_brokers import InteractiveBrokersConnector
from app.connectors.kraken import KrakenConnector
from app.connectors.oanda import OandaConnector
from app.connectors.okx import OkxConnector
from app.reconnect import ReconnectError
from trading_contracts.models import ExecutionMode, Order, OrderSide, OrderType

from .conftest import default_handler, make_mock_client

HTTP_CONNECTOR_CLASSES = [
    AlpacaConnector,
    BinanceConnector,
    BybitConnector,
    InteractiveBrokersConnector,
    KrakenConnector,
    OandaConnector,
    OkxConnector,
]


def make_order() -> Order:
    return Order(
        id=uuid4(),
        signal_id=uuid4(),
        symbol="BTCUSD",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
        price=None,
        broker="test",
        account_id="default",
        execution_mode=ExecutionMode.PAPER,
        created_at=datetime.utcnow(),
    )


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_connect_and_place_order(connector_cls):
    config = BrokerConfig(broker=connector_cls.broker_name, api_key="k", api_secret="s", demo=True)
    connector = connector_cls(config, client=make_mock_client(default_handler))

    assert not connector.is_connected()
    await connector.connect()
    assert connector.is_connected()

    report = await connector.place_order(make_order())
    assert report.filled_quantity == 1.0
    assert report.average_fill_price == 100.0
    assert report.broker == connector_cls.broker_name

    await connector.cancel_order("order-123")
    await connector.disconnect()
    assert not connector.is_connected()


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_get_positions(connector_cls):
    config = BrokerConfig(broker=connector_cls.broker_name, demo=True)
    connector = connector_cls(config, client=make_mock_client(default_handler))
    await connector.connect()

    positions = await connector.get_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSD"


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_get_account_state(connector_cls):
    config = BrokerConfig(broker=connector_cls.broker_name, demo=True)
    connector = connector_cls(config, client=make_mock_client(default_handler))
    await connector.connect()

    account = await connector.get_account_state()

    assert account.balance == 1000.0
    assert account.equity == 1010.0


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_historical_data(connector_cls):
    config = BrokerConfig(broker=connector_cls.broker_name, demo=True)
    connector = connector_cls(config, client=make_mock_client(default_handler))
    await connector.connect()

    bars = await connector.get_historical_data(
        "BTCUSD", "1h", datetime.utcnow() - timedelta(days=1), datetime.utcnow()
    )

    assert len(bars) == 1
    assert bars[0].symbol == "BTCUSD"


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_stream_market_data(connector_cls):
    config = BrokerConfig(broker=connector_cls.broker_name, demo=True)
    connector = connector_cls(config, client=make_mock_client(default_handler))
    await connector.connect()

    ticks = [t async for t in connector.stream_market_data(["BTCUSD", "ETHUSD"])]

    assert len(ticks) == 2
    assert {t.symbol for t in ticks} == {"BTCUSD", "ETHUSD"}


@pytest.mark.parametrize("connector_cls", HTTP_CONNECTOR_CLASSES)
async def test_reconnect_after_transport_drop(connector_cls):
    """First 2 pings fail (dropped transport), 3rd succeeds via backoff retry."""
    attempts = {"n": 0}

    def flaky_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ping":
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.ConnectError("connection dropped")
        return default_handler(request)

    config = BrokerConfig(broker=connector_cls.broker_name, demo=True)
    connector = connector_cls(config, client=make_mock_client(flaky_handler))

    await connector.connect()

    assert connector.is_connected()
    assert attempts["n"] == 3


async def test_reconnect_exhausts_attempts_and_raises():
    def always_fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("always down")

    config = BrokerConfig(broker="binance", demo=True)
    connector = BinanceConnector(config, client=make_mock_client(always_fail))

    with pytest.raises(ReconnectError):
        await connector.connect()

    assert not connector.is_connected()
