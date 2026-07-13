"""Injectable async clients for the services the controller orchestrates.

Market data (bars), ai-engine (regime + selection) and trading-engine (bots).
Every network call goes through these so tests inject fakes — no network. The
trading-engine calls carry a short-lived service JWT (the controller acts as an
admin system user); market-data and ai-engine are internal and unauthenticated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

from . import config


class DownstreamError(Exception):
    """A downstream service call failed or returned an error status."""


def service_token() -> str:
    """Mint a short-lived admin access token so trading-engine accepts bot
    creation/start/stop (paper bots need any user; the controller uses admin so
    the same identity also covers a future live promotion)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": config.system_user_id(),
        "roles": ["admin"],
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    return jwt.encode(payload, config.jwt_secret(), algorithm="HS256")


async def _request(client: httpx.AsyncClient | None, method: str, url: str, **kw):
    timeout = config.http_timeout()
    try:
        if client is not None:
            response = await client.request(method, url, timeout=timeout, **kw)
        else:
            async with httpx.AsyncClient(timeout=timeout) as c:
                response = await c.request(method, url, **kw)
    except httpx.HTTPError as exc:
        raise DownstreamError(f"{method} {url} failed: {exc}") from exc
    if response.status_code >= 400:
        raise DownstreamError(
            f"{method} {url} -> {response.status_code}: {response.text[:200]}"
        )
    return response


class MarketDataClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def get_bars(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        url = f"{config.market_data_url()}/market-data/{symbol}"
        params = {"broker": config.broker(), "timeframe": timeframe, "limit": limit}
        resp = await _request(self._client, "GET", url, params=params)
        return resp.json().get("bars", [])


class AiClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def regime(self, bars: list[dict]) -> dict:
        url = f"{config.ai_engine_url()}/ai/regime"
        resp = await _request(self._client, "POST", url, json={"bars": bars})
        return resp.json()

    async def select(
        self, regime: dict, market: str, timeframe: str, performance: list[dict]
    ) -> list[dict]:
        url = f"{config.ai_engine_url()}/ai/select"
        body = {
            "regime": regime,
            "market": market,
            "timeframe": timeframe,
            "performance": performance,
        }
        resp = await _request(self._client, "POST", url, json=body)
        return resp.json().get("ranked", [])


class TradingEngineClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {service_token()}"}

    async def list_bots(self, account_id: str) -> list[dict]:
        url = f"{config.trading_engine_url()}/bots"
        resp = await _request(
            self._client, "GET", url, params={"account_id": account_id},
            headers=self._headers(),
        )
        return resp.json()

    async def create_bot(self, spec: dict) -> dict:
        url = f"{config.trading_engine_url()}/bots"
        resp = await _request(self._client, "POST", url, json=spec, headers=self._headers())
        return resp.json()

    async def start_bot(self, bot_id: str) -> None:
        url = f"{config.trading_engine_url()}/bots/{bot_id}/start"
        await _request(self._client, "POST", url, headers=self._headers())

    async def stop_bot(self, bot_id: str) -> None:
        url = f"{config.trading_engine_url()}/bots/{bot_id}/stop"
        await _request(self._client, "POST", url, headers=self._headers())


@dataclass
class Clients:
    market_data: MarketDataClient
    ai: AiClient
    trading: TradingEngineClient


def get_clients() -> Clients:
    """FastAPI dependency (overridden with fakes in tests)."""
    return Clients(MarketDataClient(), AiClient(), TradingEngineClient())
