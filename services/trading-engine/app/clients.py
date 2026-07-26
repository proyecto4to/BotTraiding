"""Injectable async clients for every downstream the orchestrator talks to.

Invariants enforced by construction (docs/ARCHITECTURE.md):
- market data comes from broker-connectors' REST API, orders go exclusively
  through execution-engine — trading-engine NEVER talks to a broker
  directly (there is deliberately no client for placing broker orders);
- every signal goes through risk-engine's /risk/validate before any order
  is built (see app/orchestrator.py).

Each call has a per-call timeout and maps any transport/HTTP failure to
DownstreamError so the cycle loop can capture it without dying. An
httpx.AsyncClient can be injected per client (integration tests wire
httpx.ASGITransport instances so the real service apps are exercised
in-process); when omitted, a client is created per call from env URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from trading_contracts.auth import service_auth_header

from . import config

SERVICE_NAME = "trading-engine"

TIMEFRAME_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def timeframe_seconds(timeframe: str) -> int:
    """'15m' -> 900. Falls back to 60s on anything unparseable (the bot
    schema validates the format, so this is belt-and-braces)."""
    try:
        return int(timeframe[:-1]) * TIMEFRAME_UNIT_SECONDS[timeframe[-1]]
    except (KeyError, ValueError, IndexError):
        return 60


class DownstreamError(Exception):
    """A downstream service call failed (network, timeout or HTTP >= 400)."""

    def __init__(self, service: str, detail: str) -> None:
        self.service = service
        self.detail = detail
        super().__init__(f"{service}: {detail}")


class StrategyDisabledError(DownstreamError):
    """strategy-engine returned 409: the strategy is disabled."""


class _BaseClient:
    service = "downstream"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._http = http  # injected (integration tests); not closed by us

    def _default_base_url(self) -> str:
        raise NotImplementedError

    @property
    def base_url(self) -> str:
        return (self._base_url or self._default_base_url()).rstrip("/")

    @property
    def timeout(self) -> float:
        return self._timeout if self._timeout is not None else config.http_timeout()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self.timeout)
        # Every outbound call identifies this service. risk-engine and
        # execution-engine reject unauthenticated callers on the endpoints that
        # decide or place trades, so being able to reach the port is not enough.
        # An explicit Authorization passed by the caller wins.
        headers = {**service_auth_header(SERVICE_NAME), **(kwargs.pop("headers", None) or {})}
        kwargs["headers"] = headers
        try:
            if self._http is not None:
                return await self._http.request(method, path, **kwargs)
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                return await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DownstreamError(self.service, f"unreachable: {exc}") from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise DownstreamError(
                self.service,
                f"HTTP {response.status_code}: {response.text[:300]}",
            )


class MarketDataClient(_BaseClient):
    """Recent bars via the market-data service GET /market-data/{symbol}.

    market-data is the shared, cached bar source (one upstream fetch per
    symbol serves every bot); it can be backed by a real broker or by a
    synthetic source so the bot runs out of the box. Read-only market data —
    orders never go through here."""

    service = "market-data"

    def _default_base_url(self) -> str:
        return config.market_data_url()

    async def get_bars(
        self,
        broker: str,
        symbol: str,
        timeframe: str,
        lookback: int | None = None,
        account_id: str = "default",
    ) -> list[dict[str, Any]]:
        bars_needed = lookback if lookback is not None else config.bar_lookback()
        response = await self._request(
            "GET",
            f"/market-data/{symbol}",
            params={"broker": broker, "timeframe": timeframe, "limit": bars_needed},
        )
        self._raise_for_status(response)
        body = response.json()
        # market-data returns {..., "bars": [...]}; tolerate a bare list too.
        return body.get("bars", []) if isinstance(body, dict) else body


class StrategyClient(_BaseClient):
    """POST /strategies/{key}/evaluate: bars + params -> TradeSignal | None."""

    service = "strategy-engine"

    def _default_base_url(self) -> str:
        return config.strategy_engine_url()

    async def evaluate(
        self,
        strategy_key: str,
        bars: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
        user_id: str | None = None,
        account_id: str | None = None,
        market: str | None = None,
    ) -> Optional[dict[str, Any]]:
        response = await self._request(
            "POST",
            f"/strategies/{strategy_key}/evaluate",
            json={
                "bars": bars,
                "params": params or {},
                "user_id": user_id,
                "account_id": account_id,
                "market": market,
            },
        )
        if response.status_code == 409:
            raise StrategyDisabledError(self.service, f"strategy '{strategy_key}' is disabled")
        self._raise_for_status(response)
        return response.json().get("signal")


class RiskClient(_BaseClient):
    """POST /risk/validate and GET /risk/circuit-breaker/{account_id}."""

    service = "risk-engine"

    def _default_base_url(self) -> str:
        return config.risk_engine_url()

    async def get_circuit_breaker(self, account_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/risk/circuit-breaker/{account_id}")
        self._raise_for_status(response)
        return response.json()

    async def validate(
        self,
        signal: dict[str, Any],
        account_id: str,
        risk_per_trade_override: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"signal": signal, "account_id": account_id}
        if risk_per_trade_override is not None:
            body["risk_per_trade_override"] = risk_per_trade_override
        response = await self._request("POST", "/risk/validate", json=body)
        self._raise_for_status(response)
        return response.json()


class ExecutionClient(_BaseClient):
    """POST /executions: approved Order + RiskDecision -> ExecutionOut.

    The RiskDecision context always travels with the order (principle 2.4);
    execution-engine rejects anything without an approving decision."""

    service = "execution-engine"

    def _default_base_url(self) -> str:
        return config.execution_engine_url()

    async def submit(
        self,
        order: dict[str, Any],
        risk_decision: dict[str, Any],
        market_price: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"order": order, "risk_decision": risk_decision}
        if market_price is not None:
            payload["market_price"] = market_price
        response = await self._request("POST", "/executions", json=payload)
        self._raise_for_status(response)
        return response.json()


@dataclass
class Clients:
    """The full downstream bundle a cycle needs. Injectable everywhere:
    FastAPI dependency for /run-once, factory for the background runner."""

    market_data: MarketDataClient
    strategy: StrategyClient
    risk: RiskClient
    execution: ExecutionClient


def get_clients() -> Clients:
    """Default factory reading base URLs from the environment. FastAPI
    dependency (override in tests) and BotRunner default clients factory."""
    return Clients(
        market_data=MarketDataClient(),
        strategy=StrategyClient(),
        risk=RiskClient(),
        execution=ExecutionClient(),
    )
