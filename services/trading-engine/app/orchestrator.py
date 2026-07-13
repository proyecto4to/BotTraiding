"""The bot cycle loop: MarketData -> Strategy -> Risk -> Execution.

docs/ARCHITECTURE.md section 4, implemented as a coordinator with no
trading logic of its own:

    bars = broker-connectors.historical()          (read-only market data)
    signal = strategy-engine.evaluate(bars)         (strategies only propose)
    decision = risk-engine.validate(signal)         (no bypass, principle 2.4)
    if decision.approved: execution-engine.submit(order + decision)

Invariants enforced here:
- trading-engine NEVER talks to a broker: orders only go to
  execution-engine, market data only comes from broker-connectors' API;
- no RiskDecision -> no Order: an order is built exclusively from an
  approved decision, sized from RiskDecision.max_size_allowed, and the
  decision travels with it;
- HARD_HALT: the whole cycle is skipped (and logged) when the account's
  circuit breaker is in HARD_HALT;
- resilience: every downstream failure is captured into the CycleReport
  (cycle 'degraded'), never propagated - one failing strategy or service
  must not kill the loop. BOT_MAX_CONSECUTIVE_ERRORS consecutive
  degraded/error cycles auto-stop the bot with status=error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, events
from .clients import Clients, DownstreamError, get_clients
from .models import BotRow, CycleReportRow
from .schemas import (
    BOT_STATUS_ERROR,
    BOT_STATUS_RUNNING,
    BotOut,
)

logger = logging.getLogger("trading-engine.orchestrator")

CYCLE_OK = "ok"
CYCLE_DEGRADED = "degraded"
CYCLE_SKIPPED = "skipped"
CYCLE_ERROR = "error"

HARD_HALT = "HARD_HALT"


@dataclass
class CycleOutcome:
    """In-memory result of one cycle; persisted as a CycleReportRow."""

    bot_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str = CYCLE_OK
    reason: Optional[str] = None
    signals: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def record_error(self, stage: str, error: str, **context: Any) -> None:
        entry = {"stage": stage, "error": error}
        entry.update({k: v for k, v in context.items() if v is not None})
        self.errors.append(entry)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def bot_to_spec(row: BotRow) -> BotOut:
    return BotOut(
        id=row.id,
        name=row.name,
        account_id=row.account_id,
        broker=row.broker,
        execution_mode=row.execution_mode,
        symbols=list(row.symbols or []),
        timeframe=row.timeframe,
        strategy_keys=list(row.strategy_keys or []),
        params_overrides=dict(row.params_overrides or {}),
        risk_allocation=row.risk_allocation,
        cycle_interval_seconds=row.cycle_interval_seconds,
        status=row.status,
        status_reason=row.status_reason,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_order(bot: BotOut, signal: dict[str, Any], quantity: float) -> dict[str, Any]:
    """Approved-decision-only order construction (never called without one).

    Sized from RiskDecision.max_size_allowed; the stop travels in the
    RiskDecision context (adjusted_stop) submitted alongside the order."""
    return {
        "id": str(uuid.uuid4()),
        "signal_id": signal["id"],
        "symbol": signal["symbol"],
        "side": signal["side"],
        "quantity": quantity,
        "order_type": "market",
        "price": None,
        "status": "pending",
        "broker": bot.broker,
        "account_id": bot.account_id,
        "execution_mode": bot.execution_mode.value,
        "created_at": _now().isoformat(),
    }


async def _process_signal(
    bot: BotOut,
    clients: Clients,
    outcome: CycleOutcome,
    strategy_key: str,
    symbol: str,
    signal: dict[str, Any],
    market_price: Optional[float],
) -> None:
    """One signal through risk validation and (if approved) execution."""
    outcome.signals.append(
        {
            "signal_id": signal.get("id"),
            "strategy_key": strategy_key,
            "symbol": symbol,
            "side": signal.get("side"),
            "confidence": signal.get("confidence"),
        }
    )

    # The coordinator owns the market data, so it enriches the signal with
    # the price risk-engine needs for sizing/exposure projections (risk
    # logic itself stays entirely in risk-engine).
    if market_price is not None:
        signal.setdefault("metadata", {}).setdefault("price", market_price)

    # The bot's capital allocation (P7), if set, caps its per-trade risk so the
    # AI's weighting actually scales order size (risk-engine still enforces the
    # account limits on top).
    risk_override = (bot.risk_allocation or {}).get("risk_per_trade")
    try:
        decision = await clients.risk.validate(
            signal, bot.account_id, risk_per_trade_override=risk_override
        )
    except DownstreamError as exc:
        outcome.record_error(
            "risk_validate", str(exc), strategy_key=strategy_key, symbol=symbol
        )
        return

    outcome.decisions.append(
        {
            "signal_id": decision.get("signal_id"),
            "approved": decision.get("approved"),
            "reason": decision.get("reason"),
            "max_size_allowed": decision.get("max_size_allowed"),
            "adjusted_stop": decision.get("adjusted_stop"),
            "circuit_breaker_state": decision.get("circuit_breaker_state"),
        }
    )

    if not decision.get("approved"):
        return  # rejected -> no order, ever (principle 2.4)

    quantity = float(decision.get("max_size_allowed") or 0.0)
    if quantity <= 0:
        outcome.record_error(
            "sizing",
            "decision approved but max_size_allowed is not positive; order skipped",
            strategy_key=strategy_key,
            symbol=symbol,
        )
        return

    order = _build_order(bot, signal, quantity)
    try:
        execution = await clients.execution.submit(order, decision, market_price=market_price)
    except DownstreamError as exc:
        outcome.record_error("execution", str(exc), strategy_key=strategy_key, symbol=symbol)
        return

    outcome.orders.append(
        {
            "order_id": order["id"],
            "signal_id": order["signal_id"],
            "execution_id": execution.get("id"),
            "symbol": symbol,
            "side": order["side"],
            "quantity": quantity,
            "status": execution.get("status"),
            "filled_quantity": execution.get("filled_quantity"),
            "average_fill_price": execution.get("average_fill_price"),
            "adjusted_stop": decision.get("adjusted_stop"),
        }
    )


async def run_cycle(bot: BotOut, clients: Clients) -> CycleOutcome:
    """One full cycle for one bot. Never raises: every downstream failure is
    captured into the returned CycleOutcome."""
    outcome = CycleOutcome(bot_id=bot.id, started_at=_now())

    # --- circuit breaker gate: HARD_HALT skips the whole cycle -------------
    try:
        breaker = await clients.risk.get_circuit_breaker(bot.account_id)
        if breaker.get("state") == HARD_HALT:
            outcome.status = CYCLE_SKIPPED
            outcome.reason = (
                f"circuit_breaker_hard_halt: {breaker.get('reason') or 'halted'}"
            )
            outcome.finished_at = _now()
            logger.warning(
                "cycle_skipped %s",
                json.dumps(
                    {
                        "event": "cycle_skipped",
                        "bot_id": bot.id,
                        "account_id": bot.account_id,
                        "reason": outcome.reason,
                    }
                ),
            )
            return outcome
    except DownstreamError as exc:
        # Fail-open here is safe: /risk/validate re-checks the breaker
        # server-side before anything can execute.
        outcome.record_error("circuit_breaker", str(exc))

    symbols_fetched = 0
    for symbol in bot.symbols:
        try:
            bars = await clients.market_data.get_bars(
                bot.broker, symbol, bot.timeframe, account_id=bot.account_id
            )
        except DownstreamError as exc:
            outcome.record_error("market_data", str(exc), symbol=symbol)
            continue
        if not bars:
            outcome.record_error("market_data", "no bars returned", symbol=symbol)
            continue
        symbols_fetched += 1
        try:
            market_price = float(bars[-1]["close"])
        except (KeyError, TypeError, ValueError):
            market_price = None

        for strategy_key in bot.strategy_keys:
            try:
                signal = await clients.strategy.evaluate(
                    strategy_key,
                    bars,
                    params=bot.params_overrides.get(strategy_key, {}),
                    user_id=bot.created_by,
                    account_id=bot.account_id,
                )
            except DownstreamError as exc:
                outcome.record_error(
                    "evaluate", str(exc), strategy_key=strategy_key, symbol=symbol
                )
                continue
            if signal is None:
                continue
            await _process_signal(
                bot, clients, outcome, strategy_key, symbol, signal, market_price
            )

    if outcome.errors:
        outcome.status = CYCLE_ERROR if symbols_fetched == 0 else CYCLE_DEGRADED
    outcome.finished_at = outcome.finished_at or _now()
    return outcome


def persist_outcome(db: Session, outcome: CycleOutcome) -> CycleReportRow:
    row = CycleReportRow(
        bot_id=outcome.bot_id,
        status=outcome.status,
        reason=outcome.reason,
        started_at=outcome.started_at.replace(tzinfo=None),
        finished_at=(outcome.finished_at or _now()).replace(tzinfo=None),
        signals=outcome.signals,
        decisions=outcome.decisions,
        orders=outcome.orders,
        errors=outcome.errors,
    )
    db.add(row)
    db.flush()
    return row


async def publish_cycle_event(bot: BotOut, row: CycleReportRow) -> None:
    await events.publish_event(
        "bot.cycle",
        {
            "bot_id": bot.id,
            "cycle_id": row.id,
            "account_id": bot.account_id,
            "status": row.status,
            "reason": row.reason,
            "signals": len(row.signals),
            "decisions": len(row.decisions),
            "orders": len(row.orders),
            "errors": len(row.errors),
        },
    )


def _default_session_factory() -> Session:
    from . import db as db_module  # late import: tests swap db.SessionLocal

    return db_module.SessionLocal()


class BotRunner:
    """Owns one asyncio task per running bot.

    Each task loops: reload bot config -> run_cycle -> persist CycleReport ->
    publish bot.cycle -> sleep(cycle_interval). BOT_MAX_CONSECUTIVE_ERRORS
    consecutive degraded/error cycles set status=error and stop the task."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = _default_session_factory,
        clients_factory: Callable[[], Clients] = get_clients,
    ) -> None:
        self.session_factory = session_factory
        self.clients_factory = clients_factory
        self._tasks: dict[str, asyncio.Task] = {}

    def is_running(self, bot_id: str) -> bool:
        task = self._tasks.get(bot_id)
        return task is not None and not task.done()

    def start(self, bot_id: str) -> None:
        if self.is_running(bot_id):
            raise RuntimeError(f"bot '{bot_id}' already has a running loop")
        self._tasks[bot_id] = asyncio.create_task(
            self._run_loop(bot_id), name=f"bot-loop-{bot_id}"
        )

    async def stop(self, bot_id: str) -> None:
        task = self._tasks.pop(bot_id, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def stop_all(self) -> None:
        for bot_id in list(self._tasks):
            await self.stop(bot_id)

    def _load_spec(self, bot_id: str) -> Optional[BotOut]:
        with self.session_factory() as db:
            row = db.get(BotRow, bot_id)
            return bot_to_spec(row) if row is not None else None

    def _mark_error(self, bot_id: str, reason: str) -> None:
        with self.session_factory() as db:
            row = db.get(BotRow, bot_id)
            if row is not None:
                row.status = BOT_STATUS_ERROR
                row.status_reason = reason
                db.commit()

    async def _run_loop(self, bot_id: str) -> None:
        consecutive_failures = 0
        try:
            while True:
                bot = self._load_spec(bot_id)
                if bot is None or bot.status != BOT_STATUS_RUNNING:
                    return  # deleted or stopped elsewhere

                try:
                    outcome = await run_cycle(bot, self.clients_factory())
                except Exception as exc:  # noqa: BLE001 - loop must survive
                    logger.exception("unexpected error in cycle for bot %s", bot_id)
                    outcome = CycleOutcome(
                        bot_id=bot_id,
                        started_at=_now(),
                        finished_at=_now(),
                        status=CYCLE_ERROR,
                        reason=f"unexpected: {exc}",
                    )
                    outcome.record_error("cycle", str(exc))

                try:
                    with self.session_factory() as db:
                        row = persist_outcome(db, outcome)
                        db.commit()
                        await publish_cycle_event(bot, row)
                except Exception:  # noqa: BLE001 - persistence must not kill the loop
                    logger.exception("could not persist cycle report for bot %s", bot_id)

                if outcome.status in (CYCLE_DEGRADED, CYCLE_ERROR):
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

                max_failures = config.max_consecutive_errors()
                if consecutive_failures >= max_failures:
                    reason = (
                        f"auto-stopped after {consecutive_failures} consecutive "
                        f"failed cycles (BOT_MAX_CONSECUTIVE_ERRORS={max_failures})"
                    )
                    self._mark_error(bot_id, reason)
                    logger.error(
                        "bot_auto_stopped %s",
                        json.dumps(
                            {
                                "event": "bot_auto_stopped",
                                "bot_id": bot_id,
                                "account_id": bot.account_id,
                                "consecutive_failures": consecutive_failures,
                                "max_allowed": max_failures,
                                "last_cycle_status": outcome.status,
                                "last_errors": outcome.errors[-3:],
                            }
                        ),
                    )
                    await events.publish_event(
                        "bot.stopped",
                        {"bot_id": bot_id, "reason": reason, "status": BOT_STATUS_ERROR},
                    )
                    return

                await asyncio.sleep(bot.cycle_interval_seconds)
        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(bot_id, None)


#: Process-wide runner used by the API endpoints.
runner = BotRunner()


def mark_orphaned_bots(db: Session) -> int:
    """Startup reconciliation: a fresh process has no loops, so bots left in
    'running' by a crash/restart are marked status=error (a human must
    explicitly restart them - auto-resuming trading, especially live, is not
    safe without review). Returns how many bots were marked."""
    rows = db.scalars(
        select(BotRow).where(BotRow.status == BOT_STATUS_RUNNING)
    ).all()
    for row in rows:
        row.status = BOT_STATUS_ERROR
        row.status_reason = "orphaned by service restart; manual restart required"
        logger.warning(
            "bot_orphaned %s",
            json.dumps({"event": "bot_orphaned", "bot_id": row.id, "name": row.name}),
        )
    return len(rows)
