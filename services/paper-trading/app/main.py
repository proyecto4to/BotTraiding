"""paper-trading service - Fase 9 (broker simulado).

Responsabilidad (docs/ARCHITECTURE.md seccion 3/10): mismo execution-engine,
adapter de broker "simulado" en vez de real. Este servicio ES ese adapter:
mantiene cuentas simuladas (cash/posiciones) y llena ordenes contra el
precio de mercado que envia el caller, aplicando spread, slippage (fijo +
impacto por tamano), comision, fills parciales, latencia y rechazos por
saldo insuficiente. Los resultados son ExecutionReports del contrato
compartido, de modo que execution-engine usa exactamente el mismo pipeline
en paper y en live (solo cambia execution_mode).
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from trading_contracts import ExecutionReport, OrderStatus, Position

from . import engine
from .config import FillConfig, get_fill_config
from .db import get_db
from .models import PaperAccountRow, PaperOrderRow
from .schemas import (
    CreateAccountRequest,
    PaperAccountResponse,
    PaperOrderDetail,
    PaperOrderRequest,
)

SERVICE_NAME = "paper-trading"

app = FastAPI(title="paper-trading", version="0.2.0")

CANCELLABLE_STATUSES = {
    OrderStatus.PENDING.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
}


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


def _account_response(db: Session, account: PaperAccountRow) -> PaperAccountResponse:
    positions_value = sum(
        row.quantity * row.average_price for row in engine.positions_for(db, account.id)
    )
    return PaperAccountResponse(
        account_id=account.id,
        starting_cash=account.starting_cash,
        cash=account.cash,
        positions_value=positions_value,
        equity=account.cash + positions_value,
        currency=account.currency,
        created_at=account.created_at,
    )


def _order_detail(row: PaperOrderRow) -> PaperOrderDetail:
    return PaperOrderDetail(
        order_id=row.id,
        account_id=row.account_id,
        symbol=row.symbol,
        side=row.side,
        order_type=row.order_type,
        quantity=row.quantity,
        filled_quantity=row.filled_quantity,
        average_fill_price=row.average_fill_price,
        reference_price=row.reference_price,
        commission=row.commission,
        status=row.status,
        raw=row.raw or {},
        created_at=row.created_at,
    )


def _require_account(db: Session, account_id: str) -> PaperAccountRow:
    account = db.get(PaperAccountRow, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"unknown paper account '{account_id}'")
    return account


@app.post("/paper/accounts", response_model=PaperAccountResponse, status_code=201)
def create_account(
    body: CreateAccountRequest, db: Session = Depends(get_db)
) -> PaperAccountResponse:
    account_id = body.account_id or str(uuid.uuid4())
    if db.get(PaperAccountRow, account_id) is not None:
        raise HTTPException(status_code=409, detail=f"paper account '{account_id}' exists")
    account = PaperAccountRow(
        id=account_id,
        starting_cash=body.starting_cash,
        cash=body.starting_cash,
        currency=body.currency,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_response(db, account)


@app.get("/paper/accounts/{account_id}", response_model=PaperAccountResponse)
def get_account(account_id: str, db: Session = Depends(get_db)) -> PaperAccountResponse:
    return _account_response(db, _require_account(db, account_id))


@app.post("/paper/accounts/{account_id}/reset", response_model=PaperAccountResponse)
def reset_account(account_id: str, db: Session = Depends(get_db)) -> PaperAccountResponse:
    account = _require_account(db, account_id)
    engine.reset_account(db, account)
    db.commit()
    db.refresh(account)
    return _account_response(db, account)


@app.post("/paper/orders", response_model=ExecutionReport)
async def place_order(
    body: PaperOrderRequest,
    db: Session = Depends(get_db),
    config: FillConfig = Depends(get_fill_config),
) -> ExecutionReport:
    """Fill the order against the caller-supplied market price, applying
    spread/slippage/size-impact/commission/latency/partial-fill/reject
    simulation. Returns a shared-contract ExecutionReport."""
    try:
        report = await engine.execute_order(db, body, config)
    except engine.DuplicateOrderError as exc:
        raise HTTPException(
            status_code=409, detail=f"order '{exc}' was already processed"
        ) from exc
    db.commit()
    return report


@app.get("/paper/orders/{order_id}", response_model=PaperOrderDetail)
def get_order(order_id: str, db: Session = Depends(get_db)) -> PaperOrderDetail:
    row = db.get(PaperOrderRow, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown paper order '{order_id}'")
    return _order_detail(row)


@app.post("/paper/orders/{order_id}/cancel", response_model=PaperOrderDetail)
def cancel_order(order_id: str, db: Session = Depends(get_db)) -> PaperOrderDetail:
    """Cancel the unfilled remainder of an open (pending/submitted/partially
    filled) order. Terminal orders return 409."""
    row = db.get(PaperOrderRow, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown paper order '{order_id}'")
    if row.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"order '{order_id}' is {row.status}; cannot cancel"
        )
    row.status = OrderStatus.CANCELLED.value
    db.commit()
    db.refresh(row)
    return _order_detail(row)


@app.get("/paper/positions/{account_id}", response_model=list[Position])
def get_positions(account_id: str, db: Session = Depends(get_db)) -> list[Position]:
    _require_account(db, account_id)
    return [
        Position(
            symbol=row.symbol,
            quantity=row.quantity,
            average_price=row.average_price,
            unrealized_pnl=0.0,  # the simulator holds no market marks
            account_id=account_id,
        )
        for row in engine.positions_for(db, account_id)
    ]
