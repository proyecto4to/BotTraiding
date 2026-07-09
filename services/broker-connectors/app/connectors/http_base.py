"""Shared HTTP-transport connector base class.

Every REST-based broker connector (all of them except MetaTrader5, which
talks to a local terminal process instead of HTTP) subclasses
``BaseHTTPConnector`` and only needs to set ``broker_name``, the
demo/real base URLs, and override ``_auth_headers`` for its auth scheme.
This avoids re-implementing connect/reconnect/rate-limiting/CRUD wiring in
every one of the 8 connector modules.

All network calls go through an injectable ``httpx.AsyncClient`` (the
``client`` constructor argument) so tests can pass a mocked transport and
never hit the network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, AsyncIterator, Optional

import httpx

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


class BrokerConfig:
    """Connection configuration for a single broker/account pair.

    Holds credentials only in memory for the lifetime of the connector
    instance; never logged (see ``__repr__``).
    """

    def __init__(
        self,
        broker: str,
        api_key: str = "",
        api_secret: str = "",
        demo: bool = True,
        account_id: str = "default",
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        self.broker = broker
        self.api_key = api_key
        self.api_secret = api_secret
        self.demo = demo
        self.account_id = account_id
        self.extra = extra or {}

    def __repr__(self) -> str:
        return (
            f"BrokerConfig(broker={self.broker!r}, account_id={self.account_id!r}, "
            f"demo={self.demo}, api_key='***', api_secret='***')"
        )

    __str__ = __repr__


class BaseHTTPConnector(BrokerConnector):
    """Shared REST transport logic reused by every HTTP-based connector."""

    broker_name: str = "generic"
    demo_base_url: str = "https://demo.example.invalid"
    real_base_url: str = "https://real.example.invalid"

    def __init__(self, config: BrokerConfig, client: Optional[httpx.AsyncClient] = None) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None
        self._connected = False
        self._rate_limiter = TokenBucketRateLimiter(*get_rate_limit(self.broker_name))

    @property
    def base_url(self) -> str:
        return self.demo_base_url if self.config.demo else self.real_base_url

    def _auth_headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.config.api_key} if self.config.api_key else {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, headers=self._auth_headers())
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        await self._rate_limiter.acquire()
        client = await self._ensure_client()
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    # -- BrokerConnector interface -----------------------------------

    async def connect(self) -> None:
        async def attempt() -> None:
            await self._request("GET", "/ping")
            self._connected = True

        await reconnect_with_backoff(attempt)

    async def disconnect(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def place_order(self, order: Order) -> ExecutionReport:
        payload = {
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "price": order.price,
            "account_id": order.account_id,
        }
        response = await self._request("POST", "/orders", json=payload)
        data = response.json()
        return ExecutionReport(
            order_id=order.id,
            status=OrderStatus(data.get("status", "submitted")),
            filled_quantity=data.get("filled_quantity", 0.0),
            average_fill_price=data.get("average_fill_price"),
            broker=self.broker_name,
            reported_at=datetime.utcnow(),
            raw=data,
        )

    async def cancel_order(self, order_id: str) -> None:
        await self._request("POST", f"/orders/{order_id}/cancel")

    async def get_positions(self) -> list[Position]:
        response = await self._request("GET", "/positions")
        data = response.json()
        return [Position(**p) for p in data.get("positions", [])]

    async def get_account_state(self) -> AccountState:
        response = await self._request("GET", "/account")
        return AccountState(**response.json())

    async def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Polling-based streaming interface stub.

        Real streaming (websockets/socket subscriptions) is future work per
        broker SDK; this yields one tick per requested symbol through the
        same injectable HTTP transport so the interface and rate limiting
        behave consistently and are testable without a live socket.
        """
        for symbol in symbols:
            response = await self._request("GET", "/tick", params={"symbol": symbol})
            yield Tick(**response.json())

    async def get_historical_data(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        response = await self._request(
            "GET",
            "/historical",
            params={
                "symbol": symbol,
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        data = response.json()
        return [Bar(**b) for b in data.get("bars", [])]
