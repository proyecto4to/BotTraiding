"""Core portfolio accounting: positions, cash, PnL, exposure, correlation,
drawdown. DB-backed (portfolio_accounts / portfolio_positions /
portfolio_executions) with an in-memory hot store for marks and injected
return series (returns/marks for symbols without an open position are
process-local; position marks are persisted on the position row).

Conventions
-----------
- quantity is signed: >0 long, <0 short.
- cash flow: buy -> cash -= qty*price + commission; sell -> cash += qty*price - commission.
- equity = cash + sum(qty * mark).
- margin_used = gross notional = sum(|qty| * mark) (Fase 7: leverage 1 margin model).
- current_drawdown = (peak_equity - equity) / peak_equity, peak tracked per account.
- floating_drawdown = max(0, -total_unrealized_pnl) / equity (1.0 if equity <= 0).
- pnl_daily/weekly/monthly = realized PnL summed from executions since the
  UTC day / ISO-week (Monday) / calendar-month boundary.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PortfolioAccount, PortfolioExecution, PortfolioPosition
from app.schemas import (
    DrawdownReport,
    ExecutionIngest,
    ExecutionIngestResult,
    ExposureReport,
    MarkRequest,
    PortfolioState,
)
from trading_contracts import AccountState, OrderSide, Position

DEFAULT_STARTING_CASH = float(os.environ.get("DEFAULT_STARTING_CASH", "100000"))

# In-memory hot state (process-local): marks and injected return series per
# account, including symbols without an open position row to persist onto.
_marks: dict[str, dict[str, float]] = {}
_returns: dict[str, dict[str, list[float]]] = {}

MAX_RETURN_POINTS = int(os.environ.get("MAX_RETURN_POINTS", "500"))


def reset_memory_state() -> None:
    """Test hook: clear process-local marks/returns."""
    _marks.clear()
    _returns.clear()


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_or_create_account(db: Session, account_id: str) -> PortfolioAccount:
    account = db.get(PortfolioAccount, account_id)
    if account is None:
        account = PortfolioAccount(
            account_id=account_id,
            cash=DEFAULT_STARTING_CASH,
            realized_pnl=0.0,
            peak_equity=DEFAULT_STARTING_CASH,
        )
        db.add(account)
        db.flush()
    return account


def _get_position(db: Session, account_id: str, symbol: str) -> PortfolioPosition | None:
    return db.execute(
        select(PortfolioPosition).where(
            PortfolioPosition.account_id == account_id,
            PortfolioPosition.symbol == symbol,
        )
    ).scalar_one_or_none()


def _open_positions(db: Session, account_id: str) -> list[PortfolioPosition]:
    rows = db.execute(
        select(PortfolioPosition).where(PortfolioPosition.account_id == account_id)
    ).scalars()
    return [p for p in rows if p.quantity != 0]


def _mark_for(account_id: str, position: PortfolioPosition) -> float:
    marks = _marks.get(account_id, {})
    if position.symbol in marks:
        return marks[position.symbol]
    if position.last_price is not None:
        return position.last_price
    return position.average_price


def _position_out(account_id: str, position: PortfolioPosition | None) -> Position | None:
    if position is None:
        return None
    return Position(
        symbol=position.symbol,
        quantity=position.quantity,
        average_price=position.average_price,
        unrealized_pnl=position.unrealized_pnl,
        account_id=account_id,
    )


def find_ingested(
    db: Session, account_id: str, client_order_id: str
) -> PortfolioExecution | None:
    return db.execute(
        select(PortfolioExecution).where(
            PortfolioExecution.account_id == account_id,
            PortfolioExecution.client_order_id == client_order_id,
        )
    ).scalars().first()


def apply_execution(
    db: Session, account_id: str, ingest: ExecutionIngest
) -> ExecutionIngestResult:
    """Ingest an ExecutionReport: update position, cash, realized PnL.

    Only fills (filled_quantity > 0 with a fill price) mutate state; other
    statuses are recorded to portfolio_executions for audit only.

    Idempotency guard: when the report carries a client_order_id that was
    already ingested for this account, nothing is mutated (duplicate=True) —
    an execution-engine retry or an event replay can never double-count.
    """
    account = get_or_create_account(db, account_id)

    if ingest.client_order_id:
        existing = find_ingested(db, account_id, ingest.client_order_id)
        if existing is not None:
            position = _get_position(db, account_id, ingest.symbol)
            return ExecutionIngestResult(
                account_id=account_id,
                symbol=ingest.symbol,
                applied=False,
                duplicate=True,
                realized_pnl_delta=0.0,
                position=_position_out(account_id, position),
                cash=account.cash,
            )

    fill_qty = ingest.filled_quantity or 0.0
    price = ingest.average_fill_price
    applies = fill_qty > 0 and price is not None

    realized_delta = 0.0
    position = _get_position(db, account_id, ingest.symbol)

    if applies:
        signed_delta = fill_qty if ingest.side == OrderSide.BUY else -fill_qty

        if position is None:
            position = PortfolioPosition(
                account_id=account_id,
                symbol=ingest.symbol,
                quantity=0.0,
                average_price=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                sector=ingest.sector,
                currency=ingest.currency,
            )
            db.add(position)

        old_qty = position.quantity
        new_qty = old_qty + signed_delta

        if old_qty == 0 or (old_qty > 0) == (signed_delta > 0):
            # Opening or adding to a position in the same direction.
            total_cost = position.average_price * abs(old_qty) + price * abs(signed_delta)
            position.average_price = total_cost / abs(new_qty)
        else:
            # Reducing / closing / flipping.
            closed_qty = min(abs(signed_delta), abs(old_qty))
            direction = 1.0 if old_qty > 0 else -1.0
            realized_delta = closed_qty * (price - position.average_price) * direction
            if abs(signed_delta) > abs(old_qty):
                # Flip: remainder opens at the fill price.
                position.average_price = price
            elif new_qty == 0:
                position.average_price = 0.0
            # Partial reduce keeps the old average price.

        position.quantity = new_qty
        position.last_price = price
        if ingest.sector is not None:
            position.sector = ingest.sector
        position.currency = ingest.currency
        mark = price
        position.unrealized_pnl = position.quantity * (mark - position.average_price)
        position.realized_pnl += realized_delta

        # Cash flow (signed): buys consume cash, sells add cash.
        account.cash -= signed_delta * price
        account.cash -= ingest.commission
        account.realized_pnl += realized_delta

        _marks.setdefault(account_id, {})[ingest.symbol] = price

    db.add(
        PortfolioExecution(
            account_id=account_id,
            order_id=str(ingest.order_id),
            client_order_id=ingest.client_order_id,
            source="trading",
            symbol=ingest.symbol,
            side=ingest.side.value,
            status=ingest.status.value,
            filled_quantity=fill_qty,
            average_fill_price=price,
            commission=ingest.commission if applies else 0.0,
            realized_pnl=realized_delta,
            raw=ingest.raw,
            reported_at=_utc_naive(ingest.reported_at),
        )
    )

    _update_peak_equity(db, account)
    db.commit()

    return ExecutionIngestResult(
        account_id=account_id,
        symbol=ingest.symbol,
        applied=applies,
        realized_pnl_delta=realized_delta,
        position=_position_out(account_id, position),
        cash=account.cash,
    )


def apply_mark(db: Session, account_id: str, mark: MarkRequest) -> PortfolioState:
    """Update marks (and optionally injected return series), recompute
    unrealized PnL, floating drawdown and peak equity."""
    account = get_or_create_account(db, account_id)

    account_marks = _marks.setdefault(account_id, {})
    account_marks.update(mark.prices)

    if mark.returns:
        account_returns = _returns.setdefault(account_id, {})
        for symbol, series in mark.returns.items():
            account_returns[symbol] = list(series)[-MAX_RETURN_POINTS:]

    for position in _open_positions(db, account_id):
        px = account_marks.get(position.symbol)
        if px is not None:
            position.last_price = px
            position.unrealized_pnl = position.quantity * (px - position.average_price)

    _update_peak_equity(db, account)
    db.commit()
    return build_state(db, account_id)


def _equity(db: Session, account: PortfolioAccount) -> float:
    positions = _open_positions(db, account.account_id)
    market_value = sum(p.quantity * _mark_for(account.account_id, p) for p in positions)
    return account.cash + market_value


def _update_peak_equity(db: Session, account: PortfolioAccount) -> None:
    equity = _equity(db, account)
    if equity > account.peak_equity:
        account.peak_equity = equity


def _period_realized(db: Session, account_id: str, since: datetime) -> float:
    rows = db.execute(
        select(PortfolioExecution.realized_pnl).where(
            PortfolioExecution.account_id == account_id,
            PortfolioExecution.reported_at >= since,
        )
    ).scalars()
    return float(sum(rows))


def _period_boundaries(now: datetime) -> tuple[datetime, datetime, datetime]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)
    return day_start, week_start, month_start


def compute_correlation_matrix(
    returns: dict[str, list[float]], symbols: list[str]
) -> dict[str, dict[str, float]]:
    """Pairwise Pearson correlation over the trailing overlap of each pair
    of injected return series, restricted to `symbols`."""
    usable = {s: returns[s] for s in symbols if len(returns.get(s, [])) >= 2}
    keys = sorted(usable)
    matrix: dict[str, dict[str, float]] = {}
    for a in keys:
        matrix[a] = {}
        for b in keys:
            if a == b:
                matrix[a][b] = 1.0
                continue
            n = min(len(usable[a]), len(usable[b]))
            sa = np.asarray(usable[a][-n:], dtype=float)
            sb = np.asarray(usable[b][-n:], dtype=float)
            if n < 2 or float(np.std(sa)) == 0.0 or float(np.std(sb)) == 0.0:
                matrix[a][b] = 0.0
                continue
            matrix[a][b] = round(float(np.corrcoef(sa, sb)[0, 1]), 6)
    return matrix


def build_exposure(db: Session, account_id: str) -> ExposureReport:
    account = get_or_create_account(db, account_id)
    positions = _open_positions(db, account_id)

    per_symbol: dict[str, float] = {}
    per_sector: dict[str, float] = {}
    per_currency: dict[str, float] = {}
    gross = 0.0
    net = 0.0
    for p in positions:
        notional = p.quantity * _mark_for(account_id, p)
        per_symbol[p.symbol] = per_symbol.get(p.symbol, 0.0) + abs(notional)
        sector = p.sector or "unknown"
        per_sector[sector] = per_sector.get(sector, 0.0) + abs(notional)
        per_currency[p.currency] = per_currency.get(p.currency, 0.0) + abs(notional)
        gross += abs(notional)
        net += notional

    equity = _equity(db, account)
    correlation = compute_correlation_matrix(
        _returns.get(account_id, {}), [p.symbol for p in positions]
    )
    return ExposureReport(
        account_id=account_id,
        gross_exposure=gross,
        net_exposure=net,
        leverage=(gross / equity) if equity > 0 else 0.0,
        per_symbol=per_symbol,
        per_sector=per_sector,
        per_currency=per_currency,
        correlation_matrix=correlation,
    )


def build_drawdown(db: Session, account_id: str) -> DrawdownReport:
    account = get_or_create_account(db, account_id)
    equity = _equity(db, account)
    peak = max(account.peak_equity, equity)
    current_dd = ((peak - equity) / peak) if peak > 0 else 0.0

    positions = _open_positions(db, account_id)
    unrealized = sum(
        p.quantity * (_mark_for(account_id, p) - p.average_price) for p in positions
    )
    if equity <= 0:
        floating_dd = 1.0
    else:
        floating_dd = max(0.0, -unrealized) / equity
    return DrawdownReport(
        account_id=account_id,
        equity=equity,
        peak_equity=peak,
        current_drawdown=current_dd,
        floating_drawdown=floating_dd,
    )


def build_state(db: Session, account_id: str) -> PortfolioState:
    account = get_or_create_account(db, account_id)
    positions = _open_positions(db, account_id)

    unrealized = 0.0
    contract_positions: list[Position] = []
    marks_out: dict[str, float] = dict(_marks.get(account_id, {}))
    for p in positions:
        mark = _mark_for(account_id, p)
        upnl = p.quantity * (mark - p.average_price)
        unrealized += upnl
        marks_out.setdefault(p.symbol, mark)
        contract_positions.append(
            Position(
                symbol=p.symbol,
                quantity=p.quantity,
                average_price=p.average_price,
                unrealized_pnl=upnl,
                account_id=account_id,
            )
        )

    equity = _equity(db, account)
    exposure = build_exposure(db, account_id)
    drawdown = build_drawdown(db, account_id)

    now = _now()
    day_start, week_start, month_start = _period_boundaries(now)

    return PortfolioState(
        account=AccountState(
            account_id=account_id,
            balance=account.cash,
            equity=equity,
            margin_used=exposure.gross_exposure,
            free_margin=equity - exposure.gross_exposure,
            currency=account.base_currency,
        ),
        positions=contract_positions,
        marks=marks_out,
        returns=dict(_returns.get(account_id, {})),
        exposure=exposure,
        drawdown=drawdown,
        realized_pnl=account.realized_pnl,
        unrealized_pnl=unrealized,
        pnl_daily=_period_realized(db, account_id, day_start),
        pnl_weekly=_period_realized(db, account_id, week_start),
        pnl_monthly=_period_realized(db, account_id, month_start),
        updated_at=now,
    )
