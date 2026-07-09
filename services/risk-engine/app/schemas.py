"""Request/response models for risk-engine.

Built on the shared contracts (TradeSignal, RiskDecision, RiskLimits,
AccountState, Position). Contracts are read-only, so service-specific
fields live in subclasses/mirrors here:

- ExtendedRiskLimits adds the liquidity/slippage/volatility/total-exposure
  limits the spec requires but RiskLimits does not carry.
- RiskDecisionResponse adds positions_should_close (HARD_HALT semantics)
  and the sizing/stop plan the execution layer consumes.
- PortfolioStateIn mirrors the subset of portfolio-engine's PortfolioState
  the checks need (extra fields in the fetched JSON are ignored).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from trading_contracts import AccountState, Position, RiskDecision, RiskLimits, TradeSignal


class ExtendedRiskLimits(RiskLimits):
    """RiskLimits (contract section 5.6) + risk-engine-owned extra limits.

    All *fraction* limits are fractions of account equity (0.02 = 2%).
    max_leverage / max_total_exposure are gross-notional-to-equity ratios.
    min_volume <= 0 disables the liquidity check; max_slippage /
    max_volatility = None disables those guards.
    """

    max_total_exposure: float = 2.0
    min_volume: float = 0.0
    max_slippage: Optional[float] = None
    max_volatility: Optional[float] = None


class RiskLimitsResponse(BaseModel):
    account_id: str
    limits: ExtendedRiskLimits
    is_default: bool = False


class ExposureIn(BaseModel):
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    per_symbol: dict[str, float] = Field(default_factory=dict)
    per_sector: dict[str, float] = Field(default_factory=dict)
    per_currency: dict[str, float] = Field(default_factory=dict)


class DrawdownIn(BaseModel):
    equity: float = 0.0
    peak_equity: float = 0.0
    current_drawdown: float = 0.0
    floating_drawdown: float = 0.0


class PortfolioStateIn(BaseModel):
    """Mirror of portfolio-engine's GET /portfolio/{account_id} payload
    (subset used by the checks). Also accepted inline on /risk/validate."""

    account: AccountState
    positions: list[Position] = Field(default_factory=list)
    marks: dict[str, float] = Field(default_factory=dict)
    returns: dict[str, list[float]] = Field(default_factory=dict)
    exposure: ExposureIn = Field(default_factory=ExposureIn)
    drawdown: DrawdownIn = Field(default_factory=DrawdownIn)
    pnl_daily: float = 0.0
    pnl_weekly: float = 0.0
    pnl_monthly: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0


class ValidateRequest(BaseModel):
    signal: TradeSignal
    account_id: str
    portfolio_state: Optional[PortfolioStateIn] = None  # inline state for tests


class StopPlan(BaseModel):
    """Concrete stop numbers for the execution layer (see app/sizing.py)."""

    initial_stop: Optional[float] = None
    adjusted_stop: Optional[float] = None
    trailing_stop: Optional[float] = None
    trail_distance: Optional[float] = None
    break_even_stop: Optional[float] = None
    break_even_active: bool = False
    break_even_trigger_r: float = 1.0
    break_even_offset: float = 0.0


class SizingInfo(BaseModel):
    size_by_risk: float = 0.0
    max_size_allowed: float = 0.0
    risk_amount: float = 0.0
    stop_distance: Optional[float] = None
    caps: dict[str, float] = Field(default_factory=dict)
    binding_constraint: Optional[str] = None


class RiskDecisionResponse(RiskDecision):
    """Contract RiskDecision + risk-engine extras (contracts are read-only:
    positions_should_close could not be added to the shared model)."""

    account_id: str
    positions_should_close: bool = False
    circuit_breaker_state: str = "NORMAL"
    sizing: Optional[SizingInfo] = None
    stop_plan: Optional[StopPlan] = None


class CircuitBreakerStatus(BaseModel):
    account_id: str
    state: str
    reason: Optional[str] = None
    error_count: int = 0
    updated_at: Optional[datetime] = None
