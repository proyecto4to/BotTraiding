"""Pydantic contracts shared across services.

Fase 1: tipado puro, sin logica de negocio. Ver docs/ARCHITECTURE.md seccion 5.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ERROR = "error"


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class TradeSignal(BaseModel):
    """Seccion 5.1 - emitida por una Strategy, nunca ejecuta directamente."""

    id: UUID
    strategy_id: str
    symbol: str
    market: str
    side: OrderSide
    confidence: float = Field(ge=0.0, le=1.0)
    timeframe: str
    suggested_size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    generated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskDecision(BaseModel):
    """Seccion 5.2 - resultado de RiskEngine.validate(signal, portfolio_state)."""

    signal_id: UUID
    approved: bool
    reason: str
    max_size_allowed: Optional[float] = None
    adjusted_stop: Optional[float] = None
    risk_checks_passed: list[str] = Field(default_factory=list)
    risk_checks_failed: list[str] = Field(default_factory=list)
    decided_at: datetime


class Order(BaseModel):
    """Seccion 5.3 - orden aprobada, lista para ExecutionEngine.submit()."""

    id: UUID
    signal_id: UUID
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    broker: str
    account_id: str
    execution_mode: ExecutionMode
    created_at: datetime


class RiskLimits(BaseModel):
    """Seccion 5.6 - configuracion, no codigo."""

    max_risk_per_trade: float
    max_daily_loss: float
    max_weekly_loss: float
    max_monthly_loss: float
    max_drawdown: float
    max_floating_drawdown: float
    max_leverage: float
    max_correlation: float
    max_exposure_per_symbol: float
    max_exposure_per_sector: float
    circuit_breaker_thresholds: dict[str, float] = Field(default_factory=dict)


class Position(BaseModel):
    symbol: str
    quantity: float
    average_price: float
    unrealized_pnl: float = 0.0
    account_id: str


class AccountState(BaseModel):
    account_id: str
    balance: float
    equity: float
    margin_used: float
    free_margin: float
    currency: str = "USD"


class Tick(BaseModel):
    symbol: str
    bid: float
    ask: float
    timestamp: datetime


class Bar(BaseModel):
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime


class ExecutionReport(BaseModel):
    order_id: UUID
    status: OrderStatus
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    broker: str
    reported_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class StrategyMetadata(BaseModel):
    """Metadata de una Strategy (seccion 5.5)."""

    id: str
    name: str
    version: str
    category: str
    markets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
