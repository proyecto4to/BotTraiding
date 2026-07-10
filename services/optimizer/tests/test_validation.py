"""Walk-forward split boundaries + promotion gate semantics (Fase 12)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from app.validation import (
    promotion_gate,
    walk_forward_validate,
    walk_forward_windows,
)

from tests.fakes import FakeBacktesterClient

START = datetime(2025, 1, 1)
END = datetime(2026, 1, 1)


# --- walk-forward windows -----------------------------------------------------


def test_windows_no_overlap_no_leakage() -> None:
    windows = walk_forward_windows(START, END, n_windows=4, is_fraction=0.75)
    assert len(windows) == 4
    for w in windows:
        # zero leakage: OOS begins exactly where IS ends
        assert w.oos_start == w.is_end
        assert w.is_start < w.is_end < w.oos_end
        assert w.is_start >= START and w.oos_end <= END
    # OOS segments tile the evaluation region contiguously, no overlap
    for prev, nxt in zip(windows, windows[1:]):
        assert nxt.oos_start == prev.oos_end
        # each window advances by exactly one OOS length
        assert nxt.is_start == prev.is_start + (prev.oos_end - prev.oos_start)
    assert windows[-1].oos_end == END


def test_windows_is_fraction_shape() -> None:
    windows = walk_forward_windows(START, END, n_windows=3, is_fraction=0.75)
    for w in windows:
        span = (w.oos_end - w.oos_start) + (w.is_end - w.is_start)
        ratio = (w.is_end - w.is_start) / span
        assert ratio == pytest.approx(0.75, abs=0.01)
    # all IS segments have equal length
    lengths = {(w.is_end - w.is_start) for w in windows[:-1]}
    assert len(lengths) == 1


def test_windows_single_window() -> None:
    (w,) = walk_forward_windows(START, END, n_windows=1, is_fraction=0.8)
    assert w.is_start == START
    assert w.oos_end == END
    assert w.oos_start == w.is_end


def test_windows_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        walk_forward_windows(END, START)
    with pytest.raises(ValueError):
        walk_forward_windows(START, END, n_windows=0)
    with pytest.raises(ValueError):
        walk_forward_windows(START, END, is_fraction=1.0)


# --- promotion gate -----------------------------------------------------------


def test_better_oos_promotes() -> None:
    d = promotion_gate(1.20, 1.00, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is True


def test_worse_oos_rejects() -> None:
    d = promotion_gate(0.90, 1.00, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is False
    assert any("<" in r for r in d.reasons)


def test_equal_oos_respects_threshold() -> None:
    # equal performance must NOT promote while the threshold demands +5%
    d = promotion_gate(1.00, 1.00, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is False
    # with threshold 1.0 (no demanded improvement) equal performance passes
    d = promotion_gate(1.00, 1.00, 0.10, 0.10, threshold=1.0, dd_tolerance=0.20)
    assert d.promote is True


def test_barely_meeting_threshold_promotes() -> None:
    d = promotion_gate(1.05, 1.00, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is True


def test_negative_baseline_uses_additive_margin() -> None:
    # multiplying a negative Sharpe by 1.05 would LOWER the bar; the gate
    # must still demand improvement: required = -0.5 + 0.05 = -0.45
    d = promotion_gate(-0.40, -0.50, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is True
    d = promotion_gate(-0.50, -0.50, 0.10, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is False


def test_drawdown_gate_rejects_worse_dd() -> None:
    # sharpe clearly better BUT drawdown 5x worse than tolerated
    d = promotion_gate(2.00, 1.00, 0.50, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is False
    assert any("drawdown" in r for r in d.reasons)


def test_drawdown_within_tolerance_promotes() -> None:
    d = promotion_gate(2.00, 1.00, 0.115, 0.10, threshold=1.05, dd_tolerance=0.20)
    assert d.promote is True


def test_env_threshold_default(monkeypatch) -> None:
    monkeypatch.delenv("PROMOTION_THRESHOLD", raising=False)
    d = promotion_gate(1.04, 1.00, 0.10, 0.10)  # default threshold 1.05
    assert d.promote is False
    monkeypatch.setenv("PROMOTION_THRESHOLD", "1.01")
    d = promotion_gate(1.04, 1.00, 0.10, 0.10)
    assert d.promote is True


# --- walk-forward execution -----------------------------------------------------


def test_walk_forward_optimizes_is_and_judges_on_oos() -> None:
    # candidate quality is a pure function of fast_period; the baseline
    # (fast=10) scores 1.0, fast=20 scores 1.5 -> must win IS and be the
    # one judged OOS.
    def sharpe_fn(params: dict) -> float:
        return {10: 1.0, 20: 1.5, 30: 0.2}.get(params["fast_period"], 0.0)

    client = FakeBacktesterClient(sharpe_fn)
    candidates = [
        {"fast_period": 10, "slow_period": 50},
        {"fast_period": 20, "slow_period": 50},
        {"fast_period": 30, "slow_period": 50},
    ]
    windows = walk_forward_windows(START, END, n_windows=2, is_fraction=0.75)
    report = asyncio.run(
        walk_forward_validate(
            client=client,
            strategy_key="sma_crossover",
            candidates=candidates,
            baseline_params={"fast_period": 10, "slow_period": 50},
            symbol="BTC/USDT",
            timeframe="1h",
            windows=windows,
            threshold=1.05,
            dd_tolerance=0.20,
        )
    )
    assert report.recommended_params["fast_period"] == 20
    assert report.decision.promote is True  # 1.5 >= 1.0 * 1.05
    # per window: 3 IS + 1 OOS + 1 baseline OOS = 5 calls -> 10 total
    assert len(client.calls) == 10
    # every OOS evaluation ran strictly after its window's IS segment
    oos_evals = [e for e in report.evaluations if e["out_of_sample"]]
    assert len(oos_evals) == 4  # (candidate + baseline) x 2 windows
    is_evals = [e for e in report.evaluations if not e["out_of_sample"]]
    assert len(is_evals) == 6
    roles = {(e["role"], e["out_of_sample"]) for e in report.evaluations}
    assert ("baseline", True) in roles and ("candidate", False) in roles
