"""Parameter search over a strategy's declared schema (Fase 12).

Candidates are generated ONLY from the ``ParameterSpec`` bounds the
strategy itself declares in the shared trading_strategies library - the
optimizer never invents parameters. Every candidate is validated through
``cls.validate_params`` so cross-field rules (e.g. fast < slow) hold.

- grid search: evenly spaced points per tunable dimension, with the
  number of points per dimension grown round-robin while the cartesian
  product stays within the budget;
- random search: uniform draws within bounds, seeded for reproducibility.
"""

from __future__ import annotations

import itertools
import random
from typing import Any

from trading_strategies.plugin import (
    ParameterSpec,
    ParameterValidationError,
    StrategyPlugin,
)


def tunable_specs(cls: type[StrategyPlugin]) -> list[ParameterSpec]:
    """Specs the search can vary: bounded numerics, choices and bools."""
    out = []
    for spec in cls.param_specs:
        if spec.choices:
            out.append(spec)
        elif spec.type in ("int", "float") and spec.min is not None and spec.max is not None:
            out.append(spec)
        elif spec.type == "bool":
            out.append(spec)
    return out


def _grid_values(spec: ParameterSpec, points: int) -> list[Any]:
    """*points* evenly spaced values for one spec (deduped, ordered)."""
    if points <= 1:
        return [spec.default]
    if spec.choices:
        return list(spec.choices)[:points]
    if spec.type == "bool":
        return [False, True][:points]
    lo, hi = float(spec.min), float(spec.max)  # type: ignore[arg-type]
    raw = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    if spec.type == "int":
        values: list[Any] = sorted({int(round(v)) for v in raw})
    else:
        values = sorted({round(v, 6) for v in raw})
    return values


def _validated(cls: type[StrategyPlugin], combo: dict[str, Any]) -> dict[str, Any] | None:
    """Full validated param dict for a combo, or None if it violates rules."""
    try:
        return cls.validate_params(combo)
    except ParameterValidationError:
        return None


def grid_candidates(cls: type[StrategyPlugin], budget: int) -> list[dict[str, Any]]:
    """Grid over the schema bounds; at most *budget* validated candidates."""
    if budget < 1:
        raise ValueError("budget must be >= 1")
    specs = tunable_specs(cls)
    if not specs:
        defaults = _validated(cls, {})
        return [defaults] if defaults is not None else []

    # grow points-per-dimension round-robin while the product fits the budget
    points = [1] * len(specs)
    grew = True
    while grew:
        grew = False
        for i, spec in enumerate(specs):
            cap = len(spec.choices) if spec.choices else (2 if spec.type == "bool" else 5)
            if points[i] >= cap:
                continue
            product = 1
            for j, p in enumerate(points):
                product *= p + 1 if j == i else p
            if product <= budget:
                points[i] += 1
                grew = True

    axes = [_grid_values(spec, pts) for spec, pts in zip(specs, points)]
    names = [spec.name for spec in specs]
    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for combo in itertools.product(*axes):
        validated = _validated(cls, dict(zip(names, combo)))
        if validated is None:
            continue
        key = tuple(sorted(validated.items()))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(validated)
        if len(candidates) >= budget:
            break
    return candidates


def random_candidates(
    cls: type[StrategyPlugin], budget: int, seed: int | None = None
) -> list[dict[str, Any]]:
    """*budget* random validated candidates, reproducible via *seed*."""
    if budget < 1:
        raise ValueError("budget must be >= 1")
    specs = tunable_specs(cls)
    if not specs:
        defaults = _validated(cls, {})
        return [defaults] if defaults is not None else []
    rng = random.Random(seed)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    attempts = 0
    max_attempts = budget * 25
    while len(candidates) < budget and attempts < max_attempts:
        attempts += 1
        combo: dict[str, Any] = {}
        for spec in specs:
            if spec.choices:
                combo[spec.name] = rng.choice(spec.choices)
            elif spec.type == "bool":
                combo[spec.name] = rng.choice([False, True])
            elif spec.type == "int":
                combo[spec.name] = rng.randint(int(spec.min), int(spec.max))  # type: ignore[arg-type]
            else:
                combo[spec.name] = round(rng.uniform(float(spec.min), float(spec.max)), 6)  # type: ignore[arg-type]
        validated = _validated(cls, combo)
        if validated is None:
            continue
        key = tuple(sorted(validated.items()))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(validated)
    return candidates


def generate_candidates(
    cls: type[StrategyPlugin],
    search_type: str,
    budget: int,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    if search_type == "grid":
        return grid_candidates(cls, budget)
    if search_type == "random":
        return random_candidates(cls, budget, seed)
    raise ValueError(f"unknown search_type '{search_type}' (grid|random)")
