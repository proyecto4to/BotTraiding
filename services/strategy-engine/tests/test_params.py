"""Parameter schema validation."""

from __future__ import annotations

import pytest

from trading_strategies import (
    ParameterValidationError,
    load_builtin_strategies,
    registry,
)

load_builtin_strategies()


def _cls(strategy_id: str):
    return registry.get(strategy_id)


def test_defaults_merge() -> None:
    params = _cls("sma_crossover").validate_params({})
    assert params["fast_period"] == 10
    assert params["slow_period"] == 30


def test_override_applies_over_defaults() -> None:
    params = _cls("sma_crossover").validate_params({"fast_period": 5})
    assert params["fast_period"] == 5
    assert params["slow_period"] == 30


def test_unknown_parameter_rejected() -> None:
    with pytest.raises(ParameterValidationError) as exc:
        _cls("sma_crossover").validate_params({"nope": 1})
    assert any("unknown parameter" in e for e in exc.value.errors)


def test_below_minimum_rejected() -> None:
    with pytest.raises(ParameterValidationError) as exc:
        _cls("sma_crossover").validate_params({"fast_period": 1})
    assert any(">= 2" in e for e in exc.value.errors)


def test_above_maximum_rejected() -> None:
    with pytest.raises(ParameterValidationError):
        _cls("sma_crossover").validate_params({"fast_period": 10_000})


def test_wrong_type_rejected() -> None:
    with pytest.raises(ParameterValidationError):
        _cls("sma_crossover").validate_params({"fast_period": "abc"})
    with pytest.raises(ParameterValidationError):
        _cls("sma_crossover").validate_params({"fast_period": True})
    with pytest.raises(ParameterValidationError):
        _cls("sma_crossover").validate_params({"fast_period": 5.5})


def test_numeric_coercion() -> None:
    params = _cls("sma_crossover").validate_params(
        {"fast_period": 5.0, "stop_atr_mult": 3}
    )
    assert params["fast_period"] == 5 and isinstance(params["fast_period"], int)
    assert params["stop_atr_mult"] == 3.0 and isinstance(params["stop_atr_mult"], float)


def test_cross_field_validation() -> None:
    with pytest.raises(ParameterValidationError) as exc:
        _cls("sma_crossover").validate_params({"fast_period": 50})  # default slow=30
    assert any("fast_period" in e and "slow_period" in e for e in exc.value.errors)
    with pytest.raises(ParameterValidationError):
        _cls("dual_momentum").validate_params({"fast_lookback": 100})
    with pytest.raises(ParameterValidationError):
        _cls("volatility_regime").validate_params({"atr_fast": 60})


def test_multiple_errors_reported_together() -> None:
    with pytest.raises(ParameterValidationError) as exc:
        _cls("sma_crossover").validate_params({"fast_period": 0, "bogus": 1})
    assert len(exc.value.errors) == 2


@pytest.mark.parametrize("strategy_id", sorted(registry.ids()))
def test_every_strategy_accepts_its_defaults(strategy_id: str) -> None:
    cls = registry.get(strategy_id)
    merged = cls.validate_params({})
    assert set(merged) == {spec.name for spec in cls.param_specs}
