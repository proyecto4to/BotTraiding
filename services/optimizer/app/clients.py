"""Injectable HTTP clients for the optimizer's downstream services.

- ``BacktesterClient``: runs backtests via the backtester service REST
  API (built in parallel; contract: POST /backtests -> run_id + metrics).
  Tests inject a fake - backtester code is never imported here.
- ``StrategyEngineClient``: applies promoted params via strategy-engine's
  PUT /strategies/{key}/config. Called ONLY when the walk-forward gate
  passed AND the caller explicitly asked promote=true.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("optimizer.clients")


class BacktestMetrics(BaseModel):
    """Metrics block of the backtester contract (unknown keys kept)."""

    model_config = ConfigDict(extra="allow")

    sharpe: float = 0.0
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    profit_factor: Optional[float] = None
    cagr: Optional[float] = None
    max_drawdown: float = 0.0
    expectancy: Optional[float] = None
    win_rate: Optional[float] = None


class BacktestResult(BaseModel):
    run_id: Optional[str] = None
    metrics: BacktestMetrics
    equity_curve: list[Any] = Field(default_factory=list)
    trades: list[Any] = Field(default_factory=list)


class BacktesterClient(ABC):
    @abstractmethod
    async def run_backtest(
        self,
        strategy_key: str,
        params: dict[str, Any],
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        initial_capital: float = 10_000.0,
        frictions: Optional[dict[str, Any]] = None,
    ) -> BacktestResult:
        """Run one backtest and return its metrics."""


class HttpBacktesterClient(BacktesterClient):
    """Calls the backtester service (env BACKTESTER_URL)."""

    def __init__(self, base_url: Optional[str] = None, timeout: float = 120.0) -> None:
        self._base_url = (
            base_url or os.environ.get("BACKTESTER_URL", "http://backtester:8000")
        ).rstrip("/")
        self._timeout = timeout

    async def run_backtest(
        self,
        strategy_key: str,
        params: dict[str, Any],
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        initial_capital: float = 10_000.0,
        frictions: Optional[dict[str, Any]] = None,
    ) -> BacktestResult:
        payload = {
            "strategy_key": strategy_key,
            "params": params,
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "initial_capital": initial_capital,
            "frictions": frictions or {},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/backtests", json=payload)
            resp.raise_for_status()
            return BacktestResult.model_validate(resp.json())


class StrategyEngineClient(ABC):
    @abstractmethod
    async def apply_params(self, strategy_key: str, params: dict[str, Any]) -> dict:
        """Persist promoted params as the active config in strategy-engine."""


class HttpStrategyEngineClient(StrategyEngineClient):
    """PUT /strategies/{key}/config on strategy-engine.

    The config API is per-user; promoted params are stored under the
    optimizer's system identity (env OPTIMIZER_SYSTEM_USER_ID).
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0) -> None:
        self._base_url = (
            base_url
            or os.environ.get("STRATEGY_ENGINE_URL", "http://strategy-engine:8000")
        ).rstrip("/")
        self._timeout = timeout
        self._user_id = os.environ.get(
            "OPTIMIZER_SYSTEM_USER_ID", "00000000-0000-0000-0000-000000000001"
        )

    async def apply_params(self, strategy_key: str, params: dict[str, Any]) -> dict:
        body = {
            "user_id": self._user_id,
            "account_id": None,
            "overrides": params,
            "is_active": True,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.put(
                f"{self._base_url}/strategies/{strategy_key}/config", json=body
            )
            resp.raise_for_status()
            return resp.json()


# --- injection seams (tests replace these) -----------------------------------

_backtester: Optional[BacktesterClient] = None
_strategy_engine: Optional[StrategyEngineClient] = None


def get_backtester() -> BacktesterClient:
    global _backtester
    if _backtester is None:
        _backtester = HttpBacktesterClient()
    return _backtester


def set_backtester(client: Optional[BacktesterClient]) -> None:
    global _backtester
    _backtester = client


def get_strategy_engine() -> StrategyEngineClient:
    global _strategy_engine
    if _strategy_engine is None:
        _strategy_engine = HttpStrategyEngineClient()
    return _strategy_engine


def set_strategy_engine(client: Optional[StrategyEngineClient]) -> None:
    global _strategy_engine
    _strategy_engine = client
