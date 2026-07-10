"""Walk-forward validation + promotion gate (Fase 12).

docs/ARCHITECTURE.md (Fase 12 / seccion 10): parameter changes are NEVER
promoted without out-of-sample validation. Protocol:

1. the [start, end] history is split into ``n_windows`` rolling windows;
   each window optimizes on its in-sample (IS) segment and evaluates the
   IS winner on the immediately following out-of-sample (OOS) segment.
   OOS segments tile the evaluation region contiguously - no overlap, no
   leakage (IS always strictly precedes its OOS).
2. the current (baseline) params are evaluated on the SAME OOS segments.
3. promotion gate (env-tunable):
   - candidate OOS Sharpe >= baseline OOS Sharpe * PROMOTION_THRESHOLD
     (default 1.05; for non-positive baselines the margin is additive);
   - candidate worst OOS max_drawdown must not be worse than baseline's
     by more than MAX_DRAWDOWN_TOLERANCE relative (default 0.20).

The gate only ever RECOMMENDS. Applying params is a separate, explicit,
logged step (see pipeline.py).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field

from .clients import BacktesterClient, BacktestMetrics

DEFAULT_PROMOTION_THRESHOLD = 1.05
DEFAULT_DD_TOLERANCE = 0.20


def promotion_threshold() -> float:
    return float(os.environ.get("PROMOTION_THRESHOLD", DEFAULT_PROMOTION_THRESHOLD))


def drawdown_tolerance() -> float:
    return float(os.environ.get("MAX_DRAWDOWN_TOLERANCE", DEFAULT_DD_TOLERANCE))


# --- walk-forward windows -----------------------------------------------------


class WalkForwardWindow(BaseModel):
    index: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime


def walk_forward_windows(
    start: datetime,
    end: datetime,
    n_windows: int = 3,
    is_fraction: float = 0.75,
) -> list[WalkForwardWindow]:
    """Rolling IS/OOS windows over [start, end].

    Within one window, IS takes ``is_fraction`` of the window span and
    OOS the rest; windows advance by exactly one OOS length, so the OOS
    segments are contiguous and non-overlapping and jointly cover
    [start + is_len, end]. ``oos_start == is_end`` for every window
    (the OOS segment begins where its IS segment ends: zero leakage).
    """
    if end <= start:
        raise ValueError("end must be after start")
    if n_windows < 1:
        raise ValueError("n_windows must be >= 1")
    if not (0.0 < is_fraction < 1.0):
        raise ValueError("is_fraction must be in (0, 1)")

    total = (end - start).total_seconds()
    # total = is_len + n * oos_len, with is_len = r/(1-r) * oos_len
    oos_len = total / (is_fraction / (1.0 - is_fraction) + n_windows)
    is_len = oos_len * is_fraction / (1.0 - is_fraction)
    if oos_len <= 0 or is_len <= 0:
        raise ValueError("date range too small for the requested windows")

    windows: list[WalkForwardWindow] = []
    for k in range(n_windows):
        is_start = start + timedelta(seconds=k * oos_len)
        is_end = is_start + timedelta(seconds=is_len)
        oos_end = is_end + timedelta(seconds=oos_len)
        if k == n_windows - 1:
            oos_end = end  # absorb float rounding on the last window
        windows.append(
            WalkForwardWindow(
                index=k,
                is_start=is_start,
                is_end=is_end,
                oos_start=is_end,
                oos_end=oos_end,
            )
        )
    return windows


# --- promotion gate -----------------------------------------------------------


class PromotionDecision(BaseModel):
    promote: bool
    reasons: list[str] = Field(default_factory=list)
    candidate_oos_sharpe: float
    baseline_oos_sharpe: float
    candidate_oos_max_drawdown: float
    baseline_oos_max_drawdown: float
    threshold: float
    drawdown_tolerance: float
    metric: str = "sharpe"


def promotion_gate(
    candidate_sharpe: float,
    baseline_sharpe: float,
    candidate_max_dd: float,
    baseline_max_dd: float,
    threshold: Optional[float] = None,
    dd_tolerance: Optional[float] = None,
) -> PromotionDecision:
    """Fase 12 gate: promote ONLY if OOS beats current by the threshold
    AND the drawdown did not get materially worse."""
    thr = promotion_threshold() if threshold is None else threshold
    tol = drawdown_tolerance() if dd_tolerance is None else dd_tolerance
    reasons: list[str] = []

    if baseline_sharpe > 0.0:
        required = baseline_sharpe * thr
    else:
        # multiplying a non-positive Sharpe would INVERT the gate; use an
        # additive margin instead so improvement is still demanded.
        required = baseline_sharpe + (thr - 1.0)
    sharpe_ok = candidate_sharpe >= required
    reasons.append(
        f"OOS sharpe {candidate_sharpe:.4f} "
        f"{'>=' if sharpe_ok else '<'} required {required:.4f} "
        f"(baseline {baseline_sharpe:.4f} x threshold {thr})"
    )

    cand_dd = abs(candidate_max_dd)
    base_dd = abs(baseline_max_dd)
    if base_dd > 0.0:
        dd_ok = cand_dd <= base_dd * (1.0 + tol)
        reasons.append(
            f"OOS max drawdown {cand_dd:.4f} "
            f"{'<=' if dd_ok else '>'} allowed {base_dd * (1.0 + tol):.4f} "
            f"(baseline {base_dd:.4f} +{tol:.0%} tolerance)"
        )
    else:
        dd_ok = cand_dd <= tol
        reasons.append(
            f"baseline had no drawdown; candidate {cand_dd:.4f} "
            f"{'<=' if dd_ok else '>'} absolute tolerance {tol:.4f}"
        )

    return PromotionDecision(
        promote=sharpe_ok and dd_ok,
        reasons=reasons,
        candidate_oos_sharpe=candidate_sharpe,
        baseline_oos_sharpe=baseline_sharpe,
        candidate_oos_max_drawdown=cand_dd,
        baseline_oos_max_drawdown=base_dd,
        threshold=thr,
        drawdown_tolerance=tol,
    )


# --- walk-forward execution -----------------------------------------------------


class WindowOutcome(BaseModel):
    window_index: int
    best_params: dict[str, Any]
    is_metrics: dict[str, Any]
    oos_metrics: dict[str, Any]
    baseline_oos_metrics: dict[str, Any]


class WalkForwardReport(BaseModel):
    windows: list[WindowOutcome]
    #: IS winner of the most recent window - the params a promotion applies.
    recommended_params: dict[str, Any]
    decision: PromotionDecision
    #: every backtest executed, for persistence/audit.
    evaluations: list[dict[str, Any]] = Field(default_factory=list)


def _sharpe(metrics: BacktestMetrics) -> float:
    return float(metrics.sharpe)


async def walk_forward_validate(
    client: BacktesterClient,
    strategy_key: str,
    candidates: list[dict[str, Any]],
    baseline_params: dict[str, Any],
    symbol: str,
    timeframe: str,
    windows: list[WalkForwardWindow],
    initial_capital: float = 10_000.0,
    frictions: Optional[dict[str, Any]] = None,
    threshold: Optional[float] = None,
    dd_tolerance: Optional[float] = None,
) -> WalkForwardReport:
    """Optimize on IS, evaluate on OOS, compare against baseline OOS."""
    if not candidates:
        raise ValueError("no candidates to validate")
    if not windows:
        raise ValueError("no walk-forward windows")

    evaluations: list[dict[str, Any]] = []
    outcomes: list[WindowOutcome] = []

    async def run(
        params: dict[str, Any], start: datetime, end: datetime,
        *, oos: bool, window: int, role: str,
    ) -> BacktestMetrics:
        result = await client.run_backtest(
            strategy_key=strategy_key,
            params=params,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            initial_capital=initial_capital,
            frictions=frictions,
        )
        evaluations.append(
            {
                "parameters": params,
                "metrics": result.metrics.model_dump(),
                "out_of_sample": oos,
                "window_index": window,
                "role": role,
            }
        )
        return result.metrics

    for window in windows:
        # 1. optimize on IS: best candidate by IS Sharpe (deterministic ties)
        best_params: dict[str, Any] | None = None
        best_is: BacktestMetrics | None = None
        for params in candidates:
            metrics = await run(
                params, window.is_start, window.is_end,
                oos=False, window=window.index, role="candidate",
            )
            if best_is is None or _sharpe(metrics) > _sharpe(best_is):
                best_is, best_params = metrics, params
        assert best_params is not None and best_is is not None

        # 2. evaluate the IS winner (and baseline) on the untouched OOS
        oos_metrics = await run(
            best_params, window.oos_start, window.oos_end,
            oos=True, window=window.index, role="candidate",
        )
        baseline_oos = await run(
            baseline_params, window.oos_start, window.oos_end,
            oos=True, window=window.index, role="baseline",
        )
        outcomes.append(
            WindowOutcome(
                window_index=window.index,
                best_params=best_params,
                is_metrics=best_is.model_dump(),
                oos_metrics=oos_metrics.model_dump(),
                baseline_oos_metrics=baseline_oos.model_dump(),
            )
        )

    n = len(outcomes)
    cand_sharpe = sum(o.oos_metrics["sharpe"] for o in outcomes) / n
    base_sharpe = sum(o.baseline_oos_metrics["sharpe"] for o in outcomes) / n
    cand_dd = max(abs(o.oos_metrics["max_drawdown"]) for o in outcomes)
    base_dd = max(abs(o.baseline_oos_metrics["max_drawdown"]) for o in outcomes)

    decision = promotion_gate(
        cand_sharpe, base_sharpe, cand_dd, base_dd, threshold, dd_tolerance
    )
    return WalkForwardReport(
        windows=outcomes,
        recommended_params=outcomes[-1].best_params,
        decision=decision,
        evaluations=evaluations,
    )
