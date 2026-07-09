"""Unit tests per risk check: each limit passes at the boundary and fails
strictly over it; missing critical data fails safe."""

from __future__ import annotations

from app.checks import (
    CorrelationCheck,
    DailyLossCheck,
    FloatingDrawdownCheck,
    LeverageCheck,
    LiquidityCheck,
    MarginCheck,
    MaxDrawdownCheck,
    MonthlyLossCheck,
    PerTradeRiskCheck,
    SectorExposureCheck,
    SlippageCheck,
    SymbolExposureCheck,
    TotalExposureCheck,
    VolatilityCheck,
    WeeklyLossCheck,
)
from app.context import build_context
from app.limits import default_limits
from tests.conftest import make_signal, make_state
from trading_contracts import Position


def ctx_for(signal=None, state=None, limits=None):
    return build_context(
        signal or make_signal(),
        limits or default_limits(),
        state or make_state(),
        "acc-1",
    )


# --- per-trade risk (1% of 100k equity = 1000; stop distance 5) -----------


def test_per_trade_risk_passes_at_boundary():
    # 200 * 5 = 1000 = exactly 1% of equity
    ctx = ctx_for(make_signal(suggested_size=200, price=100, stop_loss=95))
    assert PerTradeRiskCheck().run(ctx).passed is True


def test_per_trade_risk_fails_over_boundary():
    ctx = ctx_for(make_signal(suggested_size=200.5, price=100, stop_loss=95))
    result = PerTradeRiskCheck().run(ctx)
    assert result.passed is False
    assert "risk_per_trade" in result.reason


def test_per_trade_risk_fails_without_stop():
    ctx = ctx_for(make_signal(stop_loss=None))
    result = PerTradeRiskCheck().run(ctx)
    assert result.passed is False
    assert result.reason == "no_stop_loss"


def test_per_trade_risk_fails_without_price():
    ctx = ctx_for(make_signal(price=None))
    assert PerTradeRiskCheck().run(ctx).reason == "no_entry_price"


def test_per_trade_risk_uses_atr_derived_stop():
    # no stop_loss but atr=2.5 with default multiple 2 -> stop 95, distance 5
    ctx = ctx_for(make_signal(stop_loss=None, suggested_size=200, metadata={"atr": 2.5}))
    assert PerTradeRiskCheck().run(ctx).passed is True


# --- loss limits (defaults: 3% / 6% / 10% of 100k) ------------------------


def test_daily_loss_boundary():
    assert DailyLossCheck().run(ctx_for(state=make_state(pnl_daily=-3000))).passed is True
    assert DailyLossCheck().run(ctx_for(state=make_state(pnl_daily=-3001))).passed is False


def test_daily_loss_profit_passes():
    assert DailyLossCheck().run(ctx_for(state=make_state(pnl_daily=5000))).passed is True


def test_weekly_loss_boundary():
    assert WeeklyLossCheck().run(ctx_for(state=make_state(pnl_weekly=-6000))).passed is True
    assert WeeklyLossCheck().run(ctx_for(state=make_state(pnl_weekly=-6001))).passed is False


def test_monthly_loss_boundary():
    assert MonthlyLossCheck().run(ctx_for(state=make_state(pnl_monthly=-10000))).passed is True
    assert MonthlyLossCheck().run(ctx_for(state=make_state(pnl_monthly=-10001))).passed is False


# --- drawdown (defaults: 20% max, 10% floating) ----------------------------


def test_max_drawdown_boundary():
    assert MaxDrawdownCheck().run(ctx_for(state=make_state(current_drawdown=0.20))).passed
    assert not MaxDrawdownCheck().run(ctx_for(state=make_state(current_drawdown=0.2001))).passed


def test_floating_drawdown_boundary():
    assert FloatingDrawdownCheck().run(
        ctx_for(state=make_state(floating_drawdown=0.10))
    ).passed
    assert not FloatingDrawdownCheck().run(
        ctx_for(state=make_state(floating_drawdown=0.1001))
    ).passed


# --- correlation (default limit 0.75) ---------------------------------------


def _corr_state(msft_returns):
    return make_state(
        positions=[
            Position(symbol="MSFT", quantity=10, average_price=200, account_id="acc-1")
        ],
        returns={"MSFT": msft_returns},
    )


def test_correlation_rejects_perfectly_correlated():
    series = [0.01, -0.02, 0.03, -0.01]
    ctx = ctx_for(
        make_signal(metadata={"returns": series}), state=_corr_state(series)
    )
    result = CorrelationCheck().run(ctx)
    assert result.passed is False
    assert "MSFT" in result.reason


def test_correlation_rejects_perfectly_anticorrelated():
    series = [0.01, -0.02, 0.03, -0.01]
    inverse = [-x for x in series]
    ctx = ctx_for(make_signal(metadata={"returns": inverse}), state=_corr_state(series))
    assert CorrelationCheck().run(ctx).passed is False


def test_correlation_passes_uncorrelated():
    ctx = ctx_for(
        make_signal(metadata={"returns": [0.01, 0.01, -0.01, -0.01]}),
        state=_corr_state([0.01, -0.01, 0.01, -0.01]),
    )
    assert CorrelationCheck().run(ctx).passed is True


def test_correlation_passes_with_note_when_no_data():
    ctx = ctx_for(make_signal(), state=_corr_state([0.01, -0.02, 0.03]))
    result = CorrelationCheck().run(ctx)
    assert result.passed is True
    assert result.reason == "no_return_data_for_signal"


def test_correlation_ignores_same_symbol():
    series = [0.01, -0.02, 0.03, -0.01]
    state = make_state(
        positions=[
            Position(symbol="AAPL", quantity=10, average_price=100, account_id="acc-1")
        ],
        returns={"AAPL": series},
    )
    ctx = ctx_for(make_signal(symbol="AAPL", metadata={"returns": series}), state=state)
    assert CorrelationCheck().run(ctx).passed is True


# --- exposure (defaults: 25% symbol, 40% sector, 2.0x total/leverage) -------


def test_symbol_exposure_boundary():
    # 250 * 100 = 25000 = exactly 25% of 100k
    assert SymbolExposureCheck().run(ctx_for(make_signal(suggested_size=250))).passed
    assert not SymbolExposureCheck().run(ctx_for(make_signal(suggested_size=251))).passed


def test_symbol_exposure_counts_existing_position():
    state = make_state(
        positions=[
            Position(symbol="AAPL", quantity=100, average_price=100, account_id="acc-1")
        ],
        per_symbol={"AAPL": 10000.0},
        gross_exposure=10000.0,
    )
    assert SymbolExposureCheck().run(
        ctx_for(make_signal(suggested_size=150), state=state)
    ).passed
    assert not SymbolExposureCheck().run(
        ctx_for(make_signal(suggested_size=151), state=state)
    ).passed


def test_symbol_exposure_reducing_trade_passes():
    state = make_state(
        positions=[
            Position(symbol="AAPL", quantity=400, average_price=100, account_id="acc-1")
        ],
        per_symbol={"AAPL": 40000.0},
        gross_exposure=40000.0,
    )
    ctx = ctx_for(make_signal(side="sell", suggested_size=200, stop_loss=105), state=state)
    assert SymbolExposureCheck().run(ctx).passed is True


def test_sector_exposure_boundary():
    state = make_state(per_sector={"tech": 30000.0}, gross_exposure=30000.0)
    passing = ctx_for(make_signal(suggested_size=100, metadata={"sector": "tech"}), state=state)
    failing = ctx_for(make_signal(suggested_size=101, metadata={"sector": "tech"}), state=state)
    assert SectorExposureCheck().run(passing).passed is True
    assert SectorExposureCheck().run(failing).passed is False


def test_total_exposure_and_leverage_boundary():
    state = make_state(gross_exposure=190000.0)
    passing = ctx_for(make_signal(suggested_size=100), state=state)  # -> 200k = 2.0x
    assert TotalExposureCheck().run(passing).passed is True
    assert LeverageCheck().run(passing).passed is True

    state_over = make_state(gross_exposure=190001.0)
    failing = ctx_for(make_signal(suggested_size=100), state=state_over)
    assert TotalExposureCheck().run(failing).passed is False
    assert LeverageCheck().run(failing).passed is False


def test_margin_boundary():
    # buy 100 @ 100 requires 10000 additional notional
    state = make_state(free_margin=10000.0)
    assert MarginCheck().run(ctx_for(make_signal(suggested_size=100), state=state)).passed
    tight = make_state(free_margin=9999.0)
    assert not MarginCheck().run(ctx_for(make_signal(suggested_size=100), state=tight)).passed


def test_margin_reducing_trade_needs_none():
    state = make_state(
        positions=[
            Position(symbol="AAPL", quantity=100, average_price=100, account_id="acc-1")
        ],
        per_symbol={"AAPL": 10000.0},
        gross_exposure=10000.0,
        free_margin=0.0,
    )
    ctx = ctx_for(make_signal(side="sell", suggested_size=50, stop_loss=105), state=state)
    assert MarginCheck().run(ctx).passed is True


# --- market guards (disabled by default; enabled via limits) ----------------


def test_liquidity_disabled_by_default():
    assert LiquidityCheck().run(ctx_for()).reason == "liquidity_guard_disabled"


def test_liquidity_boundary_and_missing_data():
    limits = default_limits().model_copy(update={"min_volume": 1000.0})
    ok = ctx_for(make_signal(metadata={"volume": 1000}), limits=limits)
    low = ctx_for(make_signal(metadata={"volume": 999}), limits=limits)
    missing = ctx_for(make_signal(), limits=limits)
    assert LiquidityCheck().run(ok).passed is True
    assert LiquidityCheck().run(low).passed is False
    assert LiquidityCheck().run(missing).reason == "volume_metadata_missing"


def test_slippage_boundary_and_missing_data():
    limits = default_limits().model_copy(update={"max_slippage": 0.01})
    ok = ctx_for(make_signal(metadata={"expected_slippage": 0.01}), limits=limits)
    over = ctx_for(make_signal(metadata={"expected_slippage": 0.011}), limits=limits)
    missing = ctx_for(make_signal(), limits=limits)
    assert SlippageCheck().run(ok).passed is True
    assert SlippageCheck().run(over).passed is False
    assert SlippageCheck().run(missing).passed is False
    assert SlippageCheck().run(ctx_for()).reason == "slippage_guard_disabled"


def test_volatility_boundary_atr_fallback_and_missing_data():
    limits = default_limits().model_copy(update={"max_volatility": 0.05})
    ok = ctx_for(make_signal(metadata={"volatility": 0.05}), limits=limits)
    over = ctx_for(make_signal(metadata={"volatility": 0.051}), limits=limits)
    atr_ok = ctx_for(make_signal(metadata={"atr": 5.0}), limits=limits)  # 5/100 = 0.05
    atr_over = ctx_for(make_signal(metadata={"atr": 5.2}), limits=limits)
    missing = ctx_for(make_signal(), limits=limits)
    assert VolatilityCheck().run(ok).passed is True
    assert VolatilityCheck().run(over).passed is False
    assert VolatilityCheck().run(atr_ok).passed is True
    assert VolatilityCheck().run(atr_over).passed is False
    assert VolatilityCheck().run(missing).passed is False
    assert VolatilityCheck().run(ctx_for()).reason == "volatility_guard_disabled"
