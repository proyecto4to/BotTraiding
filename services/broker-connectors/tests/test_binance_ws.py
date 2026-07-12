"""Binance websocket client tests - fake in-process transport, no sockets."""

from __future__ import annotations

import json

import pytest

from app.connectors.binance import BinanceConnector
from app.connectors.binance_ws import BinanceWebSocketClient, parse_stream_message
from app.connectors.http_base import BrokerConfig
from trading_contracts.models import Bar, Tick

from .binance_mocks import (
    BinanceMockAPI,
    FakeConnectFactory,
    FakeWebSocket,
    book_ticker_data,
    combined_frame,
    kline_data,
    make_binance_client,
    no_sleep,
)

BOOK_STREAM = "btcusdt@bookTicker"
KLINE_STREAM = "btcusdt@kline_1m"


def make_ws_client(factory: FakeConnectFactory, **kwargs) -> BinanceWebSocketClient:
    return BinanceWebSocketClient(
        "wss://stream.test.invalid", connect_factory=factory, sleep=no_sleep, **kwargs
    )


# -- parsing -----------------------------------------------------------------


def test_parse_book_ticker_to_tick():
    message = parse_stream_message(book_ticker_data("BTCUSDT", bid="42000.10", ask="42000.20"))
    assert isinstance(message, Tick)
    assert message.symbol == "BTCUSDT"
    assert message.bid == 42000.10
    assert message.ask == 42000.20


def test_parse_closed_kline_to_bar():
    message = parse_stream_message(kline_data("BTCUSDT", "1m", closed=True))
    assert isinstance(message, Bar)
    assert message.symbol == "BTCUSDT"
    assert message.timeframe == "1m"
    assert message.open == 42000.0
    assert message.close == 42050.0
    assert message.volume == 12.5
    assert message.timestamp.timestamp() == 1704067200000 / 1000


def test_open_kline_skipped_unless_requested():
    still_open = kline_data(closed=False)
    assert parse_stream_message(still_open) is None
    assert isinstance(parse_stream_message(still_open, closed_bars_only=False), Bar)


def test_unknown_payload_returns_none():
    assert parse_stream_message({"e": "24hrTicker", "s": "BTCUSDT"}) is None


# -- subscription plumbing ------------------------------------------------


async def test_combined_stream_url_and_subscribe_message_format():
    client = make_ws_client(FakeConnectFactory([]))
    await client.subscribe([BOOK_STREAM, KLINE_STREAM])

    assert client.stream_url() == (
        f"wss://stream.test.invalid/stream?streams={BOOK_STREAM}/{KLINE_STREAM}"
    )
    message = client.build_subscribe_message(client.streams)
    assert message == {"method": "SUBSCRIBE", "params": [BOOK_STREAM, KLINE_STREAM], "id": 1}


async def test_subscribe_frame_sent_on_connect():
    fake = FakeWebSocket([combined_frame(BOOK_STREAM, book_ticker_data())])
    factory = FakeConnectFactory([fake])
    client = make_ws_client(factory)
    await client.subscribe([BOOK_STREAM])

    generator = client.messages()
    tick = await generator.__anext__()
    assert isinstance(tick, Tick)

    subscribe_frames = [m for m in fake.sent_json() if m.get("method") == "SUBSCRIBE"]
    assert subscribe_frames == [{"method": "SUBSCRIBE", "params": [BOOK_STREAM], "id": 1}]
    assert factory.urls == [f"wss://stream.test.invalid/stream?streams={BOOK_STREAM}"]
    await client.close()
    await generator.aclose()


# -- streaming --------------------------------------------------------------


async def test_scripted_frames_parse_to_ticks_and_bars():
    frames = [
        json.dumps({"result": None, "id": 1}),  # subscribe ack: skipped
        json.dumps({"ping": 12345}),  # heartbeat: answered, skipped
        combined_frame(BOOK_STREAM, book_ticker_data(bid="42000.10", ask="42000.20")),
        combined_frame(KLINE_STREAM, kline_data(closed=True)),
    ]
    fake = FakeWebSocket(frames)
    client = make_ws_client(FakeConnectFactory([fake]))
    await client.subscribe([BOOK_STREAM, KLINE_STREAM])

    received = []
    async for message in client.messages():
        received.append(message)
        if len(received) == 2:
            break
    await client.close()

    assert isinstance(received[0], Tick)
    assert isinstance(received[1], Bar)
    assert {"pong": 12345} in fake.sent_json()  # heartbeat answered


async def test_reconnects_and_resubscribes_after_drop():
    first = FakeWebSocket([combined_frame(BOOK_STREAM, book_ticker_data(bid="1.0"))], drop_at_end=True)
    second = FakeWebSocket([combined_frame(BOOK_STREAM, book_ticker_data(bid="2.0"))])
    factory = FakeConnectFactory([first, second])
    client = make_ws_client(factory)
    await client.subscribe([BOOK_STREAM])

    received = []
    async for message in client.messages():
        received.append(message)
        if len(received) == 2:
            break
    await client.close()

    assert [t.bid for t in received] == [1.0, 2.0]
    assert len(factory.urls) == 2  # reconnected once
    assert all(url.endswith(f"streams={BOOK_STREAM}") for url in factory.urls)
    resubscribe = [m for m in second.sent_json() if m.get("method") == "SUBSCRIBE"]
    assert len(resubscribe) == 1 and resubscribe[0]["params"] == [BOOK_STREAM]


async def test_close_stops_iteration_cleanly():
    fake = FakeWebSocket([combined_frame(BOOK_STREAM, book_ticker_data())])
    client = make_ws_client(FakeConnectFactory([fake]))
    await client.subscribe([BOOK_STREAM])

    generator = client.messages()
    assert isinstance(await generator.__anext__(), Tick)
    await client.close()
    with pytest.raises(StopAsyncIteration):
        await generator.__anext__()
    assert fake.closed


async def test_messages_requires_a_subscription():
    client = make_ws_client(FakeConnectFactory([]))
    generator = client.messages()
    with pytest.raises(ValueError, match="subscribe"):
        await generator.__anext__()


# -- connector wiring ----------------------------------------------------------


def make_streaming_connector(factory: FakeConnectFactory) -> BinanceConnector:
    config = BrokerConfig(broker="binance", api_key="k", api_secret="s", demo=True)
    return BinanceConnector(
        config,
        client=make_binance_client(BinanceMockAPI()),
        ws_connect_factory=factory,
        sleep=no_sleep,
    )


async def test_stream_market_data_yields_ticks_from_websocket():
    frames = [
        combined_frame(BOOK_STREAM, book_ticker_data(bid="10.0")),
        combined_frame(KLINE_STREAM, kline_data()),  # non-Tick: filtered out
        combined_frame(BOOK_STREAM, book_ticker_data(bid="11.0")),
    ]
    factory = FakeConnectFactory([FakeWebSocket(frames)])
    connector = make_streaming_connector(factory)

    generator = connector.stream_market_data(["BTCUSDT"])
    first = await generator.__anext__()
    assert connector.active_streams == [BOOK_STREAM]  # visible while streaming
    second = await generator.__anext__()
    await generator.aclose()

    assert (first.bid, second.bid) == (10.0, 11.0)
    assert connector.active_streams == []  # cleaned up on shutdown
    assert factory.urls[0] == f"wss://stream.testnet.binance.vision/stream?streams={BOOK_STREAM}"


async def test_stream_bars_yields_closed_bars_only():
    frames = [
        combined_frame(KLINE_STREAM, kline_data(closed=False)),
        combined_frame(KLINE_STREAM, kline_data(closed=True)),
    ]
    factory = FakeConnectFactory([FakeWebSocket(frames)])
    connector = make_streaming_connector(factory)

    generator = connector.stream_bars(["BTCUSDT"], "1m")
    bar = await generator.__anext__()
    await generator.aclose()

    assert isinstance(bar, Bar)
    assert bar.timeframe == "1m"
    assert factory.urls[0].endswith(f"streams={KLINE_STREAM}")
