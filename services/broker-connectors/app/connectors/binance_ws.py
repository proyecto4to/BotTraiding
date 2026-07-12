"""Binance combined-stream websocket client.

Streams ``<symbol>@bookTicker`` (top-of-book -> shared ``Tick``) and
``<symbol>@kline_<interval>`` (candles -> shared ``Bar``) over a single
combined-stream connection (``/stream?streams=a/b/c``).

Design notes:

* **Injectable transport.** ``connect_factory`` is any
  ``async (url) -> websocket-like`` callable; the default uses the
  ``websockets`` library. Tests inject a factory returning an in-process
  fake that yields scripted frames, so no test ever opens a socket.
  A "websocket-like" object only needs: ``async for frame in ws``,
  ``await ws.send(str)`` and ``await ws.close()``.
* **Reconnect + resubscribe.** A dropped connection is re-established via
  the shared ``reconnect_with_backoff`` helper. The combined-stream URL
  already encodes the subscriptions, and we additionally send a SUBSCRIBE
  frame after every (re)connect so streams added at runtime survive drops.
* **Heartbeat.** Binance pings at the websocket protocol level; the
  ``websockets`` library answers those automatically (``ping_interval`` /
  ``ping_timeout`` below). As a belt-and-braces measure - and so fakes can
  exercise the path - JSON ``{"ping": ...}`` frames are answered with
  ``{"pong": ...}``.
* **Clean shutdown.** ``close()`` stops the iteration loop and closes the
  underlying socket; ``messages()`` then returns instead of reconnecting.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Union

from trading_contracts.models import Bar, Tick

from ..reconnect import reconnect_with_backoff

logger = logging.getLogger(__name__)

# Minimal protocol needed from a websocket implementation (or a test fake):
# async iteration over incoming frames, ``send()`` and ``close()``.
WebSocketLike = Any
ConnectFactory = Callable[[str], Awaitable[WebSocketLike]]


async def default_connect(url: str) -> WebSocketLike:
    """Real transport: the ``websockets`` library with protocol-level heartbeats."""
    import websockets  # imported lazily so unit tests never require a socket

    return await websockets.connect(url, ping_interval=20, ping_timeout=20)


def parse_stream_message(
    data: dict[str, Any], *, closed_bars_only: bool = True
) -> Optional[Union[Tick, Bar]]:
    """Map one Binance stream payload to a shared ``Tick`` or ``Bar``.

    Returns ``None`` for frames that don't map to a market-data model
    (subscription acks, still-open candles when ``closed_bars_only``...).
    """
    if data.get("e") == "kline" and isinstance(data.get("k"), dict):
        k = data["k"]
        if closed_bars_only and not k.get("x", False):
            return None
        return Bar(
            symbol=k.get("s", data.get("s", "")),
            timeframe=k["i"],
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            timestamp=datetime.fromtimestamp(k["t"] / 1000.0, tz=timezone.utc),
        )

    # Spot bookTicker frames carry no event type/time: identify by shape.
    if "s" in data and "b" in data and "a" in data:
        return Tick(
            symbol=data["s"],
            bid=float(data["b"]),
            ask=float(data["a"]),
            timestamp=datetime.now(timezone.utc),
        )

    return None


class BinanceWebSocketClient:
    """One combined-stream connection with reconnect/resubscribe semantics."""

    def __init__(
        self,
        base_url: str,
        *,
        connect_factory: Optional[ConnectFactory] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        closed_bars_only: bool = True,
        max_reconnect_attempts: int = 5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._connect_factory = connect_factory or default_connect
        self._sleep = sleep
        self._closed_bars_only = closed_bars_only
        self._max_reconnect_attempts = max_reconnect_attempts
        self._streams: list[str] = []
        self._ws: Optional[WebSocketLike] = None
        self._closed = False
        self._message_id = 0

    # -- subscription management --------------------------------------

    @property
    def streams(self) -> list[str]:
        return list(self._streams)

    def stream_url(self) -> str:
        return f"{self._base_url}/stream?streams={'/'.join(self._streams)}"

    def build_subscribe_message(self, streams: list[str]) -> dict[str, Any]:
        """Live-subscription frame per Binance spec:
        ``{"method": "SUBSCRIBE", "params": [...], "id": n}``."""
        self._message_id += 1
        return {"method": "SUBSCRIBE", "params": list(streams), "id": self._message_id}

    async def subscribe(self, streams: list[str]) -> None:
        new_streams = [s for s in streams if s not in self._streams]
        self._streams.extend(new_streams)
        if self._ws is not None and new_streams:
            await self._ws.send(json.dumps(self.build_subscribe_message(new_streams)))

    # -- connection lifecycle ------------------------------------------

    async def _connect(self) -> None:
        async def attempt() -> WebSocketLike:
            return await self._connect_factory(self.stream_url())

        self._ws = await reconnect_with_backoff(
            attempt, max_attempts=self._max_reconnect_attempts, sleep=self._sleep
        )
        # Resubscribe everything: the combined URL covers the initial set,
        # the explicit frame covers streams subscribed after connect.
        if self._streams:
            await self._ws.send(json.dumps(self.build_subscribe_message(self._streams)))

    async def close(self) -> None:
        self._closed = True
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - best-effort close on shutdown
                logger.debug("error closing binance websocket", exc_info=True)

    # -- streaming ------------------------------------------------------

    async def messages(self) -> AsyncIterator[Union[Tick, Bar]]:
        """Yield parsed Ticks/Bars forever, reconnecting on transport drops.

        Terminates only via ``close()`` (clean shutdown) or when reconnect
        attempts are exhausted (``ReconnectError`` propagates).
        """
        if not self._streams:
            raise ValueError("subscribe() to at least one stream before iterating")
        while not self._closed:
            if self._ws is None:
                await self._connect()
            try:
                async for raw_frame in self._ws:
                    parsed = await self._handle_frame(raw_frame)
                    if parsed is not None:
                        yield parsed
                # Iterator exhausted = server closed the connection politely.
                self._ws = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any transport error triggers reconnect
                if self._closed:
                    return
                logger.warning("binance websocket dropped (%s); reconnecting", exc)
                self._ws = None

    async def _handle_frame(self, raw_frame: Union[str, bytes]) -> Optional[Union[Tick, Bar]]:
        if isinstance(raw_frame, (bytes, bytearray)):
            raw_frame = raw_frame.decode("utf-8")
        try:
            payload = json.loads(raw_frame)
        except (TypeError, ValueError):
            logger.debug("ignoring non-JSON websocket frame: %r", raw_frame)
            return None
        if not isinstance(payload, dict):
            return None
        if "ping" in payload:  # JSON-level heartbeat (protocol pings handled by the library)
            if self._ws is not None:
                await self._ws.send(json.dumps({"pong": payload["ping"]}))
            return None
        if "result" in payload and "id" in payload:  # SUBSCRIBE/UNSUBSCRIBE ack
            return None
        data = payload.get("data") if "stream" in payload else payload
        if not isinstance(data, dict):
            return None
        return parse_stream_message(data, closed_bars_only=self._closed_bars_only)
