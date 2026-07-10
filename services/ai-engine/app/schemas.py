"""Request/response models for the ai-engine API (Fase 11)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from trading_contracts import Bar

from .anomaly import AnomalyFlag, SeriesInput
from .regime import RegimeState
from .selector import PerformanceRecord, StrategyInfo, StrategyScore
from .underperformance import Recommendation


class RegimeRequest(BaseModel):
    bars: list[Bar] = Field(min_length=2)


class RegimeRefreshRequest(BaseModel):
    #: symbols to refresh; defaults to env AI_REGIME_SYMBOLS.
    symbols: Optional[list[str]] = None
    timeframe: str = "1h"
    #: bars fetched per symbol from the injectable BarProvider.
    limit: int = Field(default=256, ge=32, le=5000)


class RegimeRefreshResult(BaseModel):
    symbol: str
    regime: Optional[RegimeState] = None
    error: Optional[str] = None


class RegimeRefreshResponse(BaseModel):
    refreshed: list[RegimeRefreshResult] = Field(default_factory=list)
    detail: str = ""


class SelectRequest(BaseModel):
    regime: RegimeState
    performance: list[PerformanceRecord] = Field(default_factory=list)
    #: explicit candidate list; when omitted the shared registry is used.
    strategies: Optional[list[StrategyInfo]] = None
    market: Optional[str] = None
    timeframe: Optional[str] = None
    top_n: Optional[int] = Field(default=None, ge=1)


class SelectResponse(BaseModel):
    regime: RegimeState
    ranked: list[StrategyScore]


class AnomalyRequest(BaseModel):
    series: list[SeriesInput] = Field(min_length=1)
    zscore_window: int = Field(default=20, ge=3)
    zscore_threshold: float = Field(default=3.0, gt=0.0)
    drawdown_window: int = Field(default=10, ge=2)
    drawdown_threshold: float = Field(default=0.10, gt=0.0)


class AnomalyResponse(BaseModel):
    flags: list[AnomalyFlag]


class StrategyPerformanceInput(BaseModel):
    strategy_key: str
    #: recent per-trade returns as fractions (0.01 = +1%), oldest first.
    trade_returns: list[float] = Field(min_length=1)


class UnderperformanceRequest(BaseModel):
    records: list[StrategyPerformanceInput] = Field(min_length=1)
    #: persist + publish the resulting recommendations (default true).
    persist: bool = True


class UnderperformanceResponse(BaseModel):
    recommendations: list[Recommendation]


class RecommendationOut(BaseModel):
    id: str
    strategy_key: str
    action: str
    rule: str
    reason: str
    severity: str
    metrics: dict
    created_at: datetime
