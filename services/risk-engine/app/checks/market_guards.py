"""Market microstructure guards: liquidity, slippage, volatility.

Data comes from signal.metadata (volume / expected_slippage / volatility or
atr); thresholds from ExtendedRiskLimits extras. A disabled limit
(min_volume <= 0, max_slippage/max_volatility None) passes; an enabled
limit with missing metadata FAILS (fail-safe: the guard was explicitly
configured, so the strategy must supply the datum).
"""

from __future__ import annotations

from typing import Optional

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


def _meta_float(ctx: ValidationContext, key: str) -> Optional[float]:
    value = ctx.signal.metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class LiquidityCheck(RiskCheck):
    """signal.metadata['volume'] (recent volume for the symbol) must be at
    least min_volume."""

    name = "liquidity"

    def run(self, ctx: ValidationContext) -> CheckResult:
        threshold = ctx.limits.min_volume
        if threshold is None or threshold <= 0:
            return self._pass("liquidity_guard_disabled")
        volume = _meta_float(ctx, "volume")
        if volume is None:
            return self._fail("volume_metadata_missing", None, threshold)
        if volume >= threshold:
            return self._pass(f"volume={volume:.6g}>={threshold:.6g}", volume, threshold)
        return self._fail(f"volume={volume:.6g}<{threshold:.6g}", volume, threshold)


class SlippageCheck(RiskCheck):
    """signal.metadata['expected_slippage'] (fraction of price) must not
    exceed max_slippage."""

    name = "slippage"

    def run(self, ctx: ValidationContext) -> CheckResult:
        limit = ctx.limits.max_slippage
        if limit is None:
            return self._pass("slippage_guard_disabled")
        expected = _meta_float(ctx, "expected_slippage")
        if expected is None:
            return self._fail("expected_slippage_metadata_missing", None, limit)
        return self.limit_check(expected, limit, "expected_slippage")


class VolatilityCheck(RiskCheck):
    """Volatility ceiling: signal.metadata['volatility'] (stddev of returns,
    fraction) or atr/entry_price must not exceed max_volatility."""

    name = "volatility"

    def run(self, ctx: ValidationContext) -> CheckResult:
        limit = ctx.limits.max_volatility
        if limit is None:
            return self._pass("volatility_guard_disabled")

        value = _meta_float(ctx, "volatility")
        if value is None:
            atr = _meta_float(ctx, "atr")
            if atr is not None and ctx.entry_price:
                value = atr / ctx.entry_price
        if value is None:
            return self._fail("volatility_metadata_missing", None, limit)
        return self.limit_check(value, limit, "volatility")
