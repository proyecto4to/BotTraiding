"""Deterministic fakes for the optimizer's injectable clients."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from app.clients import (
    BacktesterClient,
    BacktestMetrics,
    BacktestResult,
    StrategyEngineClient,
)

SharpeFn = Callable[[dict[str, Any]], float]
DrawdownFn = Callable[[dict[str, Any]], float]


class FakeBacktesterClient(BacktesterClient):
    """Metrics are a pure function of params - no backtester import."""

    def __init__(
        self,
        sharpe_fn: SharpeFn,
        drawdown_fn: Optional[DrawdownFn] = None,
    ) -> None:
        self._sharpe_fn = sharpe_fn
        self._drawdown_fn = drawdown_fn or (lambda params: 0.10)
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "strategy_key": strategy_key,
                "params": params,
                "symbol": symbol,
                "timeframe": timeframe,
                "start": start,
                "end": end,
            }
        )
        return BacktestResult(
            run_id=f"fake-{len(self.calls)}",
            metrics=BacktestMetrics(
                sharpe=self._sharpe_fn(params),
                max_drawdown=self._drawdown_fn(params),
                sortino=1.0,
                win_rate=0.5,
            ),
        )


class FakeStrategyEngineClient(StrategyEngineClient):
    def __init__(self) -> None:
        self.applied: list[tuple[str, dict[str, Any]]] = []

    async def apply_params(self, strategy_key: str, params: dict[str, Any]) -> dict:
        self.applied.append((strategy_key, params))
        return {"strategy_key": strategy_key, "overrides": params}


#: baseline marker: current_params carry fast_period=13, which no grid
#: point produces, so fakes can price the baseline differently.
BASELINE_FAST = 13


def baseline_beats_candidates(params: dict[str, Any]) -> float:
    return 2.0 if params.get("fast_period") == BASELINE_FAST else 0.5


def candidates_beat_baseline(params: dict[str, Any]) -> float:
    return 1.0 if params.get("fast_period") == BASELINE_FAST else 1.5
