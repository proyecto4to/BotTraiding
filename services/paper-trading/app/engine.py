"""Simulated broker fill engine (Fase 9).

Realistic fill modeling against the caller-supplied market (mid) price:

    total_adjustment_bps = spread_bps / 2
                         + slippage_bps
                         + size_impact_bps_per_unit * requested_quantity

    buy  fill price = mid * (1 + total_adjustment_bps / 10_000)
    sell fill price = mid * (1 - total_adjustment_bps / 10_000)

    commission = notional * commission_bps / 10_000
               + commission_per_unit * filled_quantity

Partial fills: quantities above ``max_fill_quantity`` (when > 0) fill only
up to the cap and the order stays PARTIALLY_FILLED (cancellable).
Latency: an ``asyncio.sleep`` of ``latency_ms`` before the fill.
Rejects: buys that cost more cash than the account holds are REJECTED with
reason "insufficient_balance"; with allow_short=false, sells beyond the
held quantity are REJECTED with reason "insufficient_position".
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_contracts import ExecutionReport, OrderSide, OrderStatus

from .config import FillConfig
from .models import PaperAccountRow, PaperOrderRow, PaperPositionRow
from .schemas import PaperOrderRequest

BROKER_NAME = "paper"

# Module-level seam so tests can observe/replace the latency sleep.
_sleep = asyncio.sleep


class DuplicateOrderError(Exception):
    """The order id was already processed (idempotency guard)."""


def get_or_create_account(
    db: Session, account_id: str, config: FillConfig
) -> PaperAccountRow:
    account = db.get(PaperAccountRow, account_id)
    if account is None:
        account = PaperAccountRow(
            id=account_id,
            starting_cash=config.default_starting_cash,
            cash=config.default_starting_cash,
        )
        db.add(account)
        db.flush()
    return account


def positions_for(db: Session, account_id: str) -> list[PaperPositionRow]:
    rows = db.execute(
        select(PaperPositionRow).where(PaperPositionRow.account_id == account_id)
    ).scalars()
    return [row for row in rows if row.quantity != 0]


def reset_account(db: Session, account: PaperAccountRow) -> None:
    """Back to starting cash; drop all simulated positions and orders."""
    account.cash = account.starting_cash
    for row in db.execute(
        select(PaperPositionRow).where(PaperPositionRow.account_id == account.id)
    ).scalars():
        db.delete(row)
    for row in db.execute(
        select(PaperOrderRow).where(PaperOrderRow.account_id == account.id)
    ).scalars():
        db.delete(row)
    db.flush()


def _get_position(db: Session, account_id: str, symbol: str) -> PaperPositionRow:
    row = db.execute(
        select(PaperPositionRow).where(
            PaperPositionRow.account_id == account_id,
            PaperPositionRow.symbol == symbol,
        )
    ).scalar_one_or_none()
    if row is None:
        row = PaperPositionRow(account_id=account_id, symbol=symbol)
        db.add(row)
        db.flush()
    return row


def _apply_fill_to_position(
    position: PaperPositionRow, side: OrderSide, quantity: float, price: float
) -> None:
    signed = quantity if side == OrderSide.BUY else -quantity
    if position.quantity == 0:
        position.average_price = price
        position.quantity = signed
    elif (position.quantity > 0) == (signed > 0):
        # Extending the position in the same direction: weighted average.
        total = abs(position.quantity) + quantity
        position.average_price = (
            abs(position.quantity) * position.average_price + quantity * price
        ) / total
        position.quantity += signed
    else:
        new_quantity = position.quantity + signed
        if new_quantity == 0:
            position.average_price = 0.0
        elif (new_quantity > 0) != (position.quantity > 0):
            # Crossed through flat: the residual position opened at this fill.
            position.average_price = price
        position.quantity = new_quantity


def _reject(
    db: Session,
    request: PaperOrderRequest,
    reason: str,
    raw_base: dict,
) -> ExecutionReport:
    now = datetime.now(timezone.utc)
    raw = dict(raw_base, reason=reason)
    db.add(
        PaperOrderRow(
            id=str(request.order_id),
            account_id=request.account_id,
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            filled_quantity=0.0,
            average_fill_price=None,
            reference_price=request.price,
            commission=0.0,
            status=OrderStatus.REJECTED.value,
            raw=raw,
        )
    )
    db.flush()
    return ExecutionReport(
        order_id=request.order_id,
        status=OrderStatus.REJECTED,
        filled_quantity=0.0,
        average_fill_price=None,
        broker=BROKER_NAME,
        reported_at=now,
        raw=raw,
    )


async def execute_order(
    db: Session, request: PaperOrderRequest, config: FillConfig
) -> ExecutionReport:
    if db.get(PaperOrderRow, str(request.order_id)) is not None:
        raise DuplicateOrderError(str(request.order_id))

    account = get_or_create_account(db, request.account_id, config)

    if config.latency_ms > 0:
        await _sleep(config.latency_ms / 1000.0)

    size_impact_bps = config.size_impact_bps_per_unit * request.quantity
    total_adjustment_bps = config.spread_bps / 2.0 + config.slippage_bps + size_impact_bps
    direction = 1.0 if request.side == OrderSide.BUY else -1.0
    fill_price = request.price * (1.0 + direction * total_adjustment_bps / 10_000.0)

    fill_quantity = request.quantity
    if config.max_fill_quantity > 0:
        fill_quantity = min(fill_quantity, config.max_fill_quantity)

    notional = fill_price * fill_quantity
    commission = (
        notional * config.commission_bps / 10_000.0
        + config.commission_per_unit * fill_quantity
    )

    raw_base = {
        "account_id": request.account_id,
        "symbol": request.symbol,
        "side": request.side.value,
        "mid_price": request.price,
        "requested_quantity": request.quantity,
        "spread_bps": config.spread_bps,
        "slippage_bps": config.slippage_bps,
        "size_impact_bps": size_impact_bps,
        "total_adjustment_bps": total_adjustment_bps,
        "latency_ms": config.latency_ms,
    }

    # Reject scenarios.
    if request.side == OrderSide.BUY and notional + commission > account.cash:
        return _reject(db, request, "insufficient_balance", raw_base)
    if request.side == OrderSide.SELL and not config.allow_short:
        position = _get_position(db, request.account_id, request.symbol)
        if position.quantity < fill_quantity:
            return _reject(db, request, "insufficient_position", raw_base)

    # Apply cash and position effects.
    if request.side == OrderSide.BUY:
        account.cash -= notional + commission
    else:
        account.cash += notional - commission
    position = _get_position(db, request.account_id, request.symbol)
    _apply_fill_to_position(position, request.side, fill_quantity, fill_price)

    status = (
        OrderStatus.FILLED
        if fill_quantity == request.quantity
        else OrderStatus.PARTIALLY_FILLED
    )
    raw = dict(raw_base, commission=commission)

    db.add(
        PaperOrderRow(
            id=str(request.order_id),
            account_id=request.account_id,
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.order_type.value,
            quantity=request.quantity,
            filled_quantity=fill_quantity,
            average_fill_price=fill_price,
            reference_price=request.price,
            commission=commission,
            status=status.value,
            raw=raw,
        )
    )
    db.flush()

    return ExecutionReport(
        order_id=request.order_id,
        status=status,
        filled_quantity=fill_quantity,
        average_fill_price=fill_price,
        broker=BROKER_NAME,
        reported_at=datetime.now(timezone.utc),
        raw=raw,
    )
