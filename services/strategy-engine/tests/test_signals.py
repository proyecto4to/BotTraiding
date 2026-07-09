"""Every builtin strategy produces deterministic signals on synthetic data
designed to trigger its entry condition, and stays silent on flat data."""

from __future__ import annotations

import pytest

from trading_contracts import OrderSide, StrategyContext
from trading_strategies import load_builtin_strategies, registry

from .synthetic import (
    divergence_bars,
    flat_bars,
    orb_bars,
    overbought_bars,
    oversold_bars,
    scan_signals,
    squeeze_bars,
    trend_down_bars,
    trend_up_bars,
    vol_regime_bars,
    vwap_bars,
)

load_builtin_strategies()

# (strategy_id, params, bars_factory, phase_start): a signal of the expected
# side must fire at/after `phase_start` (the index where the designed setup
# begins; earlier opposite signals in e.g. the downtrend leg are legitimate).
BUY_CASES = [
    ("sma_crossover", {}, trend_up_bars, 70),
    ("ema_crossover", {}, trend_up_bars, 70),
    ("macd_trend", {}, trend_up_bars, 70),
    ("donchian_breakout", {}, trend_up_bars, 70),
    ("atr_channel_breakout", {}, trend_up_bars, 70),
    ("roc_momentum", {}, trend_up_bars, 70),
    ("dual_momentum", {}, trend_up_bars, 70),
    ("momentum_ranking", {}, trend_up_bars, 70),
    ("bollinger_reversion", {}, oversold_bars, 40),
    ("rsi2_reversion", {}, oversold_bars, 40),
    ("zscore_reversion", {}, oversold_bars, 40),
    ("vwap_reversion", {}, vwap_bars, 40),
    ("opening_range_breakout", {}, orb_bars, 16),
    ("keltner_squeeze", {}, squeeze_bars, 40),
    ("volatility_regime", {}, vol_regime_bars, 60),
    ("rsi_divergence", {"lookback": 30}, divergence_bars, 45),
]

SELL_CASES = [
    ("sma_crossover", {}, trend_down_bars, 70),
    ("donchian_breakout", {}, trend_down_bars, 70),
    ("roc_momentum", {}, trend_down_bars, 70),
    ("rsi2_reversion", {}, overbought_bars, 40),
    ("bollinger_reversion", {}, overbought_bars, 40),
]


def _first_of_side(signals, side: OrderSide, phase_start: int):
    for index, signal in signals:
        if index >= phase_start and signal.side is side:
            return index, signal
    return None


def _assert_signal_sanity(signal, side: OrderSide, strategy_id: str) -> None:
    assert signal.strategy_id == strategy_id
    assert signal.side is side
    assert 0.0 <= signal.confidence <= 1.0
    assert signal.suggested_size > 0.0
    entry = signal.metadata["entry_price"]
    if signal.stop_loss is not None:
        if side is OrderSide.BUY:
            assert signal.stop_loss < entry
        else:
            assert signal.stop_loss > entry
    if signal.take_profit is not None:
        if side is OrderSide.BUY:
            assert signal.take_profit > entry
        else:
            assert signal.take_profit < entry


@pytest.mark.parametrize(
    "strategy_id,params,bars_factory,phase_start",
    BUY_CASES,
    ids=[c[0] for c in BUY_CASES],
)
def test_buy_setup_fires(strategy_id, params, bars_factory, phase_start) -> None:
    bars = bars_factory()
    plugin = registry.create(strategy_id, params)
    hit = _first_of_side(scan_signals(plugin, bars), OrderSide.BUY, phase_start)
    assert hit is not None, f"{strategy_id} never proposed a BUY on its setup"
    _assert_signal_sanity(hit[1], OrderSide.BUY, strategy_id)


@pytest.mark.parametrize(
    "strategy_id,params,bars_factory,phase_start",
    SELL_CASES,
    ids=[c[0] for c in SELL_CASES],
)
def test_sell_setup_fires(strategy_id, params, bars_factory, phase_start) -> None:
    bars = bars_factory()
    plugin = registry.create(strategy_id, params)
    hit = _first_of_side(scan_signals(plugin, bars), OrderSide.SELL, phase_start)
    assert hit is not None, f"{strategy_id} never proposed a SELL on its setup"
    _assert_signal_sanity(hit[1], OrderSide.SELL, strategy_id)


@pytest.mark.parametrize(
    "strategy_id,params,bars_factory,phase_start",
    BUY_CASES,
    ids=[c[0] for c in BUY_CASES],
)
def test_signals_are_deterministic(strategy_id, params, bars_factory, phase_start) -> None:
    bars = bars_factory()
    plugin = registry.create(strategy_id, params)
    hit = _first_of_side(scan_signals(plugin, bars), OrderSide.BUY, phase_start)
    assert hit is not None
    index, first = hit
    prefix = bars[: index + 1]
    again = registry.create(strategy_id, params).evaluate(prefix)
    assert again is not None
    assert again.model_dump(exclude={"id"}) == first.model_dump(exclude={"id"})
    assert first.generated_at == prefix[-1].timestamp


@pytest.mark.parametrize("strategy_id", sorted(registry.ids()))
def test_no_signal_on_flat_data(strategy_id: str) -> None:
    plugin = registry.create(strategy_id)
    assert scan_signals(plugin, flat_bars()) == []


def test_on_bar_context_path_matches_evaluate() -> None:
    bars = trend_up_bars()
    plugin = registry.create("sma_crossover")
    hit = _first_of_side(scan_signals(plugin, bars), OrderSide.BUY, 70)
    assert hit is not None
    index, direct = hit
    prefix = bars[: index + 1]
    context = StrategyContext(
        symbol="TEST",
        timeframe="1h",
        data={"bars": [b.model_dump() for b in prefix], "market": "crypto"},
    )
    via_context = registry.create("sma_crossover").on_bar(context)
    assert via_context is not None
    assert via_context.market == "crypto"
    assert via_context.side is direct.side
    assert via_context.stop_loss == direct.stop_loss
    assert via_context.take_profit == direct.take_profit


def test_evaluate_handles_empty_and_short_series() -> None:
    plugin = registry.create("sma_crossover")
    assert plugin.evaluate([]) is None
    assert plugin.evaluate(trend_up_bars()[:5]) is None
