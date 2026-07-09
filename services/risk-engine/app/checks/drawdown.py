"""Max drawdown (peak-equity) and floating drawdown (open-loss) checks."""

from __future__ import annotations

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


class MaxDrawdownCheck(RiskCheck):
    name = "max_drawdown"

    def run(self, ctx: ValidationContext) -> CheckResult:
        return self.limit_check(
            ctx.state.drawdown.current_drawdown, ctx.limits.max_drawdown, "drawdown"
        )


class FloatingDrawdownCheck(RiskCheck):
    name = "floating_drawdown"

    def run(self, ctx: ValidationContext) -> CheckResult:
        return self.limit_check(
            ctx.state.drawdown.floating_drawdown,
            ctx.limits.max_floating_drawdown,
            "floating_drawdown",
        )
