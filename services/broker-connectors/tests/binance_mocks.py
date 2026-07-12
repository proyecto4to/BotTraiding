"""Binance-shaped mock transports for tests. No network anywhere.

* ``BinanceMockAPI``: an httpx.MockTransport handler serving canonical
  Binance REST responses (exchangeInfo/klines/order/account/...), recording
  every request; individual routes are overridable per test via ``routes``.
* ``FakeWebSocket`` / ``FakeConnectFactory``: in-process stand-ins for the
  ``websockets`` transport, yielding scripted frames and optionally dropping
  the connection to exercise reconnect logic.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

import httpx

# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

DEFAULT_EXCHANGE_INFO: dict[str, Any] = {
    "timezone": "UTC",
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "1000000.00", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "minQty": "0.00010000", "maxQty": "9000.00000000", "stepSize": "0.00010000"},
                {"filterType": "NOTIONAL", "minNotional": "10.00000000", "applyMinToMarket": False},
            ],
        }
    ],
}

# [openTime, open, high, low, close, volume, closeTime, quoteVol, trades, takerBase, takerQuote, ignore]
DEFAULT_KLINE_ROWS: list[list[Any]] = [
    [1704067200000, "42000.00", "42500.00", "41900.00", "42250.00", "123.456", 1704070799999, "5.2e6", 1000, "60.0", "2.5e6", "0"],
    [1704070800000, "42250.00", "42600.00", "42100.00", "42400.00", "98.765", 1704074399999, "4.1e6", 900, "50.0", "2.1e6", "0"],
]

DEFAULT_ACCOUNT: dict[str, Any] = {
    "accountType": "SPOT",
    "balances": [
        {"asset": "USDT", "free": "1000.00000000", "locked": "10.00000000"},
        {"asset": "BTC", "free": "0.50000000", "locked": "0.00000000"},
        {"asset": "ETH", "free": "0.00000000", "locked": "0.00000000"},
    ],
}


class BinanceMockAPI:
    """Callable httpx handler that mimics the Binance spot REST API."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.exchange_info = DEFAULT_EXCHANGE_INFO
        self.kline_rows = DEFAULT_KLINE_ROWS
        self.account = DEFAULT_ACCOUNT
        self.open_orders: list[dict[str, Any]] = []
        self.my_trades: list[dict[str, Any]] = []
        self.next_order_id = 1000
        # (METHOD, path) -> handler(request) -> httpx.Response; overrides defaults.
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}

    def requests_for(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        override = self.routes.get((request.method, request.url.path))
        if override is not None:
            return override(request)
        return self._default_route(request)

    def _default_route(self, request: httpx.Request) -> httpx.Response:
        method, path, params = request.method, request.url.path, request.url.params

        if path == "/api/v3/ping":
            return httpx.Response(200, json={})
        if path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json=self.exchange_info)
        if path == "/api/v3/klines":
            limit = int(params.get("limit", "500"))
            return httpx.Response(200, json=self.kline_rows[:limit])
        if path == "/api/v3/ticker/bookTicker":
            return httpx.Response(
                200,
                json={
                    "symbol": params.get("symbol", "BTCUSDT"),
                    "bidPrice": "100.00000000",
                    "bidQty": "5.00000000",
                    "askPrice": "100.10000000",
                    "askQty": "5.00000000",
                },
            )
        if path == "/api/v3/order" and method == "POST":
            return self._place_order(params)
        if path == "/api/v3/order" and method == "DELETE":
            return httpx.Response(
                200,
                json={
                    "symbol": params.get("symbol"),
                    "orderId": int(params.get("orderId", "0")),
                    "status": "CANCELED",
                },
            )
        if path == "/api/v3/account":
            return httpx.Response(200, json=self.account)
        if path == "/api/v3/openOrders":
            return httpx.Response(200, json=self.open_orders)
        if path == "/api/v3/myTrades":
            return httpx.Response(200, json=self.my_trades)
        return httpx.Response(404, json={"code": -1121, "msg": f"no mock route for {method} {path}"})

    def _place_order(self, params: httpx.QueryParams) -> httpx.Response:
        quantity = params.get("quantity", "1")
        self.next_order_id += 1
        return httpx.Response(
            200,
            json={
                "symbol": params.get("symbol"),
                "orderId": self.next_order_id,
                "orderListId": -1,
                "clientOrderId": params.get("newClientOrderId"),
                "transactTime": 1704067200000,
                "price": params.get("price", "0.00000000"),
                "origQty": quantity,
                "executedQty": quantity,
                "cummulativeQuoteQty": str(float(quantity) * 100.0),
                "status": "FILLED",
                "timeInForce": params.get("timeInForce", "GTC"),
                "type": params.get("type"),
                "side": params.get("side"),
                "fills": [
                    {
                        "price": "100.00000000",
                        "qty": quantity,
                        "commission": "0.00000000",
                        "commissionAsset": "USDT",
                        "tradeId": 1,
                    }
                ],
            },
        )


def make_binance_client(mock_api: BinanceMockAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(mock_api), base_url="https://binance.mock.invalid"
    )


def binance_error(status: int, code: int, msg: str) -> Callable[[httpx.Request], httpx.Response]:
    """Route override returning a Binance ``{"code", "msg"}`` error body."""

    def route(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "msg": msg})

    return route


# ---------------------------------------------------------------------------
# Websocket fakes
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Scripted in-process websocket: yields ``frames`` then either closes
    cleanly or 'drops' (raises), letting tests exercise reconnect paths."""

    def __init__(self, frames: list[str], *, drop_at_end: bool = False) -> None:
        self._frames = list(frames)
        self._drop_at_end = drop_at_end
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        if self._drop_at_end:
            self._drop_at_end = False  # drop once, then behave closed
            raise ConnectionError("fake connection dropped")
        raise StopAsyncIteration

    def sent_json(self) -> list[Any]:
        return [json.loads(m) for m in self.sent]


class FakeConnectFactory:
    """Hands out pre-built fake sockets in order; records requested URLs."""

    def __init__(self, sockets: list[FakeWebSocket]) -> None:
        self._sockets = list(sockets)
        self.urls: list[str] = []

    async def __call__(self, url: str) -> FakeWebSocket:
        self.urls.append(url)
        if not self._sockets:
            raise ConnectionError("fake factory has no more sockets")
        return self._sockets.pop(0)


def combined_frame(stream: str, data: dict[str, Any]) -> str:
    return json.dumps({"stream": stream, "data": data})


def book_ticker_data(symbol: str = "BTCUSDT", bid: str = "42000.10", ask: str = "42000.20") -> dict[str, Any]:
    return {"u": 400900217, "s": symbol, "b": bid, "B": "31.2", "a": ask, "A": "40.6"}


def kline_data(
    symbol: str = "BTCUSDT",
    interval: str = "1m",
    *,
    closed: bool = True,
    open_time: int = 1704067200000,
    open_: str = "42000.00",
    high: str = "42100.00",
    low: str = "41950.00",
    close: str = "42050.00",
    volume: str = "12.5",
) -> dict[str, Any]:
    return {
        "e": "kline",
        "E": open_time + 59999,
        "s": symbol,
        "k": {
            "t": open_time,
            "T": open_time + 59999,
            "s": symbol,
            "i": interval,
            "o": open_,
            "c": close,
            "h": high,
            "l": low,
            "v": volume,
            "x": closed,
        },
    }


async def no_sleep(_: float) -> None:
    """Injectable no-op sleep so backoff/Retry-After tests run instantly."""
    return None
