"""Core execution pipeline (Fases 9/10): one code path for paper and live.

submit -> split into child orders -> for each child, place on the mode's
transport with retry/backoff -> persist every ExecutionReport -> forward
fills to portfolio-engine -> publish events -> aggregate parent status.

The pipeline never branches on execution_mode beyond asking the router for
the right transport (architecture section 10: mode is data, not code).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_contracts import ExecutionReport, Order, OrderStatus

from . import config, events
from .models import ChildOrderRow, ExecutionReportRow, ExecutionRow
from .portfolio_client import PortfolioForwarder
from .retry import PermanentTransportError, RetryExhaustedError
from .router import ExecutionRouter, split_order
from .schemas import ExecutionRequest

logger = logging.getLogger("execution-engine.pipeline")

OPEN_CHILD_STATUSES = {OrderStatus.SUBMITTED.value, OrderStatus.PARTIALLY_FILLED.value}


def build_ingest_payload(order: Order, report: ExecutionReport) -> dict:
    """ExecutionIngest body for portfolio-engine
    POST /portfolio/{account_id}/executions: the shared ExecutionReport
    fields plus the symbol/side context the contract does not carry."""
    commission = report.raw.get("commission", 0.0) if report.raw else 0.0
    return {
        "order_id": str(report.order_id),
        "status": report.status.value,
        "filled_quantity": report.filled_quantity,
        "average_fill_price": report.average_fill_price,
        "broker": report.broker,
        "reported_at": report.reported_at.isoformat(),
        "raw": report.raw,
        "symbol": order.symbol,
        "side": order.side.value,
        "commission": float(commission or 0.0),
    }


def _aggregate(execution: ExecutionRow, children: list[ChildOrderRow]) -> None:
    filled = sum(child.filled_quantity for child in children)
    execution.filled_quantity = filled
    if filled > 0:
        weighted = sum(
            child.filled_quantity * (child.average_fill_price or 0.0)
            for child in children
        )
        execution.average_fill_price = weighted / filled
    else:
        execution.average_fill_price = None

    statuses = {child.status for child in children}
    if OrderStatus.ERROR.value in statuses:
        execution.status = OrderStatus.ERROR.value
    elif statuses == {OrderStatus.FILLED.value}:
        execution.status = OrderStatus.FILLED.value
    elif statuses & OPEN_CHILD_STATUSES or OrderStatus.PENDING.value in statuses:
        execution.status = (
            OrderStatus.PARTIALLY_FILLED.value if filled > 0 else OrderStatus.SUBMITTED.value
        )
    elif filled > 0:
        execution.status = OrderStatus.PARTIALLY_FILLED.value
    elif OrderStatus.CANCELLED.value in statuses:
        execution.status = OrderStatus.CANCELLED.value
    else:
        execution.status = OrderStatus.REJECTED.value


def _child_order_model(parent: Order, child: ChildOrderRow) -> Order:
    return Order(
        id=uuid.UUID(child.id),
        signal_id=parent.signal_id,
        symbol=parent.symbol,
        side=parent.side,
        quantity=child.quantity,
        order_type=parent.order_type,
        price=parent.price,
        status=OrderStatus.PENDING,
        broker=parent.broker,
        account_id=parent.account_id,
        execution_mode=parent.execution_mode,
        created_at=datetime.now(timezone.utc),
    )


async def run_execution(
    db: Session,
    request: ExecutionRequest,
    router: ExecutionRouter,
    forwarder: PortfolioForwarder,
    actor: str | None,
) -> ExecutionRow:
    order = request.order

    execution = ExecutionRow(
        order_id=str(order.id),
        signal_id=str(order.signal_id),
        account_id=order.account_id,
        symbol=order.symbol,
        side=order.side.value,
        quantity=order.quantity,
        order_type=order.order_type.value,
        price=order.price,
        broker=order.broker,
        execution_mode=order.execution_mode.value,
        status=OrderStatus.PENDING.value,
        risk_decision=request.risk_decision.model_dump(mode="json"),
        requested_by=actor,
    )
    db.add(execution)
    db.flush()

    children = [
        ChildOrderRow(execution_id=execution.id, sequence=index, quantity=quantity)
        for index, quantity in enumerate(
            split_order(order.quantity, config.max_child_size())
        )
    ]
    db.add_all(children)
    db.flush()

    await events.publish_event(
        "order.submitted",
        {
            "execution_id": execution.id,
            "order_id": str(order.id),
            "account_id": order.account_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "execution_mode": order.execution_mode.value,
            "child_orders": len(children),
        },
    )

    for child in children:
        child_order = _child_order_model(order, child)
        try:
            report, attempts = await router.place_with_retry(
                child_order, request.market_price
            )
        except (RetryExhaustedError, PermanentTransportError) as exc:
            child.attempts = getattr(exc, "attempts", 1)
            child.status = OrderStatus.ERROR.value
            child.last_error = str(exc)
            logger.error(
                "child order %s (%s/%s) failed permanently: %s",
                child.id,
                child.sequence + 1,
                len(children),
                exc,
            )
            # Remaining children stay 'pending'; POST /executions/{id}/cancel
            # cancels them. Stop: continuing after a dead transport would
            # only spray more failures.
            break

        child.attempts = attempts
        child.status = report.status.value
        child.filled_quantity = report.filled_quantity
        child.average_fill_price = report.average_fill_price

        report_row = ExecutionReportRow(
            execution_id=execution.id,
            child_order_id=child.id,
            report_order_id=str(report.order_id),
            status=report.status.value,
            filled_quantity=report.filled_quantity,
            average_fill_price=report.average_fill_price,
            broker=report.broker,
            reported_at=report.reported_at.replace(tzinfo=None),
            raw=report.raw,
        )
        db.add(report_row)
        db.flush()

        if report.filled_quantity > 0:
            report_row.forwarded_to_portfolio = await forwarder.forward(
                order.account_id, build_ingest_payload(order, report)
            )

        await events.publish_event(
            "execution.report",
            {
                "execution_id": execution.id,
                "order_id": str(order.id),
                "child_order_id": child.id,
                "account_id": order.account_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "status": report.status.value,
                "filled_quantity": report.filled_quantity,
                "average_fill_price": report.average_fill_price,
                "broker": report.broker,
                "execution_mode": order.execution_mode.value,
            },
        )

    _aggregate(execution, children)
    db.flush()
    return execution


def children_of(db: Session, execution_id: str) -> list[ChildOrderRow]:
    return list(
        db.execute(
            select(ChildOrderRow)
            .where(ChildOrderRow.execution_id == execution_id)
            .order_by(ChildOrderRow.sequence)
        ).scalars()
    )


def reports_of(db: Session, execution_id: str) -> list[ExecutionReportRow]:
    return list(
        db.execute(
            select(ExecutionReportRow)
            .where(ExecutionReportRow.execution_id == execution_id)
            .order_by(ExecutionReportRow.created_at)
        ).scalars()
    )
