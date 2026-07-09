"""Correlation limit check: reject when the new position's returns correlate
beyond max_correlation (absolute value) with any existing open position.

Return series: signal.metadata["returns"] for the candidate symbol (falls
back to the portfolio's injected series), portfolio state returns for the
open positions. With no usable data the check passes with a note (return
series are an injected enrichment, not guaranteed for every symbol).
"""

from __future__ import annotations

import numpy as np

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


def correlation(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 2:
        return None
    sa = np.asarray(a[-n:], dtype=float)
    sb = np.asarray(b[-n:], dtype=float)
    if float(np.std(sa)) == 0.0 or float(np.std(sb)) == 0.0:
        return None
    return float(np.corrcoef(sa, sb)[0, 1])


class CorrelationCheck(RiskCheck):
    name = "correlation"

    def run(self, ctx: ValidationContext) -> CheckResult:
        new_returns = ctx.new_symbol_returns
        if new_returns is None:
            return self._pass("no_return_data_for_signal")

        worst_symbol: str | None = None
        worst_corr = 0.0
        for position in ctx.state.positions:
            if position.symbol == ctx.signal.symbol or position.quantity == 0:
                continue
            series = ctx.state.returns.get(position.symbol)
            if not series:
                continue
            corr = correlation(new_returns, series)
            if corr is None:
                continue
            if abs(corr) > abs(worst_corr):
                worst_corr = corr
                worst_symbol = position.symbol

        if worst_symbol is None:
            return self._pass("no_overlapping_return_data")

        value = abs(worst_corr)
        limit = ctx.limits.max_correlation
        if value <= limit:
            return self._pass(
                f"max_abs_correlation[{worst_symbol}]={value:.6g}<={limit:.6g}", value, limit
            )
        return self._fail(
            f"correlation[{worst_symbol}]={worst_corr:.6g} abs>{limit:.6g}", value, limit
        )
