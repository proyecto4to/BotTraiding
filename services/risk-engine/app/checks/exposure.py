"""Exposure checks: per symbol, per sector, total gross, leverage, margin.

All exposure fractions are projected *after* the proposed trade (signed:
a reducing trade lowers exposure) relative to account equity.
"""

from __future__ import annotations

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


class SymbolExposureCheck(RiskCheck):
    name = "exposure_symbol"

    def run(self, ctx: ValidationContext) -> CheckResult:
        if ctx.entry_price is None and ctx.increases_exposure:
            return self._fail("no_entry_price")
        if ctx.equity <= 0:
            return self._fail("non_positive_equity")
        value = ctx.symbol_exposure_after / ctx.equity
        return self.limit_check(value, ctx.limits.max_exposure_per_symbol, "exposure_symbol")


class SectorExposureCheck(RiskCheck):
    name = "exposure_sector"

    def run(self, ctx: ValidationContext) -> CheckResult:
        if ctx.equity <= 0:
            return self._fail("non_positive_equity")
        value = ctx.sector_exposure_after / ctx.equity
        return self.limit_check(
            value, ctx.limits.max_exposure_per_sector, f"exposure_sector[{ctx.sector}]"
        )


class TotalExposureCheck(RiskCheck):
    """Gross notional across all symbols after the trade vs equity
    (limit: ExtendedRiskLimits.max_total_exposure)."""

    name = "exposure_total"

    def run(self, ctx: ValidationContext) -> CheckResult:
        if ctx.equity <= 0:
            return self._fail("non_positive_equity")
        value = ctx.gross_exposure_after / ctx.equity
        return self.limit_check(value, ctx.limits.max_total_exposure, "exposure_total")


class LeverageCheck(RiskCheck):
    name = "leverage"

    def run(self, ctx: ValidationContext) -> CheckResult:
        if ctx.equity <= 0:
            return self._fail("non_positive_equity")
        value = ctx.gross_exposure_after / ctx.equity
        return self.limit_check(value, ctx.limits.max_leverage, "leverage")


class MarginCheck(RiskCheck):
    """Additional notional required by the trade must fit in free margin
    (Fase 7 margin model: 1:1 notional, matching portfolio-engine)."""

    name = "margin"

    def run(self, ctx: ValidationContext) -> CheckResult:
        required = max(0.0, ctx.symbol_exposure_delta)
        if required == 0.0:
            return self._pass("no_additional_margin", 0.0, ctx.state.account.free_margin)
        return self.limit_check(required, ctx.state.account.free_margin, "margin_required")
