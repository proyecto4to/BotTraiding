"""autonomy-controller service (P4): the self-driving brain.

Behind a single on/off switch it runs the platform hands-off — detecting the
market regime, selecting strategies and managing paper bots on trading-engine,
all under the existing risk controls. Operator control endpoints (enable/
disable/halt/reset) are admin-only; the tick is an internal endpoint the
scheduler drives on a cadence.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from trading_contracts.auth import TokenPayload

from . import controller, events, statemachine
from .clients import Clients, get_clients
from .db import get_db
from .deps import require_admin
from .schemas import DecisionOut, HaltRequest, StateOut, TickResult

SERVICE_NAME = "autonomy-controller"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.db import SessionLocal

    try:
        with SessionLocal() as session:
            statemachine.get_state(session)  # ensure the singleton row exists
    except Exception as exc:  # noqa: BLE001
        logger.error("state init failed: %s", exc)
    yield


app = FastAPI(title=SERVICE_NAME, version="0.1.0", lifespan=lifespan)

if not getattr(app.state, "metrics_instrumented", False):
    Instrumentator(
        should_instrument_requests_inprogress=True,
        inprogress_labels=False,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, include_in_schema=False)
    app.state.metrics_instrumented = True


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/autonomy/state", response_model=StateOut)
def get_state(db: Session = Depends(get_db)) -> StateOut:
    return StateOut(**statemachine.presentation(statemachine.get_state(db)))


@app.post("/autonomy/enable", response_model=StateOut)
async def enable(
    db: Session = Depends(get_db), admin: TokenPayload = Depends(require_admin)
) -> StateOut:
    try:
        row = statemachine.enable(db, actor=admin.sub)
    except statemachine.InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await events.publish_event("autonomy.enabled", {"actor": admin.sub, "state": row.state})
    return StateOut(**statemachine.presentation(row))


@app.post("/autonomy/disable", response_model=StateOut)
async def disable(
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_admin),
    clients: Clients = Depends(get_clients),
) -> StateOut:
    await controller.stop_all_autonomy_bots(clients)
    row = statemachine.disable(db, actor=admin.sub)
    await events.publish_event("autonomy.disabled", {"actor": admin.sub})
    return StateOut(**statemachine.presentation(row))


@app.post("/autonomy/halt", response_model=StateOut)
async def halt(
    body: HaltRequest | None = None,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_admin),
    clients: Clients = Depends(get_clients),
) -> StateOut:
    """Kill switch: force HALTED and stop autonomy bots. Needs a reset to resume."""
    reason = body.reason if body else "manual kill switch"
    await controller.stop_all_autonomy_bots(clients)
    row = statemachine.halt(db, reason=reason, actor=admin.sub)
    await events.publish_event("autonomy.halted", {"actor": admin.sub, "reason": reason})
    return StateOut(**statemachine.presentation(row))


@app.post("/autonomy/reset", response_model=StateOut)
async def reset(
    db: Session = Depends(get_db), admin: TokenPayload = Depends(require_admin)
) -> StateOut:
    try:
        row = statemachine.reset(db, actor=admin.sub)
    except statemachine.InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await events.publish_event("autonomy.reset", {"actor": admin.sub})
    return StateOut(**statemachine.presentation(row))


@app.post("/autonomy/tick", response_model=TickResult)
async def tick(
    db: Session = Depends(get_db), clients: Clients = Depends(get_clients)
) -> TickResult:
    """Run one autonomy cycle. Internal endpoint (scheduler-driven); not exposed
    through the gateway."""
    result = await controller.run_cycle(db, clients)
    await events.publish_event(
        "autonomy.cycle",
        {"state": result.state, "acted": result.acted, "summary": result.summary},
    )
    return result


@app.get("/autonomy/decisions", response_model=list[DecisionOut])
def decisions(
    limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)
) -> list[DecisionOut]:
    return [DecisionOut.model_validate(row) for row in controller.recent_decisions(db, limit)]
