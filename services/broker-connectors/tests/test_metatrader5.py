"""Tests for the MetaTrader5 connector against a fake Mt5Client.

The real `MetaTrader5` package only runs on Windows with a live terminal
process; these tests exercise the connector's logic entirely through the
injectable `Mt5Client` protocol, no real MT5 dependency involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.connectors.http_base import BrokerConfig
from app.connectors.metatrader5 import MetaTrader5Connector
from trading_contracts.models import ExecutionMode, Order, OrderSide, OrderType


class FakeResult:
    def __init__(self, retcode: int = 0, volume: float = 1.0, price: float = 100.0) -> None:
        self.retcode = retcode
        self.volume = volume
        self.price = price


class FakePosition:
    symbol = "EURUSD"
    volume = 1.0
    price_open = 1.1
    profit = 2.5


class FakeAccountInfo:
    balance = 1000.0
    equity = 1010.0
    margin = 10.0
    margin_free = 990.0
    currency = "USD"


class FakeTick:
    bid = 1.1
    ask = 1.1002


class FakeMt5Client:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.initialized = False

    def initialize(self, login: int, password: str, server: str) -> bool:
        self.calls += 1
        if self.calls <= self.fail_times:
            return False
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def order_send(self, request: dict):
        return FakeResult()

    def positions_get(self):
        return [FakePosition()]

    def account_info(self):
        return FakeAccountInfo()

    def copy_rates_range(self, symbol, timeframe, start, end):
        return [
            {
                "open": 1.1,
                "high": 1.2,
                "low": 1.05,
                "close": 1.15,
                "tick_volume": 100,
                "time": datetime.utcnow(),
            }
        ]

    def symbol_info_tick(self, symbol):
        return FakeTick()


def make_order() -> Order:
    return Order(
        id=uuid4(),
        signal_id=uuid4(),
        symbol="EURUSD",
        side=OrderSide.BUY,
        quantity=1.0,
        order_type=OrderType.MARKET,
        price=None,
        broker="metatrader5",
        account_id="default",
        execution_mode=ExecutionMode.PAPER,
        created_at=datetime.utcnow(),
    )


async def test_connect_without_client_raises():
    config = BrokerConfig(broker="metatrader5", demo=True)
    connector = MetaTrader5Connector(config, client=None)
    with pytest.raises(RuntimeError):
        await connector.connect()


async def test_connect_and_place_order():
    config = BrokerConfig(
        broker="metatrader5", api_secret="pw", demo=True, extra={"login": 123, "server": "Demo"}
    )
    connector = MetaTrader5Connector(config, client=FakeMt5Client())

    await connector.connect()
    assert connector.is_connected()

    report = await connector.place_order(make_order())
    assert report.status.value == "submitted"
    assert report.filled_quantity == 1.0

    await connector.disconnect()
    assert not connector.is_connected()


async def test_reconnect_after_drop():
    client = FakeMt5Client(fail_times=2)
    config = BrokerConfig(
        broker="metatrader5", api_secret="pw", demo=True, extra={"login": 1, "server": "Demo"}
    )
    connector = MetaTrader5Connector(config, client=client)

    await connector.connect()

    assert connector.is_connected()
    assert client.calls == 3


async def test_get_positions_and_account():
    config = BrokerConfig(broker="metatrader5", demo=True)
    connector = MetaTrader5Connector(config, client=FakeMt5Client())
    await connector.connect()

    positions = await connector.get_positions()
    assert positions[0].symbol == "EURUSD"

    account = await connector.get_account_state()
    assert account.balance == 1000.0


async def test_historical_and_stream():
    config = BrokerConfig(broker="metatrader5", demo=True)
    connector = MetaTrader5Connector(config, client=FakeMt5Client())
    await connector.connect()

    bars = await connector.get_historical_data(
        "EURUSD", "1h", datetime.utcnow() - timedelta(days=1), datetime.utcnow()
    )
    assert len(bars) == 1

    ticks = [t async for t in connector.stream_market_data(["EURUSD"])]
    assert len(ticks) == 1
