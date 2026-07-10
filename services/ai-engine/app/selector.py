"""Strategy selection/weighting for the current market regime (Fase 11).

score(strategy) = affinity(category, regime) * perf_score(recent performance)

- affinity comes from a fixed, documented regime->category matrix
  (trend affinity x volatility affinity), NOT from a model;
- perf_score is a logistic squash of the recent risk-adjusted metric
  (Sharpe by default), so 0 -> 0.5 (neutral), strongly negative -> ~0,
  strongly positive -> ~1. Strategies without performance history get
  the neutral 0.5 - the regime affinity alone ranks them.

Output weights are normalized to sum to 1. The selector only RANKS;
whether/how the weights are used (allocation, enable/disable) belongs to
risk/portfolio - la IA no sustituye las reglas de trading.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from .regime import RegimeState

# --- regime -> category affinity matrices ------------------------------------
# Rows are trading_strategies.StrategyCategory values; unknown categories
# fall back to _NEUTRAL. Values are heuristics, tuned to be defensible:
# trend/momentum like directional markets, mean-reversion likes ranges,
# breakout likes quiet ranges about to expand, volatility strategies like
# elevated volatility, arbitrage/ai are regime-agnostic.

_NEUTRAL = 0.5

TREND_AFFINITY: dict[str, dict[str, float]] = {
    "trend": {"up": 1.0, "down": 1.0, "sideways": 0.2},
    "momentum": {"up": 0.9, "down": 0.9, "sideways": 0.3},
    "breakout": {"up": 0.6, "down": 0.6, "sideways": 0.8},
    "mean_reversion": {"up": 0.3, "down": 0.3, "sideways": 1.0},
    "volatility": {"up": 0.5, "down": 0.5, "sideways": 0.6},
    "arbitrage": {"up": 0.5, "down": 0.5, "sideways": 0.5},
    "ai": {"up": 0.5, "down": 0.5, "sideways": 0.5},
}

VOLATILITY_AFFINITY: dict[str, dict[str, float]] = {
    "trend": {"low": 0.9, "normal": 1.0, "high": 0.6},
    "momentum": {"low": 0.7, "normal": 1.0, "high": 0.8},
    "breakout": {"low": 1.0, "normal": 0.8, "high": 0.5},
    "mean_reversion": {"low": 0.6, "normal": 1.0, "high": 0.7},
    "volatility": {"low": 0.3, "normal": 0.6, "high": 1.0},
    "arbitrage": {"low": 0.8, "normal": 0.8, "high": 0.8},
    "ai": {"low": 0.8, "normal": 0.8, "high": 0.8},
}


class StrategyInfo(BaseModel):
    """Minimal registry metadata the selector needs."""

    key: str
    category: str
    timeframes: list[str] = Field(default_factory=list)


class PerformanceRecord(BaseModel):
    """Recent performance of one strategy (injectable input data).

    Producers: backtester runs, paper-trading stats, live PnL - the
    selector does not care where the numbers come from.
    """

    strategy_key: str
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    trades: Optional[int] = None


class StrategyScore(BaseModel):
    key: str
    category: str
    affinity: float
    perf_score: float
    score: float
    weight: float = Field(ge=0.0, le=1.0)


def category_affinity(category: str, regime: RegimeState) -> float:
    """Affinity of a strategy category to the given regime, in (0, 1]."""
    t = TREND_AFFINITY.get(category, {}).get(regime.trend, _NEUTRAL)
    v = VOLATILITY_AFFINITY.get(category, {}).get(regime.volatility, _NEUTRAL)
    return t * v


def performance_score(record: Optional[PerformanceRecord]) -> float:
    """Logistic squash of the recent Sharpe into [0, 1]; 0.5 is neutral."""
    if record is None or record.sharpe is None:
        return _NEUTRAL
    return 1.0 / (1.0 + math.exp(-float(record.sharpe)))


def rank_strategies(
    regime: RegimeState,
    strategies: list[StrategyInfo],
    performance: list[PerformanceRecord],
    top_n: Optional[int] = None,
) -> list[StrategyScore]:
    """Rank strategies for a regime; weights of the returned list sum to 1.

    Deterministic: ties are broken by strategy key. When *top_n* is
    given, only the best top_n are returned (weights renormalized).
    """
    perf_by_key = {p.strategy_key: p for p in performance}
    scored: list[StrategyScore] = []
    for info in strategies:
        affinity = category_affinity(info.category, regime)
        perf = performance_score(perf_by_key.get(info.key))
        scored.append(
            StrategyScore(
                key=info.key,
                category=info.category,
                affinity=round(affinity, 6),
                perf_score=round(perf, 6),
                score=round(affinity * perf, 6),
                weight=0.0,
            )
        )
    scored.sort(key=lambda s: (-s.score, s.key))
    if top_n is not None:
        scored = scored[: max(0, top_n)]
    total = sum(s.score for s in scored)
    if scored:
        if total > 0.0:
            for s in scored:
                s.weight = s.score / total
        else:  # degenerate: all zero -> equal weights
            for s in scored:
                s.weight = 1.0 / len(scored)
        # remove float drift so the weights sum to exactly 1.0
        drift = 1.0 - sum(s.weight for s in scored)
        scored[0].weight += drift
    return scored


def registry_strategies(
    market: Optional[str] = None, timeframe: Optional[str] = None
) -> list[StrategyInfo]:
    """StrategyInfo list from the shared trading_strategies registry."""
    from trading_strategies import load_builtin_strategies, registry

    load_builtin_strategies()
    out: list[StrategyInfo] = []
    for key in registry.ids(market=market, timeframe=timeframe):
        cls = registry.get(key)
        out.append(
            StrategyInfo(
                key=key,
                category=cls.category.value,
                timeframes=list(cls.timeframes),
            )
        )
    return out
