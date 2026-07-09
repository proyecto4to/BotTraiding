"""RiskLimits persistence: per-account rows in risk_engine_limits with
conservative defaults applied when an account has no row yet.

Contract columns mirror init.sql `risk_limits`; ExtendedRiskLimits extras
(max_total_exposure / min_volume / max_slippage / max_volatility) are
stored in the extra_limits JSON column.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RiskLimitsRow
from app.schemas import ExtendedRiskLimits

CONTRACT_FIELDS = [
    "max_risk_per_trade",
    "max_daily_loss",
    "max_weekly_loss",
    "max_monthly_loss",
    "max_drawdown",
    "max_floating_drawdown",
    "max_leverage",
    "max_correlation",
    "max_exposure_per_symbol",
    "max_exposure_per_sector",
]

EXTRA_FIELDS = ["max_total_exposure", "min_volume", "max_slippage", "max_volatility"]


def default_limits() -> ExtendedRiskLimits:
    return ExtendedRiskLimits(
        max_risk_per_trade=0.01,
        max_daily_loss=0.03,
        max_weekly_loss=0.06,
        max_monthly_loss=0.10,
        max_drawdown=0.20,
        max_floating_drawdown=0.10,
        max_leverage=2.0,
        max_correlation=0.75,
        max_exposure_per_symbol=0.25,
        max_exposure_per_sector=0.40,
        circuit_breaker_thresholds={},
        max_total_exposure=2.0,
        min_volume=0.0,
        max_slippage=None,
        max_volatility=None,
    )


def _row_for(db: Session, account_id: str) -> RiskLimitsRow | None:
    return db.execute(
        select(RiskLimitsRow).where(RiskLimitsRow.account_id == account_id)
    ).scalar_one_or_none()


def load_limits(db: Session, account_id: str) -> tuple[ExtendedRiskLimits, bool]:
    """Returns (limits, is_default)."""
    row = _row_for(db, account_id)
    if row is None:
        return default_limits(), True

    data = {name: getattr(row, name) for name in CONTRACT_FIELDS}
    data["circuit_breaker_thresholds"] = row.circuit_breaker_thresholds or {}
    extras = row.extra_limits or {}
    defaults = default_limits()
    for name in EXTRA_FIELDS:
        data[name] = extras.get(name, getattr(defaults, name))
    return ExtendedRiskLimits(**data), False


def save_limits(db: Session, account_id: str, limits: ExtendedRiskLimits) -> ExtendedRiskLimits:
    row = _row_for(db, account_id)
    if row is None:
        row = RiskLimitsRow(account_id=account_id)
        db.add(row)

    for name in CONTRACT_FIELDS:
        setattr(row, name, getattr(limits, name))
    row.circuit_breaker_thresholds = limits.circuit_breaker_thresholds or {}
    row.extra_limits = {name: getattr(limits, name) for name in EXTRA_FIELDS}
    db.flush()
    return limits
