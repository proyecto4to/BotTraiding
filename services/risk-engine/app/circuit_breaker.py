"""Per-account circuit breaker state machine.

States: NORMAL -> SOFT_HALT (no new/increased positions) -> HARD_HALT
(reject everything; recommend closing all positions). Transitions only
escalate automatically; de-escalation is exclusively via the admin reset
endpoint (POST /risk/circuit-breaker/{account_id}/reset).

Thresholds come from RiskLimits.circuit_breaker_thresholds with defaults
derived from the account's limits:

    daily_loss_soft  (default: max_daily_loss)        - fraction of equity
    daily_loss_hard  (default: 1.5 x max_daily_loss)
    drawdown_soft    (default: max_drawdown)
    drawdown_hard    (default: 1.25 x max_drawdown)
    errors_soft      (default: 10)  - errors within the rolling window
    errors_hard      (default: 25)

A metric exactly AT a threshold does not trip (the plain risk check already
rejects at the limit boundary); strictly above it does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.orm import Session

from app.models import CircuitBreakerRow
from app.schemas import ExtendedRiskLimits

ERROR_WINDOW_SECONDS = int(os.environ.get("CB_ERROR_WINDOW_SECONDS", "300"))

DEFAULT_ERRORS_SOFT = 10
DEFAULT_ERRORS_HARD = 25


class BreakerState(str, Enum):
    NORMAL = "NORMAL"
    SOFT_HALT = "SOFT_HALT"
    HARD_HALT = "HARD_HALT"


_SEVERITY = {BreakerState.NORMAL: 0, BreakerState.SOFT_HALT: 1, BreakerState.HARD_HALT: 2}


@dataclass
class BreakerMetrics:
    daily_loss_fraction: float = 0.0
    drawdown: float = 0.0
    error_count: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def thresholds_for(limits: ExtendedRiskLimits) -> dict[str, float]:
    overrides = limits.circuit_breaker_thresholds or {}
    defaults = {
        "daily_loss_soft": limits.max_daily_loss,
        "daily_loss_hard": limits.max_daily_loss * 1.5,
        "drawdown_soft": limits.max_drawdown,
        "drawdown_hard": limits.max_drawdown * 1.25,
        "errors_soft": float(DEFAULT_ERRORS_SOFT),
        "errors_hard": float(DEFAULT_ERRORS_HARD),
    }
    defaults.update({k: float(v) for k, v in overrides.items()})
    return defaults


def get_breaker(db: Session, account_id: str) -> CircuitBreakerRow:
    row = db.get(CircuitBreakerRow, account_id)
    if row is None:
        row = CircuitBreakerRow(account_id=account_id, state=BreakerState.NORMAL.value)
        db.add(row)
        db.flush()
    return row


def record_error(db: Session, account_id: str) -> int:
    """Count an error against the rolling window; returns the current count."""
    row = get_breaker(db, account_id)
    now = _now()
    window_start = row.error_window_start
    if window_start is None or now - window_start > timedelta(seconds=ERROR_WINDOW_SECONDS):
        row.error_window_start = now
        row.error_count = 1
    else:
        row.error_count += 1
    db.flush()
    return row.error_count


def current_error_count(row: CircuitBreakerRow) -> int:
    """Effective error count: 0 once the rolling window has expired."""
    if row.error_window_start is None:
        return 0
    if _now() - row.error_window_start > timedelta(seconds=ERROR_WINDOW_SECONDS):
        return 0
    return row.error_count


def _target_state(metrics: BreakerMetrics, thresholds: dict[str, float]) -> tuple[BreakerState, str]:
    hard_reasons = []
    if metrics.daily_loss_fraction > thresholds["daily_loss_hard"]:
        hard_reasons.append(
            f"daily_loss={metrics.daily_loss_fraction:.6g}>{thresholds['daily_loss_hard']:.6g}"
        )
    if metrics.drawdown > thresholds["drawdown_hard"]:
        hard_reasons.append(f"drawdown={metrics.drawdown:.6g}>{thresholds['drawdown_hard']:.6g}")
    if metrics.error_count > thresholds["errors_hard"]:
        hard_reasons.append(f"errors={metrics.error_count}>{thresholds['errors_hard']:.6g}")
    if hard_reasons:
        return BreakerState.HARD_HALT, ";".join(hard_reasons)

    soft_reasons = []
    if metrics.daily_loss_fraction > thresholds["daily_loss_soft"]:
        soft_reasons.append(
            f"daily_loss={metrics.daily_loss_fraction:.6g}>{thresholds['daily_loss_soft']:.6g}"
        )
    if metrics.drawdown > thresholds["drawdown_soft"]:
        soft_reasons.append(f"drawdown={metrics.drawdown:.6g}>{thresholds['drawdown_soft']:.6g}")
    if metrics.error_count > thresholds["errors_soft"]:
        soft_reasons.append(f"errors={metrics.error_count}>{thresholds['errors_soft']:.6g}")
    if soft_reasons:
        return BreakerState.SOFT_HALT, ";".join(soft_reasons)

    return BreakerState.NORMAL, ""


def evaluate(
    db: Session,
    account_id: str,
    limits: ExtendedRiskLimits,
    metrics: BreakerMetrics,
) -> tuple[CircuitBreakerRow, bool]:
    """Evaluate thresholds and escalate if needed. Returns (row, escalated).
    Never de-escalates automatically."""
    row = get_breaker(db, account_id)
    current = BreakerState(row.state)
    target, reason = _target_state(metrics, thresholds_for(limits))

    if _SEVERITY[target] > _SEVERITY[current]:
        row.state = target.value
        row.reason = reason
        row.updated_at = _now()
        db.flush()
        return row, True
    return row, False


def reset(db: Session, account_id: str) -> CircuitBreakerRow:
    """Admin action: back to NORMAL, clear reason and the error window."""
    row = get_breaker(db, account_id)
    row.state = BreakerState.NORMAL.value
    row.reason = None
    row.error_count = 0
    row.error_window_start = None
    row.updated_at = _now()
    db.flush()
    return row
