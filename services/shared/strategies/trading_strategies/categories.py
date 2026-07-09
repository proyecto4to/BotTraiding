"""Category taxonomy for the strategy library (Fase 6).

A fixed, small taxonomy keeps 1000+ strategies browsable: every plugin
declares exactly one category and the registry indexes by it.
"""

from __future__ import annotations

from enum import Enum


class StrategyCategory(str, Enum):
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    VOLATILITY = "volatility"
    ARBITRAGE = "arbitrage"
    AI = "ai"


ALL_CATEGORIES: tuple[StrategyCategory, ...] = tuple(StrategyCategory)
