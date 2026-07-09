"""Daily / weekly / monthly realized-loss limit checks.

loss fraction = max(0, -pnl_period) / equity, compared against the
corresponding RiskLimits fraction. Profitable periods trivially pass.
"""

from __future__ import annotations

from app.checks.base import CheckResult, RiskCheck
from app.context import ValidationContext


def _loss_fraction(pnl: float, equity: float) -> float:
    if equity <= 0:
        return 1.0
    return max(0.0, -pnl) / equity


class DailyLossCheck(RiskCheck):
    name = "daily_loss"

    def run(self, ctx: ValidationContext) -> CheckResult:
        value = _loss_fraction(ctx.state.pnl_daily, ctx.equity)
        return self.limit_check(value, ctx.limits.max_daily_loss, "daily_loss")


class WeeklyLossCheck(RiskCheck):
    name = "weekly_loss"

    def run(self, ctx: ValidationContext) -> CheckResult:
        value = _loss_fraction(ctx.state.pnl_weekly, ctx.equity)
        return self.limit_check(value, ctx.limits.max_weekly_loss, "weekly_loss")


class MonthlyLossCheck(RiskCheck):
    name = "monthly_loss"

    def run(self, ctx: ValidationContext) -> CheckResult:
        value = _loss_fraction(ctx.state.pnl_monthly, ctx.equity)
        return self.limit_check(value, ctx.limits.max_monthly_loss, "monthly_loss")
