"""BinanceConnector REST tests - all against an in-process mock, no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.connectors import binance_auth
from app.connectors.binance import (
    BinanceAPIError,
    BinanceConnector,
    BinanceFilterError,
    BinanceInsufficientBalanceError,
    BinanceOrderNotFoundError,
    BinanceRateLimitError,
    BinanceTimestampError,
    floor_to_step,
    format_decimal,
    to_binance_interval,
)
from app.connectors.errors import OrderRejectedError, UnsupportedTimeframeError
from app.connectors.http_base import BrokerConfig
from trading_contracts.models import ExecutionMode, Order, OrderSide, OrderStatus, OrderType

from .binance_mocks import (
    DEFAULT_KLINE_ROWS,
    BinanceMockAPI,
    binance_error,
    make_binance_client,
    no_sleep,
)


@pytest.fixture(autouse=True)
def _clean_binance_env(monkeypatch):
    for var in ("BINANCE_API_URL", "BINANCE_TESTNET_URL", "BINANCE_WS_URL", "BINANCE_TESTNET_WS_URL"):
        monkeypatch.delenv(var, raising=False)


def make_connector(
    mock_api: BinanceMockAPI | None = None,
    *,
    demo: bool = True,
    extra: dict | None = None,
    sleep=no_sleep,
    clock_ms=lambda: 1700000000000,
    api_key: str = "test-key",
    api_secret: str = "test-secret",
) -> tuple[BinanceConnector, BinanceMockAPI]:
    mock_api = mock_api or BinanceMockAPI()
    config = BrokerConfig(
        broker="binance", api_key=api_key, api_secret=api_secret, demo=demo, extra=extra
    )
    connector = BinanceConnector(
        config, client=make_binance_client(mock_api), sleep=sleep, clock_ms=clock_ms
    )
    return connector, mock_api


def make_order(
    quantity: float = 0.12345678,
    order_type: OrderType = OrderType.MARKET,
    price: float | None = None,
    side: OrderSide = OrderSide.BUY,
    symbol: str = "BTCUSDT",
) -> Order:
    return Order(
        id=uuid4(),
        signal_id=uuid4(),
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        price=price,
        broker="binance",
        account_id="default",
        execution_mode=ExecutionMode.PAPER,
        created_at=datetime.now(timezone.utc),
    )


# -- interval mapping ---------------------------------------------------


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        ("1m", "1m"),
        ("15m", "15m"),
        ("1h", "1h"),
        ("60m", "1h"),
        ("60min", "1h"),
        ("15min", "15m"),
        ("M15", "15m"),
        ("H4", "4h"),
        ("240m", "4h"),
        ("1D", "1d"),
        ("D1", "1d"),
        ("1w", "1w"),
        ("1M", "1M"),  # month must survive case-sensitively (1m == minute)
        ("1mo", "1M"),
    ],
)
def test_interval_mapping(timeframe, expected):
    assert to_binance_interval(timeframe) == expected


@pytest.mark.parametrize("timeframe", ["7m", "2w", "tick", ""])
def test_interval_mapping_rejects_unknown(timeframe):
    with pytest.raises(UnsupportedTimeframeError):
        to_binance_interval(timeframe)


# -- base URL selection ----------------------------------------------------


def test_demo_targets_testnet_and_real_targets_production():
    demo, _ = make_connector(demo=True)
    real, _ = make_connector(demo=False)
    assert demo.base_url == "https://testnet.binance.vision"
    assert real.base_url == "https://api.binance.com"
    assert demo.ws_base_url == "wss://stream.testnet.binance.vision"
    assert real.ws_base_url == "wss://stream.binance.com:9443"


def test_env_vars_override_base_urls(monkeypatch):
    monkeypatch.setenv("BINANCE_TESTNET_URL", "https://testnet.proxy.local")
    monkeypatch.setenv("BINANCE_API_URL", "https://api.proxy.local")
    monkeypatch.setenv("BINANCE_TESTNET_WS_URL", "wss://testnet-ws.proxy.local")
    monkeypatch.setenv("BINANCE_WS_URL", "wss://ws.proxy.local")
    demo, _ = make_connector(demo=True)
    real, _ = make_connector(demo=False)
    assert demo.base_url == "https://testnet.proxy.local"
    assert real.base_url == "https://api.proxy.local"
    assert demo.ws_base_url == "wss://testnet-ws.proxy.local"
    assert real.ws_base_url == "wss://ws.proxy.local"


def test_config_extra_overrides_env(monkeypatch):
    monkeypatch.setenv("BINANCE_API_URL", "https://api.proxy.local")
    connector, _ = make_connector(
        demo=False, extra={"base_url": "https://custom.local", "ws_url": "wss://custom-ws.local"}
    )
    assert connector.base_url == "https://custom.local"
    assert connector.ws_base_url == "wss://custom-ws.local"


# -- connect ---------------------------------------------------------------


async def test_connect_pings_api_v3_ping():
    connector, mock_api = make_connector()
    assert not connector.is_connected()
    await connector.connect()
    assert connector.is_connected()
    assert len(mock_api.requests_for("GET", "/api/v3/ping")) == 1


# -- klines / historical -----------------------------------------------------


async def test_klines_parse_to_bars():
    connector, mock_api = make_connector()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)

    bars = await connector.get_historical_data("BTCUSDT", "1h", start, end)

    assert len(bars) == 2
    first = bars[0]
    assert first.symbol == "BTCUSDT"
    assert first.timeframe == "1h"
    assert first.open == 42000.0
    assert first.high == 42500.0
    assert first.low == 41900.0
    assert first.close == 42250.0
    assert first.volume == 123.456
    assert first.timestamp == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    request = mock_api.requests_for("GET", "/api/v3/klines")[0]
    assert request.url.params["symbol"] == "BTCUSDT"
    assert request.url.params["interval"] == "1h"
    assert request.url.params["startTime"] == str(int(start.timestamp() * 1000))
    assert request.url.params["endTime"] == str(int(end.timestamp() * 1000))


async def test_klines_paginate_until_range_covered():
    mock_api = BinanceMockAPI()
    t0, t1, t2 = 1704067200000, 1704070800000, 1704074400000
    page1 = [DEFAULT_KLINE_ROWS[0], DEFAULT_KLINE_ROWS[1]]
    page2 = [[t2, "42400.00", "42700.00", "42300.00", "42600.00", "55.5", t2 + 3599999, "0", 1, "0", "0", "0"]]

    def klines_route(request: httpx.Request) -> httpx.Response:
        start_time = int(request.url.params["startTime"])
        return httpx.Response(200, json=page1 if start_time <= t0 else page2)

    mock_api.routes[("GET", "/api/v3/klines")] = klines_route
    connector, _ = make_connector(mock_api, extra={"kline_page_limit": 2})

    start = datetime.fromtimestamp(t0 / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(t2 / 1000, tz=timezone.utc)
    bars = await connector.get_historical_data("BTCUSDT", "1h", start, end)

    assert len(bars) == 3
    kline_requests = mock_api.requests_for("GET", "/api/v3/klines")
    assert len(kline_requests) == 2
    assert kline_requests[1].url.params["startTime"] == str(t1 + 1)


async def test_get_recent_bars_uses_limit_only():
    connector, mock_api = make_connector()
    bars = await connector.get_recent_bars("BTCUSDT", "1h", limit=1)
    assert len(bars) == 1
    request = mock_api.requests_for("GET", "/api/v3/klines")[0]
    assert request.url.params["limit"] == "1"
    assert "startTime" not in request.url.params


async def test_historical_rejects_unknown_timeframe():
    connector, _ = make_connector()
    with pytest.raises(UnsupportedTimeframeError):
        await connector.get_historical_data(
            "BTCUSDT", "13m", datetime.now(timezone.utc), datetime.now(timezone.utc)
        )


async def test_book_ticker_maps_to_tick():
    connector, _ = make_connector()
    tick = await connector.get_book_ticker("BTCUSDT")
    assert tick.symbol == "BTCUSDT"
    assert tick.bid == 100.0
    assert tick.ask == 100.1


# -- order placement -----------------------------------------------------------


async def test_market_order_params_rounding_and_report():
    connector, mock_api = make_connector()
    order = make_order(quantity=0.12345678)

    report = await connector.place_order(order)

    request = mock_api.requests_for("POST", "/api/v3/order")[0]
    params = request.url.params
    assert params["symbol"] == "BTCUSDT"
    assert params["side"] == "BUY"
    assert params["type"] == "MARKET"
    assert params["quantity"] == "0.1234"  # floored to LOT_SIZE stepSize 0.0001
    assert params["newClientOrderId"] == str(order.id)
    assert params["newOrderRespType"] == "FULL"
    assert params["recvWindow"] == "5000"
    assert params["timestamp"] == "1700000000000"
    assert request.headers["X-MBX-APIKEY"] == "test-key"

    # The signature must cover the exact transmitted query string.
    query = request.url.query.decode()
    payload, _, signature = query.partition("&signature=")
    assert signature == binance_auth.sign_payload(payload, "test-secret")

    assert report.order_id == order.id
    assert report.status == OrderStatus.FILLED
    assert report.filled_quantity == 0.1234
    assert report.average_fill_price == 100.0
    assert report.broker == "binance"


async def test_limit_order_price_floored_to_tick_size():
    connector, mock_api = make_connector()
    order = make_order(quantity=0.5, order_type=OrderType.LIMIT, price=42000.567)

    await connector.place_order(order)

    params = mock_api.requests_for("POST", "/api/v3/order")[0].url.params
    assert params["type"] == "LIMIT"
    assert params["price"] == "42000.56"  # floored to PRICE_FILTER tickSize 0.01
    assert params["timeInForce"] == "GTC"


async def test_limit_order_below_min_notional_rejected_locally():
    connector, mock_api = make_connector()
    order = make_order(quantity=0.0001, order_type=OrderType.LIMIT, price=50.0)

    with pytest.raises(BinanceFilterError, match="minNotional"):
        await connector.place_order(order)

    assert mock_api.requests_for("POST", "/api/v3/order") == []  # never reached the broker


async def test_market_order_min_notional_checked_against_book_ticker():
    mock_api = BinanceMockAPI()
    mock_api.exchange_info = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.00010000", "stepSize": "0.00010000"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "NOTIONAL", "minNotional": "10.0", "applyMinToMarket": True},
                ],
            }
        ]
    }
    connector, _ = make_connector(mock_api)
    order = make_order(quantity=0.0001)  # ~100.05 mid -> notional ~0.01 << 10

    with pytest.raises(BinanceFilterError, match="minNotional"):
        await connector.place_order(order)

    assert len(mock_api.requests_for("GET", "/api/v3/ticker/bookTicker")) == 1
    assert mock_api.requests_for("POST", "/api/v3/order") == []


async def test_legacy_min_notional_filter_type_supported():
    mock_api = BinanceMockAPI()
    mock_api.exchange_info = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.00010000", "stepSize": "0.00010000"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "10.0", "applyToMarket": False},
                ],
            }
        ]
    }
    connector, mock_api = make_connector(mock_api)
    with pytest.raises(BinanceFilterError, match="minNotional"):
        await connector.place_order(make_order(quantity=0.0001, order_type=OrderType.LIMIT, price=50.0))


async def test_limit_order_without_price_rejected():
    connector, _ = make_connector()
    with pytest.raises(OrderRejectedError, match="requires a price"):
        await connector.place_order(make_order(order_type=OrderType.LIMIT, price=None))


async def test_quantity_rounding_to_zero_rejected():
    connector, _ = make_connector()
    with pytest.raises(BinanceFilterError, match="rounds to 0"):
        await connector.place_order(make_order(quantity=0.00005))  # below stepSize


async def test_exchange_info_fetched_once_and_cached():
    connector, mock_api = make_connector()
    await connector.place_order(make_order())
    await connector.place_order(make_order())
    assert len(mock_api.requests_for("GET", "/api/v3/exchangeInfo")) == 1


# -- error code mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected_error"),
    [
        (-1013, BinanceFilterError),
        (-2010, BinanceInsufficientBalanceError),
        (-1021, BinanceTimestampError),
        (-2013, BinanceOrderNotFoundError),
        (-1000, BinanceAPIError),
    ],
)
async def test_binance_error_codes_map_to_typed_exceptions(code, expected_error):
    mock_api = BinanceMockAPI()
    mock_api.routes[("POST", "/api/v3/order")] = binance_error(400, code, "mock failure")
    connector, _ = make_connector(mock_api)

    with pytest.raises(expected_error) as exc_info:
        await connector.place_order(make_order())
    assert exc_info.value.code == code
    assert exc_info.value.http_status == 400


async def test_cancel_rejected_maps_to_order_not_found():
    connector, mock_api = make_connector()
    order = make_order()
    await connector.place_order(order)
    mock_api.routes[("DELETE", "/api/v3/order")] = binance_error(400, -2011, "Unknown order sent.")

    with pytest.raises(BinanceOrderNotFoundError):
        await connector.cancel_order(str(order.id))


# -- rate limiting -----------------------------------------------------------


async def test_429_honours_retry_after_and_drains_bucket():
    mock_api = BinanceMockAPI()
    calls = {"n": 0}

    def flaky_klines(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"Retry-After": "3"}, json={"code": -1003, "msg": "Too many requests."}
            )
        return httpx.Response(200, json=DEFAULT_KLINE_ROWS[:1])

    mock_api.routes[("GET", "/api/v3/klines")] = flaky_klines
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    connector, _ = make_connector(mock_api, sleep=record_sleep)
    bars = await connector.get_recent_bars("BTCUSDT", "1h", limit=1)

    assert len(bars) == 1
    assert sleeps == [3.0]  # Retry-After honoured
    assert calls["n"] == 2
    # 429 drained the token bucket (capacity 1200): only refill trickle remains.
    assert connector._rate_limiter.available_tokens() < 5


@pytest.mark.parametrize("status", [429, 418])
async def test_persistent_rate_limiting_raises_typed_error(status):
    mock_api = BinanceMockAPI()

    def always_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"Retry-After": "7"}, json={"code": -1003, "msg": "banned"})

    mock_api.routes[("GET", "/api/v3/klines")] = always_limited
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    connector, _ = make_connector(mock_api, sleep=record_sleep)

    with pytest.raises(BinanceRateLimitError) as exc_info:
        await connector.get_recent_bars("BTCUSDT", "1h", limit=1)
    assert exc_info.value.retry_after_seconds == 7.0
    assert exc_info.value.http_status == status
    assert sleeps == [7.0]  # slept once, retried once, then surfaced the error


# -- cancel ---------------------------------------------------------------


async def test_cancel_uses_indexed_symbol_and_order_id():
    connector, mock_api = make_connector()
    order = make_order()
    await connector.place_order(order)

    await connector.cancel_order(str(order.id))

    cancel_request = mock_api.requests_for("DELETE", "/api/v3/order")[0]
    assert cancel_request.url.params["symbol"] == "BTCUSDT"
    assert cancel_request.url.params["orderId"] == "1001"  # mock's first orderId
    assert "signature" in cancel_request.url.params


async def test_cancel_unknown_id_falls_back_to_open_orders():
    mock_api = BinanceMockAPI()
    mock_api.open_orders = [{"symbol": "ETHUSDT", "orderId": 777, "clientOrderId": "ext-1"}]
    connector, _ = make_connector(mock_api)

    await connector.cancel_order("ext-1")

    assert len(mock_api.requests_for("GET", "/api/v3/openOrders")) == 1
    cancel_request = mock_api.requests_for("DELETE", "/api/v3/order")[0]
    assert cancel_request.url.params["symbol"] == "ETHUSDT"
    assert cancel_request.url.params["orderId"] == "777"


async def test_cancel_missing_everywhere_raises_not_found():
    connector, _ = make_connector()
    with pytest.raises(BinanceOrderNotFoundError):
        await connector.cancel_order("never-existed")


# -- account / positions ---------------------------------------------------


async def test_account_state_reports_quote_asset_view():
    connector, mock_api = make_connector()
    state = await connector.get_account_state()

    assert state.balance == 1010.0  # USDT free 1000 + locked 10
    assert state.equity == 1010.0
    assert state.margin_used == 10.0  # locked by open orders
    assert state.free_margin == 1000.0
    assert state.currency == "USDT"
    request = mock_api.requests_for("GET", "/api/v3/account")[0]
    assert "signature" in request.url.params


async def test_positions_derived_from_balances_excluding_quote_and_zero():
    connector, _ = make_connector()
    positions = await connector.get_positions()

    assert len(positions) == 1  # BTC only: USDT is quote, ETH balance is zero
    position = positions[0]
    assert position.symbol == "BTC"
    assert position.quantity == 0.5
    assert position.average_price == 0.0  # spot balances carry no cost basis
    assert position.account_id == "default"


async def test_quote_asset_configurable():
    connector, _ = make_connector(extra={"quote_asset": "BTC"})
    state = await connector.get_account_state()
    assert state.currency == "BTC"
    assert state.balance == 0.5
    positions = await connector.get_positions()
    assert {p.symbol for p in positions} == {"USDT"}  # BTC is now the quote


# -- helpers ---------------------------------------------------------------


def test_floor_to_step_and_formatting():
    assert format_decimal(floor_to_step(Decimal("0.12345678"), Decimal("0.0001"))) == "0.1234"
    assert format_decimal(floor_to_step(Decimal("42000.567"), Decimal("0.01"))) == "42000.56"
    assert format_decimal(floor_to_step(Decimal("5.7"), Decimal("1"))) == "5"
    assert format_decimal(floor_to_step(Decimal("5.7"), None)) == "5.7"
