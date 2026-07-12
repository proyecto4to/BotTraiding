"""Orchestrator cycle unit tests: all downstream clients mocked.

Covers the task-spec matrix: signal -> approved -> order; signal ->
rejected -> no order; HARD_HALT -> whole cycle skipped; downstream timeout
-> degraded cycle that continues; consecutive failures -> auto-stop with
status=error.
"""

from __future__ import annotations

import asyncio
import uuid

from app import db as db_module
from app import orchestrator
from app.models import BotRow, CycleReportRow
from app.orchestrator import BotRunner, bot_to_spec, run_cycle
from app.schemas import BotOut

from .conftest import (
    FakeClientsBundle,
    FakeRisk,
    FakeStrategy,
    downstream_timeout,
    make_signal,
)


def make_spec(**overrides) -> BotOut:
    defaults = dict(
        id=str(uuid.uuid4()),
        name="bot",
        account_id="acct-1",
        broker="binance",
        execution_mode="paper",
        symbols=["BTCUSD"],
        timeframe="1h",
        strategy_keys=["sma_crossover"],
        params_overrides={},
        cycle_interval_seconds=60.0,
        status="running",
        created_by="user-1",
    )
    defaults.update(overrides)
    return BotOut(**defaults)


def run(coro):
    return asyncio.run(coro)


# --- signal -> approved -> order ---------------------------------------------


def test_signal_approved_places_order():
    signal = make_signal()
    clients = FakeClientsBundle(
        strategy=FakeStrategy({"sma_crossover": signal}),
        risk=FakeRisk(approved=True, max_size_allowed=7.5),
    )
    outcome = run(run_cycle(make_spec(), clients))

    assert outcome.status == "ok"
    assert len(outcome.signals) == 1
    assert len(outcome.decisions) == 1
    assert outcome.decisions[0]["approved"] is True
    assert len(outcome.orders) == 1

    submission = clients.execution.submissions[0]
    order = submission["order"]
    # sized from RiskDecision.max_size_allowed, never from the signal
    assert order["quantity"] == 7.5
    assert order["signal_id"] == signal["id"]
    assert order["execution_mode"] == "paper"
    assert order["broker"] == "binance"
    # the approving RiskDecision travels with the order (principle 2.4)
    assert submission["risk_decision"]["approved"] is True
    assert submission["risk_decision"]["signal_id"] == signal["id"]
    # market price from the last bar is forwarded for the paper transport
    assert submission["market_price"] is not None
    # the coordinator enriched the signal with the price risk needs
    validated = clients.risk.validate_calls[0]["signal"]
    assert validated["metadata"]["price"] == submission["market_price"]


def test_params_overrides_forwarded_per_strategy():
    signal = make_signal()
    strategy = FakeStrategy({"sma_crossover": signal})
    clients = FakeClientsBundle(strategy=strategy)
    spec = make_spec(params_overrides={"sma_crossover": {"fast_period": 5}})
    run(run_cycle(spec, clients))
    assert strategy.calls[0]["params"] == {"fast_period": 5}


# --- signal -> rejected -> no order --------------------------------------------


def test_signal_rejected_places_no_order():
    signal = make_signal()
    clients = FakeClientsBundle(
        strategy=FakeStrategy({"sma_crossover": signal}),
        risk=FakeRisk(approved=False),
    )
    outcome = run(run_cycle(make_spec(), clients))

    assert outcome.status == "ok"  # a rejection is a normal, healthy outcome
    assert len(outcome.decisions) == 1
    assert outcome.decisions[0]["approved"] is False
    assert outcome.orders == []
    assert clients.execution.submissions == []


def test_approved_with_zero_size_places_no_order():
    signal = make_signal()
    clients = FakeClientsBundle(
        strategy=FakeStrategy({"sma_crossover": signal}),
        risk=FakeRisk(approved=True, max_size_allowed=0.0),
    )
    outcome = run(run_cycle(make_spec(), clients))

    assert clients.execution.submissions == []
    assert outcome.orders == []
    assert outcome.status == "degraded"
    assert any(e["stage"] == "sizing" for e in outcome.errors)


# --- HARD_HALT -> skip cycle -----------------------------------------------------


def test_hard_halt_skips_whole_cycle():
    clients = FakeClientsBundle(risk=FakeRisk(breaker_state="HARD_HALT"))
    outcome = run(run_cycle(make_spec(), clients))

    assert outcome.status == "skipped"
    assert "hard_halt" in (outcome.reason or "")
    # nothing downstream was touched: no bars, no evaluations, no orders
    assert clients.market_data.calls == []
    assert clients.strategy.calls == []
    assert clients.execution.submissions == []


def test_breaker_fetch_failure_degrades_but_still_validates():
    signal = make_signal()
    risk = FakeRisk(approved=True)
    risk.breaker_error = downstream_timeout("risk-engine")
    clients = FakeClientsBundle(strategy=FakeStrategy({"sma_crossover": signal}), risk=risk)
    outcome = run(run_cycle(make_spec(), clients))

    assert outcome.status == "degraded"
    assert any(e["stage"] == "circuit_breaker" for e in outcome.errors)
    # risk validation still gates the order server-side
    assert len(risk.validate_calls) == 1
    assert len(outcome.orders) == 1


# --- downstream failures degrade, never kill ------------------------------------


def test_one_strategy_timeout_degrades_but_others_run():
    good_signal = make_signal(strategy_id="ema_crossover")
    clients = FakeClientsBundle(
        strategy=FakeStrategy(
            {
                "sma_crossover": downstream_timeout("strategy-engine"),
                "ema_crossover": good_signal,
            }
        ),
    )
    spec = make_spec(strategy_keys=["sma_crossover", "ema_crossover"])
    outcome = run(run_cycle(spec, clients))

    assert outcome.status == "degraded"
    assert any(e["stage"] == "evaluate" for e in outcome.errors)
    # the healthy strategy still produced an order
    assert len(outcome.orders) == 1
    assert len(clients.execution.submissions) == 1


def test_market_data_failure_for_all_symbols_is_error_cycle():
    clients = FakeClientsBundle()
    clients.market_data.error = downstream_timeout("broker-connectors")
    outcome = run(run_cycle(make_spec(symbols=["BTCUSD", "ETHUSD"]), clients))

    assert outcome.status == "error"
    assert len(outcome.errors) == 2
    assert clients.strategy.calls == []


def test_execution_failure_is_captured_not_raised():
    signal = make_signal()
    clients = FakeClientsBundle(strategy=FakeStrategy({"sma_crossover": signal}))
    clients.execution.error = downstream_timeout("execution-engine")
    outcome = run(run_cycle(make_spec(), clients))

    assert outcome.status == "degraded"
    assert any(e["stage"] == "execution" for e in outcome.errors)
    assert outcome.orders == []


# --- runner loop: auto-stop after consecutive failures ----------------------------


def _insert_bot(session_factory, **overrides) -> str:
    defaults = dict(
        name="bot",
        account_id="acct-1",
        broker="binance",
        execution_mode="paper",
        symbols=["BTCUSD"],
        timeframe="1h",
        strategy_keys=["sma_crossover"],
        params_overrides={},
        cycle_interval_seconds=0.01,
        status="running",
        created_by="user-1",
    )
    defaults.update(overrides)
    with session_factory() as db:
        row = BotRow(**defaults)
        db.add(row)
        db.commit()
        return row.id


def test_consecutive_errors_auto_stop(monkeypatch):
    monkeypatch.setenv("BOT_MAX_CONSECUTIVE_ERRORS", "3")

    failing = FakeClientsBundle()
    failing.market_data.error = downstream_timeout("broker-connectors")

    session_factory = db_module.SessionLocal
    bot_id = _insert_bot(session_factory)

    runner = BotRunner(
        session_factory=session_factory, clients_factory=lambda: failing
    )

    async def scenario():
        runner.start(bot_id)
        task = runner._tasks[bot_id]
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(scenario())

    with session_factory() as db:
        row = db.get(BotRow, bot_id)
        assert row.status == "error"
        assert "3 consecutive" in (row.status_reason or "")
        reports = db.query(CycleReportRow).filter_by(bot_id=bot_id).all()
        assert len(reports) == 3
        assert all(r.status == "error" for r in reports)
    assert not runner.is_running(bot_id)


def test_clean_cycle_resets_failure_counter(monkeypatch):
    monkeypatch.setenv("BOT_MAX_CONSECUTIVE_ERRORS", "2")

    session_factory = db_module.SessionLocal
    bot_id = _insert_bot(session_factory)

    # alternate: fail, succeed, fail, succeed... never 2 consecutive
    healthy = FakeClientsBundle(strategy=FakeStrategy({"sma_crossover": None}))
    failing = FakeClientsBundle()
    failing.market_data.error = downstream_timeout("broker-connectors")
    sequence = [failing, healthy, failing, healthy]
    calls = {"n": 0}

    def factory():
        bundle = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        return bundle

    runner = BotRunner(session_factory=session_factory, clients_factory=factory)

    async def scenario():
        runner.start(bot_id)
        for _ in range(200):
            await asyncio.sleep(0.02)
            with session_factory() as db:
                if db.query(CycleReportRow).filter_by(bot_id=bot_id).count() >= 4:
                    break
        await runner.stop(bot_id)

    asyncio.run(scenario())

    with session_factory() as db:
        row = db.get(BotRow, bot_id)
        assert row.status == "running"  # never auto-stopped


def test_loop_exits_when_bot_stopped_in_db():
    session_factory = db_module.SessionLocal
    bot_id = _insert_bot(session_factory, status="stopped")

    runner = BotRunner(
        session_factory=session_factory, clients_factory=FakeClientsBundle
    )

    async def scenario():
        runner.start(bot_id)
        await asyncio.wait_for(runner._tasks[bot_id], timeout=2.0)

    asyncio.run(scenario())
    with session_factory() as db:
        assert db.query(CycleReportRow).filter_by(bot_id=bot_id).count() == 0


def test_mark_orphaned_bots():
    session_factory = db_module.SessionLocal
    bot_id = _insert_bot(session_factory, status="running")
    with session_factory() as db:
        marked = orchestrator.mark_orphaned_bots(db)
        db.commit()
        assert marked == 1
        row = db.get(BotRow, bot_id)
        assert row.status == "error"
        assert "orphaned" in (row.status_reason or "")


def test_bot_to_spec_roundtrip():
    session_factory = db_module.SessionLocal
    bot_id = _insert_bot(session_factory, params_overrides={"sma_crossover": {"fast_period": 4}})
    with session_factory() as db:
        spec = bot_to_spec(db.get(BotRow, bot_id))
    assert spec.id == bot_id
    assert spec.params_overrides == {"sma_crossover": {"fast_period": 4}}
    assert spec.execution_mode.value == "paper"
