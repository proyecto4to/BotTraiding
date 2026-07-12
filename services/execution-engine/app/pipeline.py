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
from datetime import datetime, timedelta, timezone

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

# Status for in-flight executions found stale at startup: the venue may or may
# not hold the order, so nothing is assumed until reconciliation resolves it.
UNKNOWN_STATUS = "unknown"
STALE_MARKABLE_STATUSES = {OrderStatus.SUBMITTED.value, OrderStatus.PARTIALLY_FILLED.value}

# Fixed namespace for deterministic child client_order_ids. Never change this
# value: retried/replayed executions must derive the same ids forever.
CLIENT_ORDER_NAMESPACE = uuid.UUID("6de4f7a9-52f6-4a68-9713-6f34f1e5c0d7")


def child_client_order_id(execution_id: str, sequence: int) -> str:
    """Deterministic venue idempotency key for one child order.

    uuid5 over execution id + child index: exactly 36 chars (the Binance
    clientOrderId maximum), stable across retries and process restarts."""
    return str(uuid.uuid5(CLIENT_ORDER_NAMESPACE, f"{execution_id}:{sequence}"))


def build_ingest_payload(
    order: Order, report: ExecutionReport, client_order_id: str | None = None
) -> dict:
    """ExecutionIngest body for portfolio-engine
    POST /portfolio/{account_id}/executions: the shared ExecutionReport
    fields plus the symbol/side context the contract does not carry."""
    commission = report.raw.get("commission", 0.0) if report.raw else 0.0
    return {
        "order_id": str(report.order_id),
        "client_order_id": client_order_id,
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
    # The Order.id sent to the venue IS the child's persisted client_order_id
    # (idempotency key): retries and post-timeout queries reuse it verbatim.
    return Order(
        id=uuid.UUID(child.client_order_id or child.id),
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

    # Child rows (with their deterministic client_order_ids) are flushed
    # BEFORE any transport attempt: a crash/timeout mid-placement can always
    # be reconciled against the persisted idempotency keys.
    children = []
    for index, quantity in enumerate(split_order(order.quantity, config.max_child_size())):
        cid = child_client_order_id(execution.id, index)
        children.append(
            ChildOrderRow(
                id=cid,
                client_order_id=cid,
                execution_id=execution.id,
                sequence=index,
                quantity=quantity,
            )
        )
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
            client_order_id=child.client_order_id,
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
                order.account_id,
                build_ingest_payload(order, report, child.client_order_id),
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


def mark_stale_executions(
    db: Session, *, stale_after_seconds: float, now: datetime | None = None
) -> list[dict]:
    """Startup safety net (architecture principle 2.6): in-flight executions
    (submitted/partially_filled) whose last update is older than
    ``stale_after_seconds`` are marked ``unknown`` — the venue may or may not
    hold them, so leaving them silently in-flight would lie about state.
    They are surfaced via GET /executions?status=unknown until reconciliation
    resolves them. Returns a summary dict per marked execution."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    rows = db.execute(
        select(ExecutionRow).where(ExecutionRow.status.in_(STALE_MARKABLE_STATUSES))
    ).scalars()

    marked: list[dict] = []
    for execution in rows:
        anchor = execution.updated_at or execution.created_at
        if anchor is None or anchor > cutoff:
            continue
        execution.status = UNKNOWN_STATUS
        for child in children_of(db, execution.id):
            if child.status in OPEN_CHILD_STATUSES:
                child.status = UNKNOWN_STATUS
                child.last_error = (
                    "stale in-flight at startup; needs reconciliation against the venue"
                )
        marked.append(
            {
                "execution_id": execution.id,
                "order_id": execution.order_id,
                "account_id": execution.account_id,
                "symbol": execution.symbol,
                "broker": execution.broker,
                "execution_mode": execution.execution_mode,
                "previous_status": "in-flight",
                "status": UNKNOWN_STATUS,
                "last_update": anchor.isoformat(),
            }
        )
    db.flush()
    return marked


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
