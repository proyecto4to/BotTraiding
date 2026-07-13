"""The /risk/validate pipeline: TradeSignal + portfolio state -> RiskDecision.

Order (docs/ARCHITECTURE.md section 4, "toda orden pasa por el Risk Engine"):
1. load per-account limits (defaults when unset);
2. resolve portfolio state (inline for tests, else portfolio-engine fetch;
   an unreachable portfolio-engine REJECTS fail-safe and counts a breaker error);
3. evaluate the circuit breaker (may escalate NORMAL->SOFT->HARD);
4. HARD_HALT rejects everything with positions_should_close=True;
   SOFT_HALT rejects anything that increases exposure;
5. run every risk check (no short-circuit -> complete pass/fail report);
6. position sizing + stop plan (max_size_allowed / adjusted_stop);
7. approved only if all checks passed; every rejection/halt is persisted to
   risk_events and published via the events seam.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import circuit_breaker as cb
from app import events, limits as limits_repo, sizing
from app.checks import ALL_CHECKS
from app.context import ValidationContext, build_context
from app.portfolio_client import PortfolioClient, PortfolioUnavailableError
from app.schemas import (
    PortfolioStateIn,
    RiskDecisionResponse,
    SizingInfo,
    ValidateRequest,
)
from trading_contracts import TradeSignal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_decision(signal: TradeSignal, account_id: str) -> RiskDecisionResponse:
    return RiskDecisionResponse(
        signal_id=signal.id,
        approved=False,
        reason="",
        decided_at=_now(),
        account_id=account_id,
        max_size_allowed=0.0,
    )


async def _record_rejection(
    db: Session, decision: RiskDecisionResponse, event_type: str = "risk.rejected"
) -> None:
    payload = decision.model_dump(mode="json")
    events.persist_event(
        db,
        decision.account_id,
        event_type,
        payload,
        signal_id=str(decision.signal_id),
    )
    await events.publish_event(event_type, payload)


def _compute_sizing(ctx: ValidationContext) -> SizingInfo:
    equity = ctx.equity
    lim = ctx.limits
    state = ctx.state
    sector_before = state.exposure.per_sector.get(ctx.sector, 0.0)

    result = sizing.compute_position_size(
        equity,
        lim.max_risk_per_trade,
        ctx.entry_price,
        ctx.stop_price,
        symbol_room=lim.max_exposure_per_symbol * equity - ctx.symbol_exposure_before,
        sector_room=lim.max_exposure_per_sector * equity - sector_before,
        leverage_room=lim.max_leverage * equity - state.exposure.gross_exposure,
        total_room=lim.max_total_exposure * equity - state.exposure.gross_exposure,
        margin_room=state.account.free_margin,
    )
    return SizingInfo(
        size_by_risk=result.size_by_risk,
        max_size_allowed=result.max_size_allowed,
        risk_amount=result.risk_amount,
        stop_distance=result.stop_distance,
        caps=result.caps,
        binding_constraint=result.binding_constraint,
    )


async def validate_signal(
    db: Session, request: ValidateRequest, client: PortfolioClient
) -> RiskDecisionResponse:
    signal = request.signal
    account_id = request.account_id
    limits, _ = limits_repo.load_limits(db, account_id)

    # Per-caller risk allocation (P7): an autonomy bot passes its allocated
    # risk-per-trade share. It can only *reduce* the account cap, never raise it.
    if request.risk_per_trade_override is not None:
        limits = limits.model_copy(
            update={
                "max_risk_per_trade": min(
                    request.risk_per_trade_override, limits.max_risk_per_trade
                )
            }
        )

    decision = _base_decision(signal, account_id)

    # --- portfolio state (inline bypasses the fetch) ----------------------
    state: PortfolioStateIn
    if request.portfolio_state is not None:
        state = request.portfolio_state
    else:
        try:
            state = await client.get_state(account_id)
        except PortfolioUnavailableError as exc:
            cb.record_error(db, account_id)
            row = cb.get_breaker(db, account_id)
            decision.reason = f"portfolio_state_unavailable: {exc}"
            decision.risk_checks_failed = ["portfolio_state"]
            decision.circuit_breaker_state = row.state
            await _record_rejection(db, decision)
            db.commit()
            return decision

    # --- circuit breaker ---------------------------------------------------
    equity = state.account.equity
    metrics = cb.BreakerMetrics(
        daily_loss_fraction=(max(0.0, -state.pnl_daily) / equity) if equity > 0 else 1.0,
        drawdown=state.drawdown.current_drawdown,
        error_count=cb.current_error_count(cb.get_breaker(db, account_id)),
    )
    row, escalated = cb.evaluate(db, account_id, limits, metrics)
    if escalated:
        payload = {
            "account_id": account_id,
            "state": row.state,
            "reason": row.reason,
        }
        events.persist_event(db, account_id, "risk.circuit_breaker", payload)
        await events.publish_event("risk.circuit_breaker", payload)

    decision.circuit_breaker_state = row.state
    ctx = build_context(signal, limits, state, account_id)
    decision.adjusted_stop = ctx.stop_plan.adjusted_stop
    decision.stop_plan = ctx.stop_plan

    if row.state == cb.BreakerState.HARD_HALT.value:
        decision.reason = f"circuit_breaker_hard_halt: {row.reason or 'halted'}"
        decision.risk_checks_failed = ["circuit_breaker"]
        decision.positions_should_close = True
        await _record_rejection(db, decision)
        db.commit()
        return decision

    if row.state == cb.BreakerState.SOFT_HALT.value and ctx.increases_exposure:
        decision.reason = f"circuit_breaker_soft_halt: {row.reason or 'no new positions'}"
        decision.risk_checks_failed = ["circuit_breaker"]
        await _record_rejection(db, decision)
        db.commit()
        return decision

    # --- checks --------------------------------------------------------------
    results = [check.run(ctx) for check in ALL_CHECKS]
    decision.risk_checks_passed = [r.name for r in results if r.passed]
    decision.risk_checks_failed = [r.name for r in results if not r.passed]

    # --- sizing ----------------------------------------------------------------
    sizing_info = _compute_sizing(ctx)
    decision.sizing = sizing_info
    decision.max_size_allowed = sizing_info.max_size_allowed

    if decision.risk_checks_failed:
        failures = [f"{r.name}:{r.reason}" for r in results if not r.passed]
        decision.approved = False
        decision.reason = "; ".join(failures)
        await _record_rejection(db, decision)
    else:
        decision.approved = True
        decision.reason = "approved"

    await events.publish_event("risk.decision", decision.model_dump(mode="json"))
    db.commit()
    return decision
