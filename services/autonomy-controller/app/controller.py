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
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import allocation, config, events, gates, governor, statemachine
from .clients import Clients, DownstreamError
from .models import AutonomyDecisionRow
from .schemas import TickResult

logger = logging.getLogger("autonomy-controller.controller")


def _bot_name(symbol: str, strategy_key: str) -> str:
    return f"{config.BOT_NAME_PREFIX}{symbol}:{strategy_key}"


def paper_trading_days(db: Session) -> float:
    """Days since the automation first entered TRADING_PAPER (from the decision
    log). 0 if it never has."""
    first = db.execute(
        select(AutonomyDecisionRow.created_at)
        .where(AutonomyDecisionRow.state == statemachine.TRADING_PAPER)
        .order_by(AutonomyDecisionRow.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if first is None:
        return 0.0
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return max(0.0, (now - first).total_seconds() / 86400.0)


async def build_readiness(db: Session, clients: Clients) -> gates.GateReport:
    """Assemble the paper track record and evaluate the promotion gates (P18).

    A portfolio-engine outage is a hard block: we never promote to live without
    being able to read the account's real drawdown/return."""
    try:
        state = await clients.portfolio.get_state(config.account_id())
    except DownstreamError as exc:
        return gates.GateReport(
            ready=False,
            gates=[gates.GateResult("portfolio_available", False, str(exc))],
        )

    equity = float((state.get("account") or {}).get("equity", 0.0) or 0.0)
    realized = float(state.get("realized_pnl", 0.0) or 0.0)
    unrealized = float(state.get("unrealized_pnl", 0.0) or 0.0)
    starting = equity - realized - unrealized
    total_return = ((realized + unrealized) / starting) if starting > 0 else 0.0

    # The WORST drawdown of the paper period, not today's: a strategy that fell
    # 40% and recovered must not present itself as unblemished.
    drawdown_report = state.get("drawdown") or {}
    worst_drawdown = float(
        drawdown_report.get("max_drawdown", drawdown_report.get("current_drawdown", 0.0)) or 0.0
    )

    sharpe = state.get("trade_sharpe")

    snap = gates.PromotionSnapshot(
        paper_days=paper_trading_days(db),
        drawdown=worst_drawdown,
        total_return=total_return,
        closed_trades=int(state.get("closed_trades", 0) or 0),
        sharpe=float(sharpe) if sharpe is not None else None,
        paper_return=total_return,
        # backtest_return stays unset: no baseline is wired yet, which is why
        # the coherence gate is off by default (see config.backtest_coherence_tolerance).
    )
    return gates.evaluate_gates(snap)


def _execution_mode(state: str) -> str:
    return "live" if state == statemachine.TRADING_LIVE else "paper"


async def stop_all_autonomy_bots(clients: Clients) -> list[dict]:
    """Stop every running autonomy-owned bot (used on disable/halt)."""
    actions: list[dict] = []
    try:
        bots = await clients.trading.list_bots(config.account_id())
    except DownstreamError as exc:
        logger.warning("could not list bots to stop: %s", exc)
        return actions
    for bot in bots:
        is_auto = str(bot.get("name", "")).startswith(config.BOT_NAME_PREFIX)
        if is_auto and bot.get("status") == "running":
            try:
                await clients.trading.stop_bot(bot["id"])
                actions.append({"action": "stop", "bot": bot["name"]})
            except DownstreamError as exc:
                logger.warning("could not stop bot %s: %s", bot.get("name"), exc)
    return actions


async def check_risk_guard(
    clients: Clients, errors: list, *, state_name: str = statemachine.TRADING_PAPER
) -> list[str]:
    """Platform-level circuit breaker (P9): returns a list of breached limits.

    Reads aggregate drawdown and daily PnL from portfolio-engine.

    On a portfolio outage the behaviour depends on what is at stake. In paper it
    is fail-open (recorded, not a halt): per-order risk checks in risk-engine
    still protect each trade and nothing real is lost. In TRADING_LIVE it is
    fail-closed — real money must never keep trading while the one component
    that can see aggregate drawdown is unreachable. That matches how the rest of
    the platform behaves: risk-engine rejects on an unreachable portfolio, and
    build_readiness refuses to promote."""
    max_dd = config.max_drawdown()
    max_dl = config.max_daily_loss_fraction()
    if max_dd <= 0 and max_dl <= 0:
        return []  # guard disabled
    try:
        state = await clients.portfolio.get_state(config.account_id())
    except DownstreamError as exc:
        errors.append({"stage": "risk_guard", "error": str(exc)})
        if state_name == statemachine.TRADING_LIVE:
            return [f"portfolio-engine unreachable while trading live: {exc}"]
        return []

    drawdown = float((state.get("drawdown") or {}).get("current_drawdown", 0.0) or 0.0)
    equity = float((state.get("account") or {}).get("equity", 0.0) or 0.0)
    pnl_daily = float(state.get("pnl_daily", 0.0) or 0.0)

    breaches: list[str] = []
    if max_dd > 0 and drawdown >= max_dd:
        breaches.append(f"drawdown {drawdown:.2%} >= limit {max_dd:.2%}")
    if max_dl > 0 and equity > 0 and pnl_daily < 0 and (-pnl_daily / equity) >= max_dl:
        breaches.append(f"daily loss {(-pnl_daily / equity):.2%} >= limit {max_dl:.2%}")
    return breaches


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


async def _reconcile(
    clients: Clients, selection: list, errors: list, execution_mode: str = "paper"
) -> list:
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

    # Create/start/rebalance desired bots.
    for name, sel in desired.items():
        alloc = allocation.allocation_of(sel)
        try:
            existing = auto_bots.get(name)
            if existing is None:
                created = await clients.trading.create_bot(
                    {
                        "name": name,
                        "account_id": config.account_id(),
                        "broker": config.broker(),
                        "execution_mode": execution_mode,
                        "symbols": [sel["symbol"]],
                        "timeframe": config.timeframe(),
                        "strategy_keys": [sel["strategy_key"]],
                        "params_overrides": {},
                        "risk_allocation": alloc,
                        "cycle_interval_seconds": config.bot_cycle_interval(),
                    }
                )
                await clients.trading.start_bot(created["id"])
                actions.append({"action": "create+start", "bot": name, "allocation": alloc})
            elif allocation.allocation_changed(existing.get("risk_allocation"), alloc):
                # Weight shift: rebalance capital (config changes need the bot
                # stopped first, then restart).
                await clients.trading.stop_bot(existing["id"])
                await clients.trading.update_bot(existing["id"], {"risk_allocation": alloc})
                await clients.trading.start_bot(existing["id"])
                actions.append({"action": "rebalance", "bot": name, "allocation": alloc})
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

    # Global risk guard (P9): a real breach halts the whole automation before
    # any new bot action, stops running bots and requires an admin reset.
    breaches = await check_risk_guard(clients, errors, state_name=state)
    if breaches:
        reason = "auto-halt: " + "; ".join(breaches)
        statemachine.halt(db, reason=reason, actor="risk-guard")
        actions = await stop_all_autonomy_bots(clients)
        await events.publish_event(
            "autonomy.halted",
            {"reason": reason, "severity": "critical", "actor": "risk-guard"},
        )
        _persist(
            db, state=statemachine.HALTED, summary=reason, regime={},
            selection=[], actions=actions, errors=errors,
        )
        logger.error("AUTONOMY AUTO-HALT: %s", reason)
        return TickResult(
            state=statemachine.HALTED, acted=bool(actions), summary=reason,
            actions=actions, errors=errors,
        )

    selection, regime_summary = await _build_selection(clients, errors)
    # Capital allocation (P7): enrich each pick with its share of the budget.
    selection = allocation.build_allocation_plan(selection)
    actions = await _reconcile(clients, selection, errors, _execution_mode(state))

    # Strategy lifecycle governor (P5): act on the AI's validated advice
    # (disable underperformers, re-enable regime-favored strategies).
    governor_actions = await governor.run_governor(db, clients, selection, errors)

    # First usable selection promotes LEARNING -> TRADING_PAPER.
    if state == statemachine.LEARNING and selection:
        state_row = statemachine.promote_to_paper(db, actor="autonomy")
        state = state_row.state

    summary = (
        f"{len(selection)} strategies selected, {len(actions)} action(s), "
        f"{len(governor_actions)} governor action(s), {len(errors)} error(s)"
    )
    _persist(
        db, state=state, summary=summary, regime=regime_summary,
        selection=selection, actions=actions, errors=errors,
    )
    logger.info("autonomy cycle: %s", summary)
    return TickResult(
        state=state, acted=bool(actions or governor_actions), summary=summary,
        selection=selection, actions=actions, governor=governor_actions,
        errors=errors,
    )


def recent_decisions(db: Session, limit: int) -> list[AutonomyDecisionRow]:
    return list(
        db.scalars(
            select(AutonomyDecisionRow)
            .order_by(AutonomyDecisionRow.created_at.desc(), AutonomyDecisionRow.id.desc())
            .limit(limit)
        )
    )
