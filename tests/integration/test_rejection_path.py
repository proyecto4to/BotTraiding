"""Rejection paths with REAL risk-engine code: a signal that breaches the
account's limits produces NO order anywhere and a persisted risk_event;
a HARD_HALT breaker skips the whole cycle before any market data is read.
"""

from __future__ import annotations

import uuid

from .conftest import auth_headers, synthetic_uptrend_bars

ACCOUNT = "acct-int-reject"
SYMBOL = "BTCUSD"


def _bot_spec(platform):
    schemas = platform.trading.get("schemas")
    return schemas.BotOut(
        id=str(uuid.uuid4()),
        name="reject-bot",
        account_id=ACCOUNT,
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


def test_limit_breach_rejects_no_order_risk_event_persisted(platform):
    platform.bars_by_symbol[SYMBOL] = synthetic_uptrend_bars(symbol=SYMBOL)

    # Tighten the account's real limits so ANY trade risk is absurd relative
    # to them (admin-gated endpoint, exercised with a real JWT).
    limits = platform.get_json(platform.risk_http, f"/risk/limits/{ACCOUNT}")["limits"]
    limits["max_risk_per_trade"] = 1e-9
    platform.run(_put_limits(platform, limits))

    orchestrator = platform.trading.get("orchestrator")
    outcome = platform.run(orchestrator.run_cycle(_bot_spec(platform), platform.clients))

    # signal emitted, decision rejected, no order built or submitted
    assert len(outcome.signals) == 1
    assert len(outcome.decisions) == 1
    assert outcome.decisions[0]["approved"] is False
    assert "per_trade_risk" in outcome.decisions[0]["reason"]
    assert outcome.orders == []
    assert outcome.status == "ok"  # a rejection is risk doing its job

    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert executions == []

    # the rejection was persisted as a risk_event (audit trail)
    events = platform.get_json(platform.risk_http, f"/risk/events/{ACCOUNT}")
    assert any(e["event_type"] == "risk.rejected" for e in events)

    # and the portfolio never changed
    state = platform.get_json(platform.portfolio_http, f"/portfolio/{ACCOUNT}")
    assert state["positions"] == []
    assert state["account"]["balance"] == 100_000.0


async def _put_limits(platform, limits: dict):
    response = await platform.risk_http.put(
        f"/risk/limits/{ACCOUNT}", json=limits, headers=auth_headers(["admin"])
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_hard_halt_breaker_skips_cycle_entirely(platform):
    platform.bars_by_symbol[SYMBOL] = synthetic_uptrend_bars(symbol=SYMBOL)

    # Trip the REAL breaker row in risk-engine's DB (only an admin reset can
    # de-escalate it, so writing the row mirrors an escalated state).
    risk = platform.services["risk"]
    with risk.get("db").SessionLocal() as session:
        session.add(
            risk.get("models").CircuitBreakerRow(
                account_id=ACCOUNT, state="HARD_HALT", reason="integration-tripped"
            )
        )
        session.commit()

    orchestrator = platform.trading.get("orchestrator")
    outcome = platform.run(orchestrator.run_cycle(_bot_spec(platform), platform.clients))

    assert outcome.status == "skipped"
    assert "hard_halt" in (outcome.reason or "")
    assert outcome.signals == []
    assert outcome.orders == []

    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert executions == []
