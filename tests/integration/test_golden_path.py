"""The golden end-to-end path, with REAL service code in-process:

synthetic uptrend bars -> strategy-engine (sma_crossover) emits a buy ->
risk-engine approves against portfolio-engine state with a sized quantity ->
execution-engine routes paper -> paper-trading fills with spread/slippage ->
execution report reaches portfolio-engine -> position exists, cash
decreased, PnL updates after a mark.
"""

from __future__ import annotations

import uuid

from .conftest import synthetic_uptrend_bars

ACCOUNT = "acct-int-golden"
SYMBOL = "BTCUSD"
STARTING_CASH = 100_000.0


def _bot_spec(platform, account_id: str = ACCOUNT):
    schemas = platform.trading.get("schemas")
    return schemas.BotOut(
        id=str(uuid.uuid4()),
        name="golden-bot",
        account_id=account_id,
        broker="binance",
        execution_mode="paper",
        symbols=[SYMBOL],
        timeframe="1h",
        strategy_keys=["sma_crossover"],
        params_overrides={},
        cycle_interval_seconds=60.0,
        status="running",
        created_by="integration-user",
    )


def test_golden_path_signal_to_position(platform):
    bars = synthetic_uptrend_bars(symbol=SYMBOL)
    platform.bars_by_symbol[SYMBOL] = bars
    last_close = bars[-1]["close"]

    orchestrator = platform.trading.get("orchestrator")
    outcome = platform.run(orchestrator.run_cycle(_bot_spec(platform), platform.clients))

    # --- the strategy proposed a buy on the last bar ------------------------
    assert outcome.errors == [], outcome.errors
    assert outcome.status == "ok"
    assert len(outcome.signals) == 1
    assert outcome.signals[0]["side"] == "buy"
    assert outcome.signals[0]["strategy_key"] == "sma_crossover"

    # --- risk-engine approved with a sized quantity --------------------------
    assert len(outcome.decisions) == 1
    decision = outcome.decisions[0]
    assert decision["approved"] is True
    assert decision["max_size_allowed"] > 0
    assert decision["adjusted_stop"] is not None
    assert decision["adjusted_stop"] < last_close  # protective stop below entry

    # --- execution-engine routed paper and paper-trading filled --------------
    assert len(outcome.orders) == 1
    order = outcome.orders[0]
    assert order["status"] == "filled"
    assert order["quantity"] == decision["max_size_allowed"]
    assert order["filled_quantity"] == order["quantity"]
    # buy fills pay up: spread/slippage push the fill above the mid price
    assert order["average_fill_price"] > last_close

    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert len(executions) == 1
    assert executions[0]["status"] == "filled"
    assert executions[0]["execution_mode"] == "paper"

    # --- paper-trading account debited ---------------------------------------
    paper_account = platform.get_json(platform.paper_http, f"/paper/accounts/{ACCOUNT}")
    assert paper_account["cash"] < STARTING_CASH

    # --- portfolio-engine holds the position, cash decreased ------------------
    state = platform.get_json(platform.portfolio_http, f"/portfolio/{ACCOUNT}")
    positions = {p["symbol"]: p for p in state["positions"]}
    assert SYMBOL in positions
    position = positions[SYMBOL]
    assert position["quantity"] == order["filled_quantity"]
    assert position["average_price"] == order["average_fill_price"]
    assert state["account"]["balance"] < STARTING_CASH

    # --- PnL updates after a mark ----------------------------------------------
    marked = platform.post_json(
        platform.portfolio_http,
        f"/portfolio/{ACCOUNT}/mark",
        {"prices": {SYMBOL: last_close * 1.05}},
    )
    assert marked["unrealized_pnl"] > 0
    assert marked["account"]["equity"] > state["account"]["balance"]


def test_flat_market_produces_no_signal_no_order(platform):
    # flat closes: the real sma_crossover must stay silent -> nothing flows
    from .conftest import bars_from_closes

    platform.bars_by_symbol[SYMBOL] = bars_from_closes([100.0] * 60, symbol=SYMBOL)

    orchestrator = platform.trading.get("orchestrator")
    outcome = platform.run(orchestrator.run_cycle(_bot_spec(platform), platform.clients))

    assert outcome.status == "ok"
    assert outcome.signals == []
    assert outcome.orders == []
    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert executions == []
