"""execution-engine service - Fases 9/10 (paper + live trading).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): convierte una Order
aprobada en ordenes de venue (paper-trading o broker-connectors), con
splitting, reintentos con backoff, confirmacion (ExecutionReports
persistidos + reenviados a portfolio-engine + publicados via NATS).

Invariantes:
- Toda orden llega con la RiskDecision que la aprobo; sin ella (o si no
  esta aprobada) se rechaza con 422 (principio 2.4: sin bypass del Risk
  Engine).
- Paper y live comparten EXACTAMENTE el mismo pipeline (seccion 10); el
  modo solo selecciona el transporte en el ExecutionRouter.
- Pasar a live es un acto explicito y auditable: el override del modo por
  request exige rol admin y cada ejecucion live emite un warning
  estructurado + evento `execution.live_order`.
"""

from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_contracts import ExecutionMode, ExecutionReport, OrderStatus
from trading_contracts.auth import TokenPayload

from . import config, events, pipeline
from .db import get_db
from .deps import get_optional_token, require_admin_override
from .models import ChildOrderRow, ExecutionReportRow, ExecutionRow
from .portfolio_client import PortfolioForwarder, get_portfolio_forwarder
from .router import ExecutionRouter, ModeUnavailableError, get_router
from .schemas import (
    CancelResponse,
    ChildOrderOut,
    ExecutionOut,
    ExecutionRequest,
    ModeInfo,
    ModesResponse,
)

SERVICE_NAME = "execution-engine"

logger = logging.getLogger("execution-engine")

app = FastAPI(title="execution-engine", version="0.2.0")

# Fase 14 (Monitoreo): default HTTP metrics (request count/latency/errors,
# in-progress gauge) exposed on /metrics for Prometheus. Guarded so repeated
# imports (tests) never register duplicate collectors.
if not getattr(app.state, "metrics_instrumented", False):
    Instrumentator(
        should_instrument_requests_inprogress=True,
        inprogress_labels=False,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, include_in_schema=False)
    app.state.metrics_instrumented = True

CANCELLABLE_EXECUTION_STATUSES = {
    OrderStatus.PENDING.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
    OrderStatus.ERROR.value,  # error may leave pending children behind
}


@app.on_event("startup")
async def _mark_stale_inflight_executions() -> None:
    """Startup reconciliation guard (architecture principle 2.6): in-flight
    executions older than EXECUTION_STALE_AFTER_SECONDS are marked
    'unknown' (needs reconciliation) instead of lying about being live.
    Exposed via GET /executions?status=unknown. Never touches the venue."""
    from . import db as db_module  # late import: tests swap SessionLocal

    try:
        with db_module.SessionLocal() as session:
            marked = pipeline.mark_stale_executions(
                session, stale_after_seconds=config.stale_after_seconds()
            )
            session.commit()
    except Exception:  # noqa: BLE001 - startup must not crash on a DB hiccup
        logger.exception("startup stale-execution marking failed")
        return

    for item in marked:
        logger.warning(
            "stale_execution_marked_unknown %s", json.dumps(item, default=str)
        )
        await events.publish_event("execution.marked_unknown", item)


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


def _to_out(
    execution: ExecutionRow,
    children: list[ChildOrderRow],
    reports: list[ExecutionReportRow],
) -> ExecutionOut:
    return ExecutionOut(
        id=execution.id,
        order_id=execution.order_id,
        signal_id=execution.signal_id,
        account_id=execution.account_id,
        symbol=execution.symbol,
        side=execution.side,
        quantity=execution.quantity,
        order_type=execution.order_type,
        price=execution.price,
        broker=execution.broker,
        execution_mode=execution.execution_mode,
        status=execution.status,
        filled_quantity=execution.filled_quantity,
        average_fill_price=execution.average_fill_price,
        requested_by=execution.requested_by,
        created_at=execution.created_at,
        child_orders=[
            ChildOrderOut(
                id=child.id,
                client_order_id=child.client_order_id,
                sequence=child.sequence,
                quantity=child.quantity,
                status=child.status,
                filled_quantity=child.filled_quantity,
                average_fill_price=child.average_fill_price,
                attempts=child.attempts,
                last_error=child.last_error,
            )
            for child in children
        ],
        reports=[
            ExecutionReport(
                order_id=report.report_order_id,
                status=report.status,
                filled_quantity=report.filled_quantity,
                average_fill_price=report.average_fill_price,
                broker=report.broker,
                reported_at=report.reported_at,
                raw=report.raw or {},
            )
            for report in reports
        ],
    )


def _load_execution(db: Session, execution_id: str) -> ExecutionRow:
    execution = db.get(ExecutionRow, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail=f"unknown execution '{execution_id}'")
    return execution


@app.post("/executions", response_model=ExecutionOut, status_code=201)
async def submit_execution(
    request: ExecutionRequest,
    db: Session = Depends(get_db),
    router: ExecutionRouter = Depends(get_router),
    forwarder: PortfolioForwarder = Depends(get_portfolio_forwarder),
    token: TokenPayload | None = Depends(get_optional_token),
) -> ExecutionOut:
    """Execute an approved Order. Body must include the approving
    RiskDecision (architecture principle 2.4) — 422 otherwise."""
    order = request.order
    decision = request.risk_decision

    # --- RiskDecision invariant ------------------------------------------
    if not decision.approved:
        raise HTTPException(
            status_code=422,
            detail="order is not backed by an approved RiskDecision "
            f"(reason: {decision.reason or 'rejected'})",
        )
    if decision.signal_id != order.signal_id:
        raise HTTPException(
            status_code=422,
            detail="RiskDecision.signal_id does not match Order.signal_id; "
            "the decision does not approve this order",
        )

    # --- Mode gate: override of the env default is admin-only ------------
    actor: str | None = token.sub if token else None
    if order.execution_mode != config.default_execution_mode():
        actor = require_admin_override(token).sub

    if order.execution_mode == ExecutionMode.LIVE:
        live_context = {
            "event": "live_execution",
            "order_id": str(order.id),
            "signal_id": str(order.signal_id),
            "account_id": order.account_id,
            "broker": order.broker,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "actor": actor,
        }
        logger.warning("live_execution %s", json.dumps(live_context, default=str))
        await events.publish_event("execution.live_order", live_context)

    try:
        execution = await pipeline.run_execution(db, request, router, forwarder, actor)
    except ModeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    db.commit()
    return _to_out(
        execution,
        pipeline.children_of(db, execution.id),
        pipeline.reports_of(db, execution.id),
    )


@app.get("/executions", response_model=list[ExecutionOut])
def list_executions(
    account_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[ExecutionOut]:
    query = select(ExecutionRow).order_by(ExecutionRow.created_at)
    if account_id is not None:
        query = query.where(ExecutionRow.account_id == account_id)
    if status is not None:
        query = query.where(ExecutionRow.status == status)
    rows = list(db.execute(query).scalars())
    return [
        _to_out(row, pipeline.children_of(db, row.id), pipeline.reports_of(db, row.id))
        for row in rows
    ]


@app.get("/executions/{execution_id}", response_model=ExecutionOut)
def get_execution(execution_id: str, db: Session = Depends(get_db)) -> ExecutionOut:
    execution = _load_execution(db, execution_id)
    return _to_out(
        execution,
        pipeline.children_of(db, execution_id),
        pipeline.reports_of(db, execution_id),
    )


@app.post("/executions/{execution_id}/cancel", response_model=CancelResponse)
async def cancel_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    router: ExecutionRouter = Depends(get_router),
) -> CancelResponse:
    """Cancel the remaining child orders of an execution: open children
    (submitted/partially filled) are cancelled at the transport; children
    never sent (pending) are cancelled locally."""
    execution = _load_execution(db, execution_id)
    if execution.status not in CANCELLABLE_EXECUTION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"execution '{execution_id}' is {execution.status}; nothing to cancel",
        )

    children = pipeline.children_of(db, execution_id)
    open_children = [c for c in children if c.status in pipeline.OPEN_CHILD_STATUSES]
    pending_children = [c for c in children if c.status == OrderStatus.PENDING.value]
    if not open_children and not pending_children:
        raise HTTPException(
            status_code=409,
            detail=f"execution '{execution_id}' has no cancellable child orders",
        )

    mode = ExecutionMode(execution.execution_mode)
    transport_cancelled = 0
    try:
        for child in open_children:
            if await router.cancel(
                mode, child.id, broker=execution.broker, account_id=execution.account_id
            ):
                transport_cancelled += 1
            child.status = OrderStatus.CANCELLED.value
    except ModeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    for child in pending_children:
        child.status = OrderStatus.CANCELLED.value

    execution.status = OrderStatus.CANCELLED.value
    db.commit()

    await events.publish_event(
        "execution.cancelled",
        {
            "execution_id": execution_id,
            "order_id": execution.order_id,
            "account_id": execution.account_id,
            "cancelled_children": len(open_children) + len(pending_children),
            "transport_cancelled": transport_cancelled,
        },
    )

    return CancelResponse(
        execution_id=execution_id,
        status=execution.status,
        cancelled_children=len(open_children) + len(pending_children),
        transport_cancelled=transport_cancelled,
    )


@app.get("/modes", response_model=ModesResponse)
def get_modes(router: ExecutionRouter = Depends(get_router)) -> ModesResponse:
    """Paper|live availability and execution configuration."""
    available = set(router.available_modes())
    return ModesResponse(
        default_mode=config.default_execution_mode().value,
        override_requires_admin=True,
        max_child_size=config.max_child_size(),
        modes={
            ExecutionMode.PAPER.value: ModeInfo(
                available=ExecutionMode.PAPER.value in available,
                transport="paper-trading",
                url=config.paper_trading_url(),
            ),
            ExecutionMode.LIVE.value: ModeInfo(
                available=ExecutionMode.LIVE.value in available,
                transport="broker-connectors",
                url=config.broker_connectors_url(),
            ),
        },
    )
