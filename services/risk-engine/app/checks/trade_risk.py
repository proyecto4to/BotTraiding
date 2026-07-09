"""Per-trade risk % check (spec: max_risk_per_trade)."""

from __future__ import annotations

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


class PerTradeRiskCheck(RiskCheck):
    """risk = suggested_size * stop_distance must be <= equity * max_risk_per_trade.

    Fails safe when there is no usable entry price or stop (a trade whose
    risk cannot be quantified must not reach the market)."""

    name = "per_trade_risk"

    def run(self, ctx: ValidationContext) -> CheckResult:
        if ctx.entry_price is None or ctx.entry_price <= 0:
            return self._fail("no_entry_price")
        if ctx.stop_price is None:
            return self._fail("no_stop_loss")
        stop_distance = abs(ctx.entry_price - ctx.stop_price)
        if stop_distance <= 0:
            return self._fail("zero_stop_distance")
        if ctx.equity <= 0:
            return self._fail("non_positive_equity")

        risk_fraction = (ctx.signal.suggested_size * stop_distance) / ctx.equity
        return self.limit_check(risk_fraction, ctx.limits.max_risk_per_trade, "risk_per_trade")
