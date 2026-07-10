"""Grid/random candidate generation from the strategy's own param schema."""

from __future__ import annotations

import pytest

from trading_strategies import load_builtin_strategies, registry

from app.search import generate_candidates, grid_candidates, random_candidates, tunable_specs

load_builtin_strategies()

CLS = registry.get("sma_crossover")


def _spec_bounds() -> dict[str, tuple[float, float]]:
    return {
        s.name: (s.min, s.max)
        for s in CLS.param_specs
        if s.min is not None and s.max is not None
    }


def test_tunable_specs_only_bounded_params() -> None:
    names = {s.name for s in tunable_specs(CLS)}
    assert "fast_period" in names and "slow_period" in names


def test_grid_respects_budget_bounds_and_cross_field_rules() -> None:
    budget = 8
    candidates = grid_candidates(CLS, budget)
    assert 1 <= len(candidates) <= budget
    bounds = _spec_bounds()
    seen = set()
    for cand in candidates:
        for name, (lo, hi) in bounds.items():
            assert lo <= cand[name] <= hi, f"{name} out of schema bounds"
        # cross-field rule enforced by the strategy itself
        assert cand["fast_period"] < cand["slow_period"]
        key = tuple(sorted(cand.items()))
        assert key not in seen, "duplicate candidate"
        seen.add(key)


def test_grid_is_deterministic() -> None:
    assert grid_candidates(CLS, 12) == grid_candidates(CLS, 12)


def test_random_is_seeded_and_valid() -> None:
    a = random_candidates(CLS, 10, seed=42)
    b = random_candidates(CLS, 10, seed=42)
    assert a == b
    assert len(a) == 10
    c = random_candidates(CLS, 10, seed=43)
    assert c != a  # different seed explores differently
    bounds = _spec_bounds()
    for cand in a:
        for name, (lo, hi) in bounds.items():
            assert lo <= cand[name] <= hi
        assert cand["fast_period"] < cand["slow_period"]


def test_generate_candidates_dispatch_and_unknown_type() -> None:
    assert generate_candidates(CLS, "grid", 4) == grid_candidates(CLS, 4)
    with pytest.raises(ValueError, match="unknown search_type"):
        generate_candidates(CLS, "genetic", 4)
