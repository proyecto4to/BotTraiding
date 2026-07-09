"""Registry discovery, indexing and instantiation."""

from __future__ import annotations

import pytest

from trading_strategies import (
    ALL_CATEGORIES,
    DuplicateStrategyError,
    StrategyCategory,
    StrategyPlugin,
    StrategyRegistry,
    UnknownStrategyError,
    load_builtin_strategies,
    registry,
)

load_builtin_strategies()

EXPECTED_IDS = {
    # trend
    "sma_crossover",
    "ema_crossover",
    "macd_trend",
    # mean reversion
    "bollinger_reversion",
    "rsi2_reversion",
    "zscore_reversion",
    "vwap_reversion",
    # momentum
    "roc_momentum",
    "dual_momentum",
    "momentum_ranking",
    "rsi_divergence",
    # breakout
    "donchian_breakout",
    "atr_channel_breakout",
    "opening_range_breakout",
    # volatility
    "keltner_squeeze",
    "volatility_regime",
}


def test_discovery_finds_all_builtin_strategies() -> None:
    assert len(registry) >= 15
    assert EXPECTED_IDS <= set(registry.ids())


def test_every_strategy_has_valid_metadata() -> None:
    valid_categories = {c.value for c in ALL_CATEGORIES}
    for cls in registry.all():
        info = cls.describe()
        assert info["id"]
        assert info["name"]
        assert info["version"]
        assert info["category"] in valid_categories
        assert info["markets"], f"{info['id']} declares no markets"
        assert info["timeframes"], f"{info['id']} declares no timeframes"
        assert info["description"], f"{info['id']} has no description"
        assert isinstance(info["parameters"], list) and info["parameters"]
        assert 0 < info["recommended_risk_per_trade"] <= 0.1
        assert isinstance(info["historical_metrics"], dict)


@pytest.mark.parametrize("strategy_id", sorted(EXPECTED_IDS))
def test_create_with_defaults(strategy_id: str) -> None:
    plugin = registry.create(strategy_id)
    assert plugin.metadata.id == strategy_id
    schema = plugin.parameters
    assert schema["type"] == "object"
    assert schema["properties"]
    assert plugin.required_filters() == []


def test_filter_by_category() -> None:
    assert set(registry.ids(category="trend")) == {
        "sma_crossover",
        "ema_crossover",
        "macd_trend",
    }
    assert set(registry.ids(category="volatility")) == {
        "keltner_squeeze",
        "volatility_regime",
    }


def test_filter_by_market_and_timeframe() -> None:
    intraday = set(registry.ids(timeframe="1m"))
    assert intraday == {"opening_range_breakout", "vwap_reversion"}
    # forex excludes the equity/crypto-only intraday strategies
    assert "vwap_reversion" not in registry.ids(market="forex")
    assert "sma_crossover" in registry.ids(market="forex")
    # combined filters intersect
    assert set(registry.ids(category="mean_reversion", timeframe="1m")) == {
        "vwap_reversion"
    }
    assert registry.ids(category="trend", timeframe="1m") == []


def test_category_index_counts() -> None:
    counts = registry.categories()
    assert counts["trend"] == 3
    assert counts["mean_reversion"] == 4
    assert counts["momentum"] == 4
    assert counts["breakout"] == 3
    assert counts["volatility"] == 2


def test_duplicate_registration_rejected() -> None:
    reg = StrategyRegistry()

    class Dummy(StrategyPlugin):
        strategy_id = "dummy"
        name = "Dummy"
        category = StrategyCategory.TREND
        markets = ("crypto",)
        timeframes = ("1h",)

        def _evaluate(self, bars):
            return None

    reg.register(Dummy)
    reg.register(Dummy)  # same class again is a no-op
    assert len(reg) == 1

    class Clash(StrategyPlugin):
        strategy_id = "dummy"
        name = "Clash"
        category = StrategyCategory.TREND
        markets = ("crypto",)
        timeframes = ("1h",)

        def _evaluate(self, bars):
            return None

    with pytest.raises(DuplicateStrategyError):
        reg.register(Clash)


def test_unknown_strategy_raises() -> None:
    with pytest.raises(UnknownStrategyError):
        registry.get("does_not_exist")
