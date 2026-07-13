"""The tick: turn AI regime + strategy selection into paper-bot actions.

One cycle:
  1. skip if the state machine is OFF/HALTED;
  2. per symbol: fetch bars (market-data) -> regime (ai) -> ranked strategies (ai);
  3. take the top strategies, capped by the risk budget (max active bots);
  4. reconcile trading-engine's autonomy-owned bots to that selection
     (create+start the desired, stop the no-longer-desired) — the controller
     only ever touches bots it created (BOT_NAME_PREFIX);
  5. promote LEARNING -> TRADING_PAPER on the first usable selection;
  6. persist an explainable decision record.

Every downstream call is isolated: one failure is recorded and the cycle keeps
going. trading-engine + risk-engine still enforce risk on every resulting order
— the controller never bypasses them (it only creates paper bots by default).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, statemachine
from .clients import Clients, DownstreamError
from .models import AutonomyDecisionRow
from .schemas import TickResult

logger = logging.getLogger("autonomy-controller.controller")


def _bot_name(symbol: str, strategy_key: str) -> str:
    return f"{config.BOT_NAME_PREFIX}{symbol}:{strategy_key}"


async def _build_selection(clients: Clients, errors: list) -> tuple[list, dict]:
    """Per-symbol regime + ranked strategies -> capped selection list."""
    selection: list[dict] = []
    regime_summary: dict[str, dict] = {}
    tf, mkt, limit, top_n = (
        config.timeframe(), config.market(), config.bar_limit(), config.top_n_per_symbol()
    )

    for symbol in config.symbols():
        try:
            bars = await clients.market_data.get_bars(symbol, tf, limit)
            if len(bars) < 2:
                errors.append({"symbol": symbol, "error": "insufficient bars"})
                continue
            regime = await clients.ai.regime(bars)
            ranked = await clients.ai.select(regime, mkt, tf, performance=[])
        except DownstreamError as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
            continue

        regime_summary[symbol] = {
            "trend": regime.get("trend"),
            "volatility": regime.get("volatility"),
            "confidence": regime.get("confidence"),
        }
        for score in ranked[:top_n]:
            selection.append(
                {
                    "symbol": symbol,
                    "strategy_key": score.get("key"),
                    "weight": score.get("weight", 0.0),
                    "category": score.get("category"),
                }
            )

    selection.sort(key=lambda s: s.get("weight", 0.0), reverse=True)
    return selection[: config.max_active_bots()], regime_summary


async def _reconcile(clients: Clients, selection: list, errors: list) -> list:
    """Align autonomy-owned bots to the selection."""
    actions: list[dict] = []
    try:
        current = await clients.trading.list_bots(config.account_id())
    except DownstreamError as exc:
        errors.append({"stage": "list_bots", "error": str(exc)})
        return actions

    auto_bots = {
        b["name"]: b for b in current if str(b.get("name", "")).startswith(config.BOT_NAME_PREFIX)
    }
    desired = {_bot_name(s["symbol"], s["strategy_key"]): s for s in selection}

    # Create/start desired bots.
    for name, sel in desired.items():
        try:
            existing = auto_bots.get(name)
            if existing is None:
                created = await clients.trading.create_bot(
                    {
                        "name": name,
                        "account_id": config.account_id(),
                        "broker": config.broker(),
                        "execution_mode": "paper",
                        "symbols": [sel["symbol"]],
                        "timeframe": config.timeframe(),
                        "strategy_keys": [sel["strategy_key"]],
                        "params_overrides": {},
                        "cycle_interval_seconds": config.bot_cycle_interval(),
                    }
                )
                await clients.trading.start_bot(created["id"])
                actions.append({"action": "create+start", "bot": name})
            elif existing.get("status") != "running":
                await clients.trading.start_bot(existing["id"])
                actions.append({"action": "start", "bot": name})
        except DownstreamError as exc:
            errors.append({"bot": name, "error": str(exc)})

    # Stop bots no longer selected.
    for name, bot in auto_bots.items():
        if name in desired:
            continue
        if bot.get("status") == "running":
            try:
                await clients.trading.stop_bot(bot["id"])
                actions.append({"action": "stop", "bot": name})
            except DownstreamError as exc:
                errors.append({"bot": name, "error": str(exc)})

    return actions


def _persist(db: Session, *, state: str, summary: str, regime: dict,
             selection: list, actions: list, errors: list) -> AutonomyDecisionRow:
    row = AutonomyDecisionRow(
        state=state, summary=summary, regime=regime,
        selection=selection, actions=actions, errors=errors,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def run_cycle(db: Session, clients: Clients) -> TickResult:
    state_row = statemachine.get_state(db)
    state = state_row.state

    if state not in statemachine.ACTIVE_STATES:
        summary = f"skipped: state={state}"
        _persist(db, state=state, summary=summary, regime={}, selection=[], actions=[], errors=[])
        return TickResult(state=state, acted=False, summary=summary)

    errors: list[dict] = []
    selection, regime_summary = await _build_selection(clients, errors)
    actions = await _reconcile(clients, selection, errors)

    # First usable selection promotes LEARNING -> TRADING_PAPER.
    if state == statemachine.LEARNING and selection:
        state_row = statemachine.promote_to_paper(db, actor="autonomy")
        state = state_row.state

    summary = (
        f"{len(selection)} strategies selected, {len(actions)} action(s), "
        f"{len(errors)} error(s)"
    )
    _persist(
        db, state=state, summary=summary, regime=regime_summary,
        selection=selection, actions=actions, errors=errors,
    )
    logger.info("autonomy cycle: %s", summary)
    return TickResult(
        state=state, acted=bool(actions), summary=summary,
        selection=selection, actions=actions, errors=errors,
    )


def recent_decisions(db: Session, limit: int) -> list[AutonomyDecisionRow]:
    return list(
        db.scalars(
            select(AutonomyDecisionRow)
            .order_by(AutonomyDecisionRow.created_at.desc(), AutonomyDecisionRow.id.desc())
            .limit(limit)
        )
    )
