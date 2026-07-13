"""Paper -> live promotion gates (P18): the guardian of the last step.

The system only trades real money once its paper track record proves itself.
This module is the pure, testable decision: given a snapshot of the paper
performance, evaluate each configurable gate. Promotion requires ALL gates to
pass; every promotion is admin-confirmed and audited on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config


@dataclass
class PromotionSnapshot:
    paper_days: float = 0.0
    drawdown: float = 0.0          # observed drawdown from peak (fraction)
    total_return: float = 0.0      # (equity - starting) / starting
    sharpe: float | None = None
    paper_return: float | None = None      # for backtest coherence
    backtest_return: float | None = None


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass
class GateReport:
    ready: bool
    gates: list[GateResult] = field(default_factory=list)


def evaluate_gates(
    snap: PromotionSnapshot,
    *,
    min_days: float | None = None,
    max_dd: float | None = None,
    min_return: float | None = None,
    min_sharpe: float | None = None,
    coherence_tol: float | None = None,
) -> GateReport:
    min_days = min_days if min_days is not None else config.min_paper_days()
    max_dd = max_dd if max_dd is not None else config.max_promote_drawdown()
    min_return = min_return if min_return is not None else config.min_paper_return()
    if min_sharpe is None:
        min_sharpe = config.min_sharpe()
    if coherence_tol is None:
        coherence_tol = config.backtest_coherence_tolerance()

    gates: list[GateResult] = [
        GateResult(
            "min_paper_days",
            snap.paper_days >= min_days,
            f"{snap.paper_days:.1f}d paper vs {min_days:.0f}d required",
        ),
        GateResult(
            "max_drawdown",
            snap.drawdown <= max_dd,
            f"drawdown {snap.drawdown:.2%} vs {max_dd:.2%} allowed",
        ),
        GateResult(
            "min_return",
            snap.total_return >= min_return,
            f"return {snap.total_return:.2%} vs {min_return:.2%} required",
        ),
    ]

    # Optional gates: when a threshold is configured but the metric is missing,
    # the gate FAILS (conservative — never promote to live without the proof).
    if min_sharpe is not None:
        ok = snap.sharpe is not None and snap.sharpe >= min_sharpe
        detail = (
            f"sharpe {snap.sharpe:.2f} vs {min_sharpe:.2f} required"
            if snap.sharpe is not None
            else "sharpe metric unavailable"
        )
        gates.append(GateResult("min_sharpe", ok, detail))

    if coherence_tol is not None:
        if (
            snap.paper_return is not None
            and snap.backtest_return is not None
            and snap.backtest_return != 0
        ):
            diff = abs(snap.paper_return - snap.backtest_return) / abs(snap.backtest_return)
            gates.append(
                GateResult(
                    "backtest_coherence",
                    diff <= coherence_tol,
                    f"paper vs backtest gap {diff:.2%} vs {coherence_tol:.2%} allowed",
                )
            )
        else:
            gates.append(
                GateResult("backtest_coherence", False, "backtest baseline unavailable")
            )

    return GateReport(ready=all(g.passed for g in gates), gates=gates)
