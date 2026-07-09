"""MetaTrader5 connector.

Real MT5 integration requires the ``MetaTrader5`` Python package, which
only works on Windows with a running MetaTrader 5 terminal process (IPC,
not HTTP) - it cannot be installed or exercised in this sandbox and has no
Linux/mac support. This connector is written against a small duck-typed
``Mt5Client`` protocol mirroring the real package's function surface
(``initialize``, ``shutdown``, ``order_send``, ``positions_get``,
``account_info``, ``copy_rates_range``, ``symbol_info_tick``) so it can be
unit-tested with a mock and swapped for ``import MetaTrader5 as mt5`` in a
deployment that actually has a running terminal.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, AsyncIterator, Optional, Protocol

from trading_contracts.broker_connector import BrokerConnector
from trading_contracts.models import (
    AccountState,
    Bar,
    ExecutionReport,
    Order,
    OrderStatus,
    Position,
    Tick,
)

from ..broker_limits import get_rate_limit
from ..rate_limiter import TokenBucketRateLimiter
from ..reconnect import reconnect_with_backoff
from .http_base import BrokerConfig


class Mt5Client(Protocol):
    def initialize(self, login: int, password: str, server: str) -> bool: ...

    def shutdown(self) -> None: ...

    def order_send(self, request: dict[str, Any]) -> Any: ...

    def positions_get(self) -> Optional[list[Any]]: ...

    def account_info(self) -> Any: ...

    def copy_rates_range(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> Optional[list[dict[str, Any]]]: ...

    def symbol_info_tick(self, symbol: str) -> Any: ...


class MetaTrader5Connector(BrokerConnector):
    broker_name = "metatrader5"

    def __init__(self, config: BrokerConfig, client: Optional[Mt5Client] = None) -> None:
        self.config = config
        self._client = client
        self._connected = False
        self._rate_limiter = TokenBucketRateLimiter(*get_rate_limit(self.broker_name))

    async def connect(self) -> None:
        if self._client is None:
            raise RuntimeError(
                "MetaTrader5Connector requires an injected Mt5Client "
                "(the real MetaTrader5 terminal only runs on Windows)"
            )

        async def attempt() -> None:
            await self._rate_limiter.acquire()
            ok = await asyncio.to_thread(
                self._client.initialize,
                int(self.config.extra.get("login", 0)),
                self.config.api_secret,
                self.config.extra.get("server", "MetaTrader5-Demo" if self.config.demo else "MetaTrader5-Live"),
            )
            if not ok:
                raise ConnectionError("MetaTrader5 initialize() failed")
            self._connected = True

        await reconnect_with_backoff(attempt)

    async def disconnect(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.shutdown)
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def place_order(self, order: Order) -> ExecutionReport:
        await self._rate_limiter.acquire()
        request = {
            "symbol": order.symbol,
            "volume": order.quantity,
            "type": order.side.value,
            "type_filling": order.order_type.value,
            "price": order.price,
        }
        result = await asyncio.to_thread(self._client.order_send, request)
        retcode = getattr(result, "retcode", None)
        status = OrderStatus.SUBMITTED if retcode in (0, 10009) else OrderStatus.REJECTED
        return ExecutionReport(
            order_id=order.id,
            status=status,
            filled_quantity=getattr(result, "volume", 0.0),
            average_fill_price=getattr(result, "price", None),
            broker=self.broker_name,
            reported_at=datetime.utcnow(),
            raw={"retcode": retcode},
        )

    async def cancel_order(self, order_id: str) -> None:
        await self._rate_limiter.acquire()
        await asyncio.to_thread(self._client.order_send, {"action": "remove", "order": order_id})

    async def get_positions(self) -> list[Position]:
        await self._rate_limiter.acquire()
        raw_positions = await asyncio.to_thread(self._client.positions_get)
        return [
            Position(
                symbol=p.symbol,
                quantity=p.volume,
                average_price=p.price_open,
                unrealized_pnl=getattr(p, "profit", 0.0),
                account_id=self.config.account_id,
            )
            for p in (raw_positions or [])
        ]

    async def get_account_state(self) -> AccountState:
        await self._rate_limiter.acquire()
        info = await asyncio.to_thread(self._client.account_info)
        return AccountState(
            account_id=self.config.account_id,
            balance=info.balance,
            equity=info.equity,
            margin_used=info.margin,
            free_margin=info.margin_free,
            currency=getattr(info, "currency", "USD"),
        )

    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:
        for symbol in symbols:
            await self._rate_limiter.acquire()
            tick = await asyncio.to_thread(self._client.symbol_info_tick, symbol)
            yield Tick(symbol=symbol, bid=tick.bid, ask=tick.ask, timestamp=datetime.utcnow())

    async def get_historical_data(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        await self._rate_limiter.acquire()
        rates = await asyncio.to_thread(self._client.copy_rates_range, symbol, timeframe, start, end)
        bars: list[Bar] = []
        for r in rates or []:
            raw_time = r["time"]
            timestamp = raw_time if isinstance(raw_time, datetime) else datetime.fromtimestamp(raw_time)
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r.get("tick_volume", r.get("volume", 0)),
                    timestamp=timestamp,
                )
            )
        return bars
