"""Risk check registry: ALL_CHECKS is the pipeline order for /risk/validate.

Every check is individually instantiable/testable; the pipeline runs all of
them (no short-circuit) so RiskDecision reports the complete pass/fail set.
"""

from __future__ import annotations

from app.checks.base import CheckResult, RiskCheck
from app.checks.correlation import CorrelationCheck
from app.checks.drawdown import FloatingDrawdownCheck, MaxDrawdownCheck
from app.checks.exposure import (
    LeverageCheck,
    MarginCheck,
    SectorExposureCheck,
    SymbolExposureCheck,
    TotalExposureCheck,
)
from app.checks.losses import DailyLossCheck, MonthlyLossCheck, WeeklyLossCheck
from app.checks.market_guards import LiquidityCheck, SlippageCheck, VolatilityCheck
from app.checks.trade_risk import PerTradeRiskCheck

ALL_CHECKS: list[RiskCheck] = [
    PerTradeRiskCheck(),
    DailyLossCheck(),
    WeeklyLossCheck(),
    MonthlyLossCheck(),
    MaxDrawdownCheck(),
    FloatingDrawdownCheck(),
    CorrelationCheck(),
    SymbolExposureCheck(),
    SectorExposureCheck(),
    TotalExposureCheck(),
    LeverageCheck(),
    MarginCheck(),
    LiquidityCheck(),
    SlippageCheck(),
    VolatilityCheck(),
]

__all__ = [
    "ALL_CHECKS",
    "CheckResult",
    "RiskCheck",
    "PerTradeRiskCheck",
    "DailyLossCheck",
    "WeeklyLossCheck",
    "MonthlyLossCheck",
    "MaxDrawdownCheck",
    "FloatingDrawdownCheck",
    "CorrelationCheck",
    "SymbolExposureCheck",
    "SectorExposureCheck",
    "TotalExposureCheck",
    "LeverageCheck",
    "MarginCheck",
    "LiquidityCheck",
    "SlippageCheck",
    "VolatilityCheck",
]
