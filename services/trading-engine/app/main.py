"""trading-engine service - Fase 16 (bot orchestrator).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): orquestador del flujo
senal -> riesgo -> ejecucion (coordinador, sin logica propia). Un Bot es
configuracion pura (cuenta, broker, simbolos, timeframe, estrategias,
intervalo); el orquestador (app/orchestrator.py) ejecuta un ciclo por
intervalo via clientes inyectables (app/clients.py).

Invariantes:
- trading-engine NUNCA habla con un broker: datos de mercado solo via
  broker-connectors, ordenes solo via execution-engine;
- sin RiskDecision aprobada no hay Order (principio 2.4);
- HARD_HALT del circuit breaker salta el ciclo completo (y lo registra);
- bots live requieren rol admin; bots paper cualquier usuario autenticado.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_contracts.auth import TokenPayload

from . import events, orchestrator
from .clients import Clients, get_clients
from .db import get_db
from .deps import get_token_payload, require_mode_role
from .models import BotRow, CycleReportRow
from .orchestrator import runner
from .schemas import (
    BOT_STATUS_RUNNING,
    BOT_STATUS_STOPPED,
    BotActionResponse,
    BotCreate,
    BotOut,
    BotUpdate,
    CycleReportOut,
)

SERVICE_NAME = "trading-engine"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reconciliation (architecture principle 6): a crash must not leave
    # phantom 'running' bots that no loop is actually driving.
    try:
        from . import db as db_module

        with db_module.SessionLocal() as session:
            orphaned = orchestrator.mark_orphaned_bots(session)
            session.commit()
        if orphaned:
            logger.warning("marked %d orphaned bot(s) as error on startup", orphaned)
    except Exception:  # noqa: BLE001 - DB may be briefly unavailable
        logger.exception("startup bot reconciliation failed")
    yield
    await runner.stop_all()


app = FastAPI(title="trading-engine", version="0.2.0", lifespan=lifespan)

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


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


def _load_bot(db: Session, bot_id: str) -> BotRow:
    row = db.get(BotRow, bot_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown bot '{bot_id}'")
    return row


def _to_out(row: BotRow) -> BotOut:
    return orchestrator.bot_to_spec(row)


def _cycle_out(row: CycleReportRow) -> CycleReportOut:
    return CycleReportOut(
        id=row.id,
        bot_id=row.bot_id,
        status=row.status,
        reason=row.reason,
        started_at=row.started_at,
        finished_at=row.finished_at,
        signals=row.signals or [],
        decisions=row.decisions or [],
        orders=row.orders or [],
        errors=row.errors or [],
    )


# --- Bot CRUD ---------------------------------------------------------------


@app.post("/bots", response_model=BotOut, status_code=201)
def create_bot(
    body: BotCreate,
    db: Session = Depends(get_db),
    token: TokenPayload = Depends(get_token_payload),
) -> BotOut:
    """Create a bot (status=stopped). Live-mode bots require role 'admin'."""
    require_mode_role(token, body.execution_mode)
    row = BotRow(
        name=body.name,
        account_id=body.account_id,
        broker=body.broker,
        execution_mode=body.execution_mode.value,
        symbols=body.symbols,
        timeframe=body.timeframe,
        strategy_keys=body.strategy_keys,
        params_overrides=body.params_overrides,
        risk_allocation=body.risk_allocation,
        cycle_interval_seconds=body.cycle_interval_seconds,
        status=BOT_STATUS_STOPPED,
        created_by=token.sub,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@app.get("/bots", response_model=list[BotOut])
def list_bots(
    account_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[BotOut]:
    query = select(BotRow).order_by(BotRow.created_at)
    if account_id is not None:
        query = query.where(BotRow.account_id == account_id)
    if status is not None:
        query = query.where(BotRow.status == status)
    return [_to_out(row) for row in db.scalars(query).all()]


@app.get("/bots/{bot_id}", response_model=BotOut)
def get_bot(bot_id: str, db: Session = Depends(get_db)) -> BotOut:
    return _to_out(_load_bot(db, bot_id))


@app.patch("/bots/{bot_id}", response_model=BotOut)
def update_bot(
    bot_id: str,
    body: BotUpdate,
    db: Session = Depends(get_db),
    token: TokenPayload = Depends(get_token_payload),
) -> BotOut:
    """Update bot configuration. Only allowed while the bot is NOT running;
    switching a bot to (or editing a bot in) live mode requires 'admin'."""
    row = _load_bot(db, bot_id)
    if row.status == BOT_STATUS_RUNNING:
        raise HTTPException(
            status_code=409,
            detail="bot is running; stop it before changing its configuration",
        )
    # Gate on both current and target mode: editing a live bot and turning a
    # paper bot live are equally privileged acts.
    require_mode_role(token, row.execution_mode)
    if body.execution_mode is not None:
        require_mode_role(token, body.execution_mode)

    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        if name == "execution_mode":
            value = value.value if hasattr(value, "value") else value
        setattr(row, name, value)
    db.commit()
    db.refresh(row)
    return _to_out(row)


# --- Lifecycle --------------------------------------------------------------


@app.post("/bots/{bot_id}/start", response_model=BotActionResponse)
async def start_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    token: TokenPayload = Depends(get_token_payload),
) -> BotActionResponse:
    """Start the bot's cycle loop. Paper bots: any authenticated user;
    live bots: role 'admin'."""
    row = _load_bot(db, bot_id)
    require_mode_role(token, row.execution_mode)
    if row.status == BOT_STATUS_RUNNING and runner.is_running(bot_id):
        raise HTTPException(status_code=409, detail="bot is already running")

    row.status = BOT_STATUS_RUNNING
    row.status_reason = None
    db.commit()
    db.refresh(row)
    if not runner.is_running(bot_id):
        runner.start(bot_id)

    await events.publish_event(
        "bot.started",
        {
            "bot_id": bot_id,
            "name": row.name,
            "account_id": row.account_id,
            "execution_mode": row.execution_mode,
            "actor": token.sub,
        },
    )
    return BotActionResponse(bot=_to_out(row), detail="bot started")


@app.post("/bots/{bot_id}/stop", response_model=BotActionResponse)
async def stop_bot(
    bot_id: str,
    db: Session = Depends(get_db),
    token: TokenPayload = Depends(get_token_payload),
) -> BotActionResponse:
    """Stop the bot's cycle loop (also clears an error status)."""
    row = _load_bot(db, bot_id)
    require_mode_role(token, row.execution_mode)
    if row.status == BOT_STATUS_STOPPED and not runner.is_running(bot_id):
        raise HTTPException(status_code=409, detail="bot is not running")

    await runner.stop(bot_id)
    row.status = BOT_STATUS_STOPPED
    row.status_reason = None
    db.commit()
    db.refresh(row)

    await events.publish_event(
        "bot.stopped",
        {"bot_id": bot_id, "name": row.name, "reason": "requested", "actor": token.sub},
    )
    return BotActionResponse(bot=_to_out(row), detail="bot stopped")


@app.post("/bots/{bot_id}/run-once", response_model=CycleReportOut)
async def run_once(
    bot_id: str,
    db: Session = Depends(get_db),
    token: TokenPayload = Depends(get_token_payload),
    clients: Clients = Depends(get_clients),
) -> CycleReportOut:
    """Run a single synchronous cycle and return its CycleReport - the
    debugging/testing seam. Rejected while the bot's loop is running (a
    cycle would overlap with the loop's)."""
    row = _load_bot(db, bot_id)
    require_mode_role(token, row.execution_mode)
    if row.status == BOT_STATUS_RUNNING or runner.is_running(bot_id):
        raise HTTPException(
            status_code=409, detail="bot is running; stop it before run-once"
        )

    bot = _to_out(row)
    outcome = await orchestrator.run_cycle(bot, clients)
    report = orchestrator.persist_outcome(db, outcome)
    db.commit()
    db.refresh(report)
    await orchestrator.publish_cycle_event(bot, report)
    return _cycle_out(report)


@app.get("/bots/{bot_id}/cycles", response_model=list[CycleReportOut])
def list_cycles(
    bot_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[CycleReportOut]:
    """Recent cycle reports for a bot, newest first."""
    _load_bot(db, bot_id)
    rows = db.scalars(
        select(CycleReportRow)
        .where(CycleReportRow.bot_id == bot_id)
        .order_by(CycleReportRow.started_at.desc(), CycleReportRow.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_cycle_out(row) for row in rows]
