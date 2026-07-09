"""Request/response models for portfolio-engine.

PortfolioState is composed of the shared contract models (AccountState,
Position) plus service-owned exposure/drawdown reports. ExecutionIngest
embeds the shared ExecutionReport fields and adds the symbol/side context
the contract does not carry (contracts are read-only; see report).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from trading_contracts import AccountState, OrderSide, OrderStatus, Position


class ExecutionIngest(BaseModel):
    """Body of POST /portfolio/{account_id}/executions.

    Superset of the shared ExecutionReport: adds symbol/side (missing from
    the contract) and optional sector/currency/commission context.
    """

    order_id: UUID
    status: OrderStatus
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    broker: str = "unknown"
    reported_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)

    symbol: str
    side: OrderSide
    sector: Optional[str] = None
    currency: str = "USD"
    commission: float = 0.0


class MarkRequest(BaseModel):
    """Body of POST /portfolio/{account_id}/mark.

    prices: last mark per symbol. returns: optional injected recent return
    series per symbol, used for the correlation matrix and served to the
    risk-engine correlation check.
    """

    prices: dict[str, float] = Field(default_factory=dict)
    returns: dict[str, list[float]] = Field(default_factory=dict)


class ExposureReport(BaseModel):
    account_id: str
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    leverage: float = 0.0
    per_symbol: dict[str, float] = Field(default_factory=dict)
    per_sector: dict[str, float] = Field(default_factory=dict)
    per_currency: dict[str, float] = Field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)


class DrawdownReport(BaseModel):
    account_id: str
    equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown: float = 0.0
    floating_drawdown: float = 0.0


class PortfolioState(BaseModel):
    """Full snapshot served by GET /portfolio/{account_id}; the risk-engine
    validation pipeline consumes this shape."""

    account: AccountState
    positions: list[Position] = Field(default_factory=list)
    marks: dict[str, float] = Field(default_factory=dict)
    returns: dict[str, list[float]] = Field(default_factory=dict)
    exposure: ExposureReport
    drawdown: DrawdownReport
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    pnl_daily: float = 0.0
    pnl_weekly: float = 0.0
    pnl_monthly: float = 0.0
    updated_at: datetime


class ExecutionIngestResult(BaseModel):
    account_id: str
    symbol: str
    applied: bool
    realized_pnl_delta: float = 0.0
    position: Optional[Position] = None
    cash: float = 0.0
