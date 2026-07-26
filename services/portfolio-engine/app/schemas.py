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
    client_order_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="execution-engine's deterministic venue idempotency key; "
        "ingesting the same client_order_id twice is a no-op",
    )
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
    # Worst drawdown ever observed (never decreases). The paper->live gate uses
    # this, not current_drawdown, so a recovered crash still counts against it.
    max_drawdown: float = 0.0
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
    # Completed round trips (executions that realized PnL). The paper->live gate
    # uses it to tell a real track record from a handful of lucky fills.
    closed_trades: int = 0
    # Per-trade Sharpe (mean realized PnL / its stdev). None when there are too
    # few trades to be meaningful, which makes the promotion gate fail closed.
    trade_sharpe: float | None = None
    pnl_daily: float = 0.0
    pnl_weekly: float = 0.0
    pnl_monthly: float = 0.0
    updated_at: datetime


class ExecutionIngestResult(BaseModel):
    account_id: str
    symbol: str
    applied: bool
    duplicate: bool = False  # same client_order_id already ingested: no-op
    realized_pnl_delta: float = 0.0
    position: Optional[Position] = None
    cash: float = 0.0


# --- reconciliation (broker truth vs local state) ---------------------------


class ReconcileEntry(BaseModel):
    """One symbol compared between local portfolio state and broker truth."""

    symbol: str
    local_quantity: float = 0.0
    broker_quantity: float = 0.0
    difference: float = 0.0  # broker - local
    broker_average_price: Optional[float] = None


class ReconciliationAdjustment(BaseModel):
    """One applied correction, recorded as a synthetic execution
    (portfolio_executions.source == "reconciliation")."""

    symbol: str
    kind: str  # missing_locally | missing_at_broker | quantity_mismatch
    adjustment_quantity: float  # signed broker - local delta applied
    side: str  # buy | sell (direction of the synthetic execution)
    price_used: float
    execution_id: str  # portfolio_executions.id of the audit row


class ReconciliationReport(BaseModel):
    account_id: str
    broker: str
    broker_account_id: str
    tolerance: float
    matched: list[ReconcileEntry] = Field(default_factory=list)
    missing_locally: list[ReconcileEntry] = Field(default_factory=list)
    missing_at_broker: list[ReconcileEntry] = Field(default_factory=list)
    quantity_mismatches: list[ReconcileEntry] = Field(default_factory=list)
    discrepancies: int = 0
    local_cash: Optional[float] = None
    broker_balance: Optional[float] = None
    applied: bool = False
    adjustments: list[ReconciliationAdjustment] = Field(default_factory=list)
    generated_at: datetime


class ReconcileRequest(BaseModel):
    """Body of POST /portfolio/{account_id}/reconcile (admin only).

    apply=false (default) only reports; apply=true aligns local positions to
    broker truth, recording each adjustment as an auditable synthetic
    execution and publishing a reconciliation event."""

    broker: str
    broker_account_id: Optional[str] = None  # defaults to the path account_id
    apply: bool = False
