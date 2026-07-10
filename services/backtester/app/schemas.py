"""Pydantic request/response schemas for the backtester API (Fase 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from app.engine import FrictionConfig, SessionWindow


# --- data source configuration ---------------------------------------------------


class CsvDataConfig(BaseModel):
    """CSV OHLCV input: a server-side path OR raw uploaded CSV text."""

    source: Literal["csv"] = "csv"
    path: Optional[str] = Field(default=None, description="Server-side CSV file path.")
    content: Optional[str] = Field(default=None, description="Raw CSV text (upload).")

    @model_validator(mode="after")
    def _exactly_one(self) -> "CsvDataConfig":
        if (self.path is None) == (self.content is None):
            raise ValueError("provide exactly one of 'path' or 'content'")
        return self


class SyntheticDataConfig(BaseModel):
    """Deterministic synthetic OHLCV series (trend/range/random_walk)."""

    source: Literal["synthetic"] = "synthetic"
    regime: Literal["trend", "range", "random_walk"] = "random_walk"
    n_bars: int = Field(default=500, ge=2, le=100_000)
    seed: int = 42
    start_price: float = Field(default=100.0, gt=0.0)
    drift: float = Field(default=0.002, description="Per-bar log-price drift (trend regime).")
    volatility: float = Field(default=0.01, ge=0.0)
    mean_reversion: float = Field(default=0.1, ge=0.0, le=1.0)
    base_volume: float = Field(default=10_000.0, gt=0.0)


DataConfig = Annotated[
    Union[CsvDataConfig, SyntheticDataConfig], Field(discriminator="source")
]


# --- requests ---------------------------------------------------------------------


class BacktestCreateRequest(BaseModel):
    strategy_key: str = Field(description="Registry id, e.g. 'sma_crossover'.")
    params: dict[str, Any] = Field(default_factory=dict, description="Strategy parameter overrides.")
    symbol: str = Field(default="SYN", min_length=1, max_length=50)
    timeframe: str = Field(default="1h", min_length=1, max_length=10)
    start: Optional[datetime] = Field(default=None, description="Inclusive data range start (UTC).")
    end: Optional[datetime] = Field(default=None, description="Inclusive data range end (UTC).")
    initial_capital: float = Field(default=100_000.0, gt=0.0)
    position_size_pct: float = Field(default=1.0, gt=0.0, le=1.0)
    allow_reverse: bool = True
    lookback_bars: int = Field(default=500, ge=10, le=10_000)
    periods_per_year: Optional[float] = Field(default=None, gt=0.0)
    risk_free_rate: float = 0.0
    market: Optional[str] = None
    friction: FrictionConfig = Field(default_factory=FrictionConfig)
    sessions: list[SessionWindow] = Field(default_factory=list)
    data: DataConfig = Field(default_factory=SyntheticDataConfig)


# --- responses --------------------------------------------------------------------


class BacktestSummary(BaseModel):
    """List-view row: run inputs + headline metrics, no curve/trades."""

    id: str
    strategy_key: str
    symbol: str
    timeframe: str
    status: str
    initial_capital: float
    parameters: dict[str, Any]
    started_at: datetime
    finished_at: Optional[datetime]
    error: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None


class BacktestDetail(BacktestSummary):
    """Full results: metrics + equity curve + trade list + engine stats."""

    friction: dict[str, Any] = Field(default_factory=dict)
    data_config: dict[str, Any] = Field(default_factory=dict)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
