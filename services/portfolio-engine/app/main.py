"""portfolio-engine service - Fase 7.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): estado de cuenta por
account_id: posiciones, cash, margen, PnL realizado/no realizado,
exposicion por simbolo/sector/moneda, matriz de correlacion de posiciones
abiertas y drawdown (peak-equity + flotante).

Consumido de forma sincrona por risk-engine (GET /portfolio/{account_id})
y alimentado por execution-engine (POST /portfolio/{account_id}/executions).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from app import portfolio
from app.db import get_db
from app.schemas import (
    DrawdownReport,
    ExecutionIngest,
    ExecutionIngestResult,
    ExposureReport,
    MarkRequest,
    PortfolioState,
)

SERVICE_NAME = "portfolio-engine"

app = FastAPI(title="portfolio-engine", version="0.2.0")

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
    account_id: str, ingest: ExecutionIngest, db: Session = Depends(get_db)
) -> ExecutionIngestResult:
    """Ingest an ExecutionReport (execution-engine callback): updates the
    position, cash, realized PnL and peak equity."""
    return portfolio.apply_execution(db, account_id, ingest)


@app.post("/portfolio/{account_id}/mark", response_model=PortfolioState)
def mark_portfolio(
    account_id: str, mark: MarkRequest, db: Session = Depends(get_db)
) -> PortfolioState:
    """Update marks (and optionally injected return series) then recompute
    unrealized PnL, floating drawdown and peak equity."""
    return portfolio.apply_mark(db, account_id, mark)
