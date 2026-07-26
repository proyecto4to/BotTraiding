"""portfolio-engine service - Fase 7.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): estado de cuenta por
account_id: posiciones, cash, margen, PnL realizado/no realizado,
exposicion por simbolo/sector/moneda, matriz de correlacion de posiciones
abiertas y drawdown (peak-equity + flotante).

Consumido de forma sincrona por risk-engine (GET /portfolio/{account_id})
y alimentado por execution-engine (POST /portfolio/{account_id}/executions).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from app import events, portfolio, reconcile
from app.db import get_db
from app.deps import require_admin, require_caller
from app.schemas import (
    DrawdownReport,
    ExecutionIngest,
    ExecutionIngestResult,
    ExposureReport,
    MarkRequest,
    PortfolioState,
    ReconciliationReport,
    ReconcileRequest,
)
from trading_contracts.auth import TokenPayload

SERVICE_NAME = "portfolio-engine"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Report-only reconciliation at startup when RECONCILE_ON_START=true; never
    # applies changes and never crashes startup (needs a connected broker
    # session, so it is off by default).
    try:
        await reconcile.run_startup_reconciliation()
    except Exception as exc:  # defensive: startup must survive a broker outage
        logger.error("startup reconciliation failed: %s", exc)
    yield


app = FastAPI(title="portfolio-engine", version="0.3.0", lifespan=lifespan)

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


@app.get("/portfolio/{account_id}", response_model=PortfolioState)
def get_portfolio(account_id: str, db: Session = Depends(get_db)) -> PortfolioState:
    """Full portfolio snapshot: account state, open positions, marks,
    injected return series, exposure, correlation matrix and drawdown."""
    state = portfolio.build_state(db, account_id)
    db.commit()  # account row may have been auto-created
    return state


@app.get("/portfolio/{account_id}/exposure", response_model=ExposureReport)
def get_exposure(account_id: str, db: Session = Depends(get_db)) -> ExposureReport:
    report = portfolio.build_exposure(db, account_id)
    db.commit()
    return report


@app.get("/portfolio/{account_id}/drawdown", response_model=DrawdownReport)
def get_drawdown(account_id: str, db: Session = Depends(get_db)) -> DrawdownReport:
    report = portfolio.build_drawdown(db, account_id)
    db.commit()
    return report


@app.post("/portfolio/{account_id}/executions", response_model=ExecutionIngestResult)
def ingest_execution(
    account_id: str,
    ingest: ExecutionIngest,
    db: Session = Depends(get_db),
    _caller: TokenPayload = Depends(require_caller),
) -> ExecutionIngestResult:
    """Ingest an ExecutionReport (execution-engine callback): updates the
    position, cash, realized PnL and peak equity."""
    return portfolio.apply_execution(db, account_id, ingest)


@app.post("/portfolio/{account_id}/mark", response_model=PortfolioState)
def mark_portfolio(
    account_id: str,
    mark: MarkRequest,
    db: Session = Depends(get_db),
    _caller: TokenPayload = Depends(require_caller),
) -> PortfolioState:
    """Update marks (and optionally injected return series) then recompute
    unrealized PnL, floating drawdown and peak equity."""
    return portfolio.apply_mark(db, account_id, mark)


@app.post("/portfolio/{account_id}/reconcile", response_model=ReconciliationReport)
async def reconcile_portfolio(
    account_id: str,
    body: ReconcileRequest,
    _admin: TokenPayload = Depends(require_admin),
    db: Session = Depends(get_db),
    broker_client: reconcile.HttpBrokerClient = Depends(reconcile.get_broker_client),
) -> ReconciliationReport:
    """Compare local positions against broker truth (admin only).

    apply=false (default) only reports discrepancies. apply=true aligns local
    positions to the broker, recording each correction as an auditable
    synthetic execution (source="reconciliation") and publishing a
    reconciliation event. Cash is never touched — it is an inventory
    correction, not a trade.
    """
    broker_account_id = body.broker_account_id or account_id
    try:
        broker_positions = await broker_client.get_positions(body.broker, broker_account_id)
    except reconcile.BrokerClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    broker_balance = None
    try:
        broker_balance = (
            await broker_client.get_account(body.broker, broker_account_id)
        ).balance
    except reconcile.BrokerClientError:
        # Balances are best-effort context; a positions-only reconcile is valid.
        pass

    account = portfolio.get_or_create_account(db, account_id)
    report = reconcile.build_report(
        account_id,
        body.broker,
        broker_account_id,
        reconcile.local_positions(db, account_id),
        broker_positions,
        reconcile.qty_tolerance(),
    )
    report.local_cash = account.cash
    report.broker_balance = broker_balance

    if body.apply and report.discrepancies:
        report.adjustments = reconcile.apply_report(db, account_id, report)
        report.applied = True
        portfolio._update_peak_equity(db, account)
        db.commit()
    else:
        db.commit()  # persist any auto-created account; report-only writes nothing else

    reconcile.log_report(report, context="on-demand")
    if report.discrepancies or report.applied:
        await events.publish_event(
            "portfolio.reconciliation", report.model_dump(mode="json")
        )
    return report
