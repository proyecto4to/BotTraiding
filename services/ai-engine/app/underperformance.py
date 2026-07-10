"""Underperformance rules -> disable RECOMMENDATIONS (Fase 11).

The AI engine NEVER disables a strategy itself. It evaluates simple,
auditable rules over recent trade returns and produces recommendations
that are persisted (ai_recommendations) and published on NATS
(``ai.recommendation.created``); a human or an authorized consumer acts
on them via strategy-engine's PATCH /strategies/{key}. La IA no
sustituye las reglas de trading (docs/ARCHITECTURE.md).

Rules (thresholds env-configurable, see ``RuleConfig.from_env``):

1. rolling_sharpe_below_threshold: per-trade Sharpe over the last
   ``min_trades`` trades < ``sharpe_threshold``.
2. max_drawdown_breach: max drawdown of the equity curve rebuilt from
   the trade returns >= ``max_drawdown``.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field


class RuleConfig(BaseModel):
    #: minimum trades before the Sharpe rule may fire (avoid noise).
    min_trades: int = Field(default=30, ge=2)
    #: per-trade rolling Sharpe below this recommends disabling.
    sharpe_threshold: float = 0.0
    #: max drawdown (fraction, 0.2 = 20%) at or above this recommends disabling.
    max_drawdown: float = Field(default=0.20, gt=0.0)

    @classmethod
    def from_env(cls) -> "RuleConfig":
        return cls(
            min_trades=int(os.environ.get("UNDERPERF_MIN_TRADES", "30")),
            sharpe_threshold=float(
                os.environ.get("UNDERPERF_SHARPE_THRESHOLD", "0.0")
            ),
            max_drawdown=float(os.environ.get("UNDERPERF_MAX_DRAWDOWN", "0.20")),
        )


class Recommendation(BaseModel):
    """Advisory output. ``action`` is what the consumer is advised to do."""

    strategy_key: str
    action: Literal["disable"] = "disable"
    rule: str
    reason: str
    severity: Literal["medium", "high", "critical"] = "medium"
    metrics: dict = Field(default_factory=dict)


def rolling_sharpe(trade_returns: Sequence[float]) -> float:
    """Per-trade Sharpe (mean/std of trade returns, no annualization)."""
    r = np.asarray(trade_returns, dtype=float)
    if len(r) < 2:
        return 0.0
    std = float(r.std(ddof=1))
    if std <= 0.0:
        mean = float(r.mean())
        return 0.0 if mean == 0.0 else math.copysign(float("inf"), mean)
    return float(r.mean()) / std


def max_drawdown_from_returns(trade_returns: Sequence[float]) -> float:
    """Max drawdown (fraction) of the compounded equity curve."""
    r = np.asarray(trade_returns, dtype=float)
    if len(r) == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    dd = 1.0 - equity / peaks
    return float(dd.max())


def evaluate_strategy(
    strategy_key: str,
    trade_returns: Sequence[float],
    config: RuleConfig | None = None,
) -> list[Recommendation]:
    """Apply every rule to one strategy's recent trade returns."""
    cfg = config or RuleConfig.from_env()
    recs: list[Recommendation] = []

    if len(trade_returns) >= cfg.min_trades:
        window = list(trade_returns)[-cfg.min_trades :]
        sharpe = rolling_sharpe(window)
        if sharpe < cfg.sharpe_threshold:
            severity = "high" if sharpe < cfg.sharpe_threshold - 0.5 else "medium"
            recs.append(
                Recommendation(
                    strategy_key=strategy_key,
                    rule="rolling_sharpe_below_threshold",
                    reason=(
                        f"rolling Sharpe {sharpe:.3f} over the last "
                        f"{cfg.min_trades} trades is below the "
                        f"{cfg.sharpe_threshold:.3f} threshold"
                    ),
                    severity=severity,
                    metrics={
                        "rolling_sharpe": sharpe,
                        "window_trades": cfg.min_trades,
                        "threshold": cfg.sharpe_threshold,
                    },
                )
            )

    dd = max_drawdown_from_returns(trade_returns)
    if dd >= cfg.max_drawdown:
        severity = "critical" if dd >= 1.5 * cfg.max_drawdown else "high"
        recs.append(
            Recommendation(
                strategy_key=strategy_key,
                rule="max_drawdown_breach",
                reason=(
                    f"max drawdown {dd:.1%} breaches the "
                    f"{cfg.max_drawdown:.1%} limit"
                ),
                severity=severity,
                metrics={"max_drawdown": dd, "limit": cfg.max_drawdown},
            )
        )
    return recs
