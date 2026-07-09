"""risk-engine service - Fase 7.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): valida cada TradeSignal
contra limites de riesgo, tamano de posicion y circuit breakers. Toda orden
pasa por POST /risk/validate, sin excepciones (principio 2.4); la respuesta
es sincrona porque execution-engine necesita la decision inmediata.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app import circuit_breaker as cb
from app import events, limits as limits_repo, pipeline
from app.db import get_db
from app.deps import require_admin
from app.portfolio_client import PortfolioClient, get_portfolio_client
from app.schemas import (
    CircuitBreakerStatus,
    ExtendedRiskLimits,
    RiskDecisionResponse,
    RiskLimitsResponse,
    ValidateRequest,
)
from trading_contracts.auth import TokenPayload

SERVICE_NAME = "risk-engine"

app = FastAPI(title="risk-engine", version="0.2.0")


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/risk/validate", response_model=RiskDecisionResponse)
async def validate(
    request: ValidateRequest,
    db: Session = Depends(get_db),
    client: PortfolioClient = Depends(get_portfolio_client),
) -> RiskDecisionResponse:
    """Validate a TradeSignal -> RiskDecision (approved/rejected, sized).

    Portfolio state is fetched from portfolio-engine unless supplied inline
    (portfolio_state) for tests/backtesting."""
    return await pipeline.validate_signal(db, request, client)


@app.get("/risk/limits/{account_id}", response_model=RiskLimitsResponse)
def get_limits(account_id: str, db: Session = Depends(get_db)) -> RiskLimitsResponse:
    limits, is_default = limits_repo.load_limits(db, account_id)
    return RiskLimitsResponse(account_id=account_id, limits=limits, is_default=is_default)


@app.put("/risk/limits/{account_id}", response_model=RiskLimitsResponse)
async def put_limits(
    account_id: str,
    limits: ExtendedRiskLimits,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_admin),
) -> RiskLimitsResponse:
    """Admin-only: upsert the account's risk limits."""
    saved = limits_repo.save_limits(db, account_id, limits)
    payload = {"account_id": account_id, "actor": admin.sub, "limits": saved.model_dump()}
    events.persist_event(db, account_id, "risk.limits_updated", payload)
    await events.publish_event("risk.limits_updated", payload)
    db.commit()
    return RiskLimitsResponse(account_id=account_id, limits=saved, is_default=False)


@app.get("/risk/circuit-breaker/{account_id}", response_model=CircuitBreakerStatus)
def get_circuit_breaker(account_id: str, db: Session = Depends(get_db)) -> CircuitBreakerStatus:
    row = cb.get_breaker(db, account_id)
    db.commit()  # row may have been auto-created
    return CircuitBreakerStatus(
        account_id=account_id,
        state=row.state,
        reason=row.reason,
        error_count=row.error_count,
        updated_at=row.updated_at,
    )


@app.post("/risk/circuit-breaker/{account_id}/reset", response_model=CircuitBreakerStatus)
async def reset_circuit_breaker(
    account_id: str,
    db: Session = Depends(get_db),
    admin: TokenPayload = Depends(require_admin),
) -> CircuitBreakerStatus:
    """Admin-only: force the breaker back to NORMAL (audited)."""
    row = cb.reset(db, account_id)
    payload = {"account_id": account_id, "state": row.state, "actor": admin.sub}
    events.persist_event(db, account_id, "risk.circuit_breaker_reset", payload)
    await events.publish_event("risk.circuit_breaker_reset", payload)
    db.commit()
    return CircuitBreakerStatus(
        account_id=account_id,
        state=row.state,
        reason=row.reason,
        error_count=row.error_count,
        updated_at=row.updated_at,
    )
