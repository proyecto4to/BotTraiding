"""Binance connector - first production-grade connector (spot REST + websockets).

Real endpoints used (spot API v3):

* ``GET  /api/v3/ping``               connectivity check (``connect()``)
* ``GET  /api/v3/exchangeInfo``       symbol filters (LOT_SIZE / PRICE_FILTER /
                                      MIN_NOTIONAL|NOTIONAL), cached per symbol
* ``GET  /api/v3/klines``             historical Bars (paginated)
* ``GET  /api/v3/ticker/bookTicker``  top-of-book -> shared ``Tick``
* ``POST /api/v3/order``              place order (SIGNED)
* ``DELETE /api/v3/order``            cancel order (SIGNED)
* ``GET  /api/v3/account``            balances -> ``AccountState`` / holdings (SIGNED)
* ``GET  /api/v3/openOrders``         cancel-by-id fallback + reports (SIGNED)
* ``GET  /api/v3/myTrades``           trade reports helper (SIGNED)

Demo mode targets the Binance *Spot Testnet* (https://testnet.binance.vision),
real mode targets production. Both are overridable via config
(``extra["base_url"]`` / ``extra["ws_url"]``) or environment variables
(``BINANCE_TESTNET_URL`` / ``BINANCE_API_URL`` and the ``*_WS_URL`` pair).

Positions on spot
-----------------
Binance *spot* has no positions/margin: you own asset balances. This
connector derives "positions" as holdings from ``GET /api/v3/account``
balances (every non-quote asset with a non-zero balance), with
``average_price`` reported as 0.0 because spot balances carry no cost basis -
computing one requires replaying ``/api/v3/myTrades`` (helper provided as
``get_my_trades()``). Futures (USD-M) would expose real positions but is a
different API family (``/fapi``) - see README-binance.md.

Rate limits
-----------
Binance meters by request *weight* (1200 weight/min on the default tier).
Every call passes its documented weight into the shared token-bucket
limiter; HTTP 429/418 drains the bucket and honours ``Retry-After``.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

from trading_contracts.models import (
    AccountState,
    Bar,
    ExecutionReport,
    Order,
    OrderStatus,
    OrderType,
    Position,
    Tick,
)

from ..reconnect import reconnect_with_backoff
from . import binance_auth
from .binance_ws import BinanceWebSocketClient, ConnectFactory
from .errors import (
    ClockSkewError,
    ConnectorError,
    ConnectorRateLimitError,
    InsufficientBalanceError,
    OrderNotFoundError,
    OrderRejectedError,
    UnsupportedTimeframeError,
)
from .http_base import BaseHTTPConnector, BrokerConfig

# --------------------------------------------------------------------------
# Typed errors (Binance error codes -> categories from .errors)
# --------------------------------------------------------------------------


class BinanceAPIError(ConnectorError):
    """Any Binance ``{"code": ..., "msg": ...}`` error not mapped more precisely."""

    def __init__(self, message: str, code: Optional[int] = None, http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class BinanceFilterError(BinanceAPIError, OrderRejectedError):
    """-1013 Filter failure (LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL...), or a
    local pre-flight rejection against the cached exchangeInfo filters."""


class BinanceInsufficientBalanceError(BinanceAPIError, InsufficientBalanceError):
    """-2010 New order rejected (insufficient balance)."""


class BinanceTimestampError(BinanceAPIError, ClockSkewError):
    """-1021 Timestamp outside recvWindow - local clock skew vs Binance."""


class BinanceOrderNotFoundError(BinanceAPIError, OrderNotFoundError):
    """-2011 cancel rejected / -2013 order does not exist."""


class BinanceRateLimitError(BinanceAPIError, ConnectorRateLimitError):
    """HTTP 429 (rate limited) or 418 (IP auto-banned for continuing after 429)."""

    def __init__(self, message: str, retry_after_seconds: Optional[float] = None, http_status: Optional[int] = None) -> None:
        BinanceAPIError.__init__(self, message, code=None, http_status=http_status)
        self.retry_after_seconds = retry_after_seconds


_ERROR_CODE_MAP: dict[int, type[BinanceAPIError]] = {
    -1013: BinanceFilterError,
    -2010: BinanceInsufficientBalanceError,
    -1021: BinanceTimestampError,
    -2011: BinanceOrderNotFoundError,
    -2013: BinanceOrderNotFoundError,
}

# --------------------------------------------------------------------------
# Interval mapping (platform timeframes -> Binance kline intervals)
# --------------------------------------------------------------------------

# Native Binance intervals. NOTE: "1m" (minute) vs "1M" (month) differ only
# by case, so exact-match is checked before any case-folding.
BINANCE_INTERVALS = frozenset(
    {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
)

_TIMEFRAME_ALIASES: dict[str, str] = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m", "30min": "30m",
    "60m": "1h", "60min": "1h", "120m": "2h", "240m": "4h",
    "m1": "1m", "m3": "3m", "m5": "5m", "m15": "15m", "m30": "30m",
    "h1": "1h", "h2": "2h", "h4": "4h", "h6": "6h", "h8": "8h", "h12": "12h",
    "d1": "1d", "1day": "1d", "w1": "1w", "1wk": "1w", "1week": "1w",
    "mn1": "1M", "1mo": "1M", "1mon": "1M", "1month": "1M",
}


def to_binance_interval(timeframe: str) -> str:
    """Map a platform timeframe string to a Binance kline interval."""
    candidate = timeframe.strip()
    if candidate in BINANCE_INTERVALS:
        return candidate
    lowered = candidate.lower()
    if lowered in BINANCE_INTERVALS:
        return lowered
    if lowered in _TIMEFRAME_ALIASES:
        return _TIMEFRAME_ALIASES[lowered]
    raise UnsupportedTimeframeError(
        f"timeframe '{timeframe}' has no Binance kline interval equivalent"
    )


# --------------------------------------------------------------------------
# Endpoint request weights (Binance spot docs; 1200 weight/min default tier)
# --------------------------------------------------------------------------

WEIGHTS: dict[str, int] = {
    "ping": 1,
    "exchange_info": 20,
    "klines": 2,
    "book_ticker": 2,
    "order": 1,
    "cancel_order": 1,
    "account": 20,
    "open_orders_all": 80,  # /api/v3/openOrders WITHOUT symbol
    "open_orders_symbol": 6,
    "my_trades": 20,
}

# --------------------------------------------------------------------------
# Symbol filters (exchangeInfo)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    step_size: Optional[Decimal] = None  # LOT_SIZE.stepSize
    min_qty: Optional[Decimal] = None  # LOT_SIZE.minQty
    tick_size: Optional[Decimal] = None  # PRICE_FILTER.tickSize
    min_notional: Optional[Decimal] = None  # MIN_NOTIONAL/NOTIONAL.minNotional
    apply_min_notional_to_market: bool = False


def _parse_symbol_filters(symbol_info: dict[str, Any]) -> SymbolFilters:
    step_size = min_qty = tick_size = min_notional = None
    apply_to_market = False
    for f in symbol_info.get("filters", []):
        filter_type = f.get("filterType")
        if filter_type == "LOT_SIZE":
            step_size = _decimal_or_none(f.get("stepSize"))
            min_qty = _decimal_or_none(f.get("minQty"))
        elif filter_type == "PRICE_FILTER":
            tick_size = _decimal_or_none(f.get("tickSize"))
        elif filter_type == "MIN_NOTIONAL":  # legacy spot filter name
            min_notional = _decimal_or_none(f.get("minNotional"))
            apply_to_market = bool(f.get("applyToMarket", False))
        elif filter_type == "NOTIONAL":  # current spot filter name
            min_notional = _decimal_or_none(f.get("minNotional"))
            apply_to_market = bool(f.get("applyMinToMarket", False))
    return SymbolFilters(
        symbol=symbol_info["symbol"],
        step_size=step_size,
        min_qty=min_qty,
        tick_size=tick_size,
        min_notional=min_notional,
        apply_min_notional_to_market=apply_to_market,
    )


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    dec = Decimal(str(value)).normalize()
    return dec if dec > 0 else None


def floor_to_step(value: Decimal, step: Optional[Decimal]) -> Decimal:
    """Round ``value`` DOWN to a multiple of ``step`` (never rounds up so an
    order can never exceed the intended size/price)."""
    if step is None or step == 0:
        return value
    return (value // step) * step


def format_decimal(value: Decimal) -> str:
    """Plain fixed-point string (Binance rejects scientific notation)."""
    text = format(value.normalize(), "f")
    return text if text else "0"


# --------------------------------------------------------------------------
# Order field mapping
# --------------------------------------------------------------------------

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP: "STOP_LOSS",
    OrderType.STOP_LIMIT: "STOP_LOSS_LIMIT",
}

_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.SUBMITTED,
    "PENDING_NEW": OrderStatus.SUBMITTED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELLED,
    "PENDING_CANCEL": OrderStatus.CANCELLED,
    "EXPIRED": OrderStatus.CANCELLED,
    "EXPIRED_IN_MATCH": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
}


def _average_fill_price(data: dict[str, Any]) -> Optional[float]:
    fills = data.get("fills") or []
    if fills:
        total_qty = sum(Decimal(str(f["qty"])) for f in fills)
        if total_qty > 0:
            total_quote = sum(Decimal(str(f["price"])) * Decimal(str(f["qty"])) for f in fills)
            return float(total_quote / total_qty)
    executed = Decimal(str(data.get("executedQty", "0") or "0"))
    quote = Decimal(str(data.get("cummulativeQuoteQty", "0") or "0"))
    if executed > 0 and quote > 0:
        return float(quote / executed)
    return None


# --------------------------------------------------------------------------
# Connector
# --------------------------------------------------------------------------


class BinanceConnector(BaseHTTPConnector):
    """Spot REST + websocket connector. Demo maps to the Spot Testnet."""

    broker_name = "binance"
    demo_base_url = "https://testnet.binance.vision"
    real_base_url = "https://api.binance.com"
    demo_ws_url = "wss://stream.testnet.binance.vision"
    real_ws_url = "wss://stream.binance.com:9443"

    def __init__(
        self,
        config: BrokerConfig,
        client: Optional[httpx.AsyncClient] = None,
        *,
        ws_connect_factory: Optional[ConnectFactory] = None,
        clock_ms: Optional[Callable[[], int]] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(config, client=client)
        self._ws_connect_factory = ws_connect_factory
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._sleep = sleep
        self._recv_window_ms = int(config.extra.get("recv_window_ms", binance_auth.DEFAULT_RECV_WINDOW_MS))
        self._quote_asset = str(config.extra.get("quote_asset", "USDT"))
        self._kline_page_limit = int(config.extra.get("kline_page_limit", 1000))
        self._filters_cache: dict[str, SymbolFilters] = {}
        # our order id (== Binance clientOrderId) -> (symbol, binance orderId)
        self._order_index: dict[str, tuple[str, int]] = {}
        self._ws_clients: set[BinanceWebSocketClient] = set()

    # -- configuration ---------------------------------------------------

    @property
    def base_url(self) -> str:
        override = self.config.extra.get("base_url")
        if override:
            return str(override)
        if self.config.demo:
            return os.environ.get("BINANCE_TESTNET_URL", self.demo_base_url)
        return os.environ.get("BINANCE_API_URL", self.real_base_url)

    @property
    def ws_base_url(self) -> str:
        override = self.config.extra.get("ws_url")
        if override:
            return str(override)
        if self.config.demo:
            return os.environ.get("BINANCE_TESTNET_WS_URL", self.demo_ws_url)
        return os.environ.get("BINANCE_WS_URL", self.real_ws_url)

    def _auth_headers(self) -> dict[str, str]:
        return binance_auth.auth_headers(self.config.api_key)

    async def _ensure_client(self) -> httpx.AsyncClient:
        # Also stamp X-MBX-APIKEY on *injected* clients (tests, pooled
        # clients); the base class only sets headers on clients it creates.
        client = await super()._ensure_client()
        client.headers.update(self._auth_headers())
        return client

    # -- transport ---------------------------------------------------------

    async def _binance_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        signed: bool = False,
        weight: float = 1.0,
    ) -> Any:
        """One weighted, error-mapped Binance call.

        429/418 drains the shared token bucket, honours ``Retry-After`` once
        (re-signing with a fresh timestamp) and raises
        ``BinanceRateLimitError`` if the broker is still throttling.
        """
        last_rate_limit: Optional[BinanceRateLimitError] = None
        for attempt in range(2):
            await self._rate_limiter.acquire(weight)
            client = await self._ensure_client()
            if signed:
                # The signature covers the exact query string, so it is
                # embedded verbatim in the URL (and rebuilt fresh per attempt
                # so a Retry-After wait can't push the timestamp stale).
                query = binance_auth.signed_query(
                    params or {},
                    self.config.api_secret,
                    timestamp_ms=self._clock_ms(),
                    recv_window_ms=self._recv_window_ms,
                )
                response = await client.request(method, f"{path}?{query}")
            else:
                response = await client.request(method, path, params=params)

            if response.status_code in (429, 418):
                self._rate_limiter.drain()  # broker says stop: empty local burst budget
                retry_after = float(response.headers.get("Retry-After", 1.0))
                last_rate_limit = BinanceRateLimitError(
                    f"binance rate limit (HTTP {response.status_code}), retry after {retry_after}s",
                    retry_after_seconds=retry_after,
                    http_status=response.status_code,
                )
                if attempt == 0:
                    await self._sleep(retry_after)
                    continue
                raise last_rate_limit

            if response.status_code >= 400:
                raise self._map_error(response)
            if response.status_code == 204 or not response.content:
                return {}
            return response.json()
        raise last_rate_limit  # pragma: no cover - loop always returns/raises

    @staticmethod
    def _map_error(response: httpx.Response) -> BinanceAPIError:
        code: Optional[int] = None
        message = f"binance HTTP {response.status_code}"
        try:
            body = response.json()
            code = body.get("code")
            message = f"binance error {code}: {body.get('msg', '')} (HTTP {response.status_code})"
        except ValueError:
            pass
        error_cls = _ERROR_CODE_MAP.get(code, BinanceAPIError) if code is not None else BinanceAPIError
        return error_cls(message, code=code, http_status=response.status_code)

    # -- BrokerConnector interface ----------------------------------------

    async def connect(self) -> None:
        async def attempt() -> None:
            await self._binance_request("GET", "/api/v3/ping", weight=WEIGHTS["ping"])
            self._connected = True

        await reconnect_with_backoff(attempt)

    async def disconnect(self) -> None:
        for ws_client in list(self._ws_clients):
            await ws_client.close()
        self._ws_clients.clear()
        await super().disconnect()

    async def place_order(self, order: Order) -> ExecutionReport:
        binance_type = _ORDER_TYPE_MAP.get(order.order_type)
        if binance_type is None:
            raise OrderRejectedError(f"order type '{order.order_type}' not supported on binance spot")

        filters = await self._get_symbol_filters(order.symbol)
        quantity = floor_to_step(Decimal(str(order.quantity)), filters.step_size)
        if quantity <= 0:
            raise BinanceFilterError(
                f"quantity {order.quantity} rounds to 0 with LOT_SIZE stepSize {filters.step_size}"
            )
        if filters.min_qty is not None and quantity < filters.min_qty:
            raise BinanceFilterError(
                f"quantity {quantity} below LOT_SIZE minQty {filters.min_qty} for {order.symbol}"
            )

        params: dict[str, Any] = {
            "symbol": order.symbol,
            "side": order.side.value.upper(),
            "type": binance_type,
            "quantity": format_decimal(quantity),
            # UUIDs are exactly 36 chars, the Binance clientOrderId maximum.
            "newClientOrderId": str(order.id),
            "newOrderRespType": "FULL",
        }

        price: Optional[Decimal] = None
        if binance_type in ("LIMIT", "STOP_LOSS_LIMIT"):
            if order.price is None:
                raise OrderRejectedError(f"{order.order_type.value} order requires a price")
            price = floor_to_step(Decimal(str(order.price)), filters.tick_size)
            params["price"] = format_decimal(price)
            params["timeInForce"] = "GTC"
        if binance_type in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
            if order.price is None:
                raise OrderRejectedError(f"{order.order_type.value} order requires a price")
            # Our Order model carries a single price: it doubles as stopPrice.
            stop_price = floor_to_step(Decimal(str(order.price)), filters.tick_size)
            params["stopPrice"] = format_decimal(stop_price)

        await self._check_min_notional(order, filters, quantity, price)

        data = await self._binance_request(
            "POST", "/api/v3/order", params=params, signed=True, weight=WEIGHTS["order"]
        )

        if "orderId" in data:
            self._order_index[str(order.id)] = (order.symbol, int(data["orderId"]))
        return ExecutionReport(
            order_id=order.id,
            status=_STATUS_MAP.get(data.get("status", ""), OrderStatus.SUBMITTED),
            filled_quantity=float(data.get("executedQty", 0.0) or 0.0),
            average_fill_price=_average_fill_price(data),
            broker=self.broker_name,
            reported_at=datetime.now(timezone.utc),
            raw=data,
        )

    async def _check_min_notional(
        self,
        order: Order,
        filters: SymbolFilters,
        quantity: Decimal,
        price: Optional[Decimal],
    ) -> None:
        """Local MIN_NOTIONAL pre-flight so obviously-too-small orders fail
        fast with a clear message instead of a broker round-trip + -1013."""
        if filters.min_notional is None:
            return
        reference_price = price
        if reference_price is None:
            if not filters.apply_min_notional_to_market:
                return
            tick = await self.get_book_ticker(order.symbol)
            reference_price = (Decimal(str(tick.bid)) + Decimal(str(tick.ask))) / 2
        notional = quantity * reference_price
        if notional < filters.min_notional:
            raise BinanceFilterError(
                f"order notional {notional} {self._quote_asset} is below minNotional "
                f"{filters.min_notional} for {order.symbol}"
            )

    async def cancel_order(self, order_id: str) -> None:
        indexed = self._order_index.get(order_id)
        if indexed is not None:
            symbol, binance_order_id = indexed
            await self._binance_request(
                "DELETE",
                "/api/v3/order",
                params={"symbol": symbol, "orderId": binance_order_id},
                signed=True,
                weight=WEIGHTS["cancel_order"],
            )
            return
        # Not placed through this instance (restart, another replica):
        # find it among open orders by clientOrderId or exchange orderId.
        for open_order in await self.get_open_orders():
            if order_id in (str(open_order.get("clientOrderId")), str(open_order.get("orderId"))):
                await self._binance_request(
                    "DELETE",
                    "/api/v3/order",
                    params={"symbol": open_order["symbol"], "orderId": open_order["orderId"]},
                    signed=True,
                    weight=WEIGHTS["cancel_order"],
                )
                return
        raise BinanceOrderNotFoundError(
            f"order '{order_id}' not found among binance open orders", code=-2013
        )

    async def get_positions(self) -> list[Position]:
        """Spot holdings derived from account balances (see module docstring).

        ``average_price`` is 0.0: spot balances have no cost basis. Use
        ``get_my_trades(symbol)`` to reconstruct one if a strategy needs it.
        """
        account = await self._binance_request(
            "GET", "/api/v3/account", params={}, signed=True, weight=WEIGHTS["account"]
        )
        positions: list[Position] = []
        for balance in account.get("balances", []):
            asset = balance.get("asset", "")
            total = Decimal(str(balance.get("free", "0"))) + Decimal(str(balance.get("locked", "0")))
            if asset and asset != self._quote_asset and total > 0:
                positions.append(
                    Position(
                        symbol=asset,
                        quantity=float(total),
                        average_price=0.0,
                        unrealized_pnl=0.0,
                        account_id=self.config.account_id,
                    )
                )
        return positions

    async def get_account_state(self) -> AccountState:
        """Quote-asset (default USDT) view of the spot account.

        Spot has no margin: ``margin_used`` maps to the *locked* quote amount
        (funds reserved by open orders) and ``free_margin`` to the free quote
        amount. ``equity`` == ``balance`` because valuing non-quote holdings
        requires per-asset tickers (documented TODO in README-binance.md).
        """
        account = await self._binance_request(
            "GET", "/api/v3/account", params={}, signed=True, weight=WEIGHTS["account"]
        )
        free = locked = Decimal("0")
        for balance in account.get("balances", []):
            if balance.get("asset") == self._quote_asset:
                free = Decimal(str(balance.get("free", "0")))
                locked = Decimal(str(balance.get("locked", "0")))
                break
        total = free + locked
        return AccountState(
            account_id=self.config.account_id,
            balance=float(total),
            equity=float(total),
            margin_used=float(locked),
            free_margin=float(free),
            currency=self._quote_asset,
        )

    async def get_historical_data(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        interval = to_binance_interval(timeframe)
        start_ms = _to_millis(start)
        end_ms = _to_millis(end)
        bars: list[Bar] = []
        while start_ms <= end_ms:
            rows = await self._binance_request(
                "GET",
                "/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": self._kline_page_limit,
                },
                weight=WEIGHTS["klines"],
            )
            bars.extend(_parse_kline(row, symbol, timeframe) for row in rows)
            if len(rows) < self._kline_page_limit:
                break
            start_ms = int(rows[-1][0]) + 1  # next page starts after last open time
        return bars

    async def get_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        """Last ``limit`` klines (no start/end needed) - used by the
        ``/historical?limit=N`` service endpoint."""
        interval = to_binance_interval(timeframe)
        rows = await self._binance_request(
            "GET",
            "/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            weight=WEIGHTS["klines"],
        )
        return [_parse_kline(row, symbol, timeframe) for row in rows]

    async def get_book_ticker(self, symbol: str) -> Tick:
        data = await self._binance_request(
            "GET",
            "/api/v3/ticker/bookTicker",
            params={"symbol": symbol},
            weight=WEIGHTS["book_ticker"],
        )
        return Tick(
            symbol=data["symbol"],
            bid=float(data["bidPrice"]),
            ask=float(data["askPrice"]),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[dict[str, Any]]:
        weight = WEIGHTS["open_orders_symbol"] if symbol else WEIGHTS["open_orders_all"]
        params: dict[str, Any] = {"symbol": symbol} if symbol else {}
        return await self._binance_request(
            "GET", "/api/v3/openOrders", params=params, signed=True, weight=weight
        )

    async def get_my_trades(self, symbol: str, limit: int = 500) -> list[dict[str, Any]]:
        return await self._binance_request(
            "GET",
            "/api/v3/myTrades",
            params={"symbol": symbol, "limit": limit},
            signed=True,
            weight=WEIGHTS["my_trades"],
        )

    # -- streaming ---------------------------------------------------------

    def _make_ws_client(self) -> BinanceWebSocketClient:
        return BinanceWebSocketClient(
            self.ws_base_url,
            connect_factory=self._ws_connect_factory,
            sleep=self._sleep,
        )

    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Top-of-book Ticks over a combined ``<symbol>@bookTicker`` stream."""
        ws_client = self._make_ws_client()
        await ws_client.subscribe([f"{symbol.lower()}@bookTicker" for symbol in symbols])
        self._ws_clients.add(ws_client)
        try:
            async for message in ws_client.messages():
                if isinstance(message, Tick):
                    yield message
        finally:
            self._ws_clients.discard(ws_client)
            await ws_client.close()

    async def stream_bars(self, symbols: list[str], timeframe: str) -> AsyncIterator[Bar]:
        """Closed candles over a combined ``<symbol>@kline_<interval>`` stream."""
        interval = to_binance_interval(timeframe)
        ws_client = self._make_ws_client()
        await ws_client.subscribe([f"{symbol.lower()}@kline_{interval}" for symbol in symbols])
        self._ws_clients.add(ws_client)
        try:
            async for message in ws_client.messages():
                if isinstance(message, Bar):
                    yield message
        finally:
            self._ws_clients.discard(ws_client)
            await ws_client.close()

    @property
    def active_streams(self) -> list[str]:
        streams: set[str] = set()
        for ws_client in self._ws_clients:
            streams.update(ws_client.streams)
        return sorted(streams)

    # -- symbol filters ------------------------------------------------------

    async def _get_symbol_filters(self, symbol: str) -> SymbolFilters:
        cached = self._filters_cache.get(symbol)
        if cached is not None:
            return cached
        data = await self._binance_request(
            "GET",
            "/api/v3/exchangeInfo",
            params={"symbol": symbol},
            weight=WEIGHTS["exchange_info"],
        )
        for symbol_info in data.get("symbols", []):
            parsed = _parse_symbol_filters(symbol_info)
            self._filters_cache[parsed.symbol] = parsed
        if symbol not in self._filters_cache:
            raise BinanceAPIError(f"symbol '{symbol}' not present in binance exchangeInfo")
        return self._filters_cache[symbol]


def _to_millis(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _parse_kline(row: list[Any], symbol: str, timeframe: str) -> Bar:
    """Binance kline row: [openTime, open, high, low, close, volume, closeTime, ...]."""
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        timestamp=datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc),
    )
