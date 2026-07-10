"""REST endpoints for the optimizer (Fase 12).

POST /optimize runs synchronously when the budget is small (env
OPTIMIZER_SYNC_BUDGET, default 32 candidates) and in a background task
otherwise; either way the run id is immediately queryable via
GET /optimize/{id}.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from trading_strategies.plugin import ParameterValidationError

from . import db as db_module
from .db import get_db
from .models import OptimizationRunRecord
from .pipeline import create_run, execute_run
from .schemas import (
    OptimizationResultOut,
    OptimizationRunDetail,
    OptimizationRunOut,
    OptimizeRequest,
)
from .validation import PromotionDecision

logger = logging.getLogger("optimizer.api")

router = APIRouter(tags=["optimize"])


def _sync_budget_limit() -> int:
    return int(os.environ.get("OPTIMIZER_SYNC_BUDGET", "32"))


def _run_out(run: OptimizationRunRecord) -> OptimizationRunOut:
    return OptimizationRunOut(
        id=run.id,
        strategy_key=run.strategy_key,
        strategy_version=run.strategy_version,
        symbol=run.symbol,
        timeframe=run.timeframe,
        start_date=run.start_date,
        end_date=run.end_date,
        search_type=run.search_type,
        budget=run.budget,
        status=run.status,
        baseline_params=run.baseline_params,
        best_params=run.best_params,
        promoted=run.promoted,
        applied=run.applied,
        decision=PromotionDecision(**run.decision) if run.decision else None,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _execute_in_background(run_id: str, request: OptimizeRequest) -> None:
    """Background tasks get their own session (the request's is closed)."""
    session = db_module.SessionLocal()
    try:
        await execute_run(session, run_id, request)
    finally:
        session.close()


@router.post("/optimize", response_model=OptimizationRunOut, status_code=201)
async def start_optimization(
    body: OptimizeRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> OptimizationRunOut:
    try:
        run = create_run(db, body)
    except ParameterValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "unknown strategy" in str(exc) else 422,
                            detail=str(exc))

    if body.budget <= _sync_budget_limit():
        await execute_run(db, run.id, body)
        db.refresh(run)
    else:
        background.add_task(_execute_in_background, run.id, body)
        logger.info(
            "run %s scheduled in background (budget %d > sync limit %d)",
            run.id, body.budget, _sync_budget_limit(),
        )
    return _run_out(run)


@router.get("/optimize", response_model=list[OptimizationRunOut])
def list_optimizations(
    strategy_key: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[OptimizationRunOut]:
    query = db.query(OptimizationRunRecord)
    if strategy_key:
        query = query.filter(OptimizationRunRecord.strategy_key == strategy_key)
    rows = (
        query.order_by(
            OptimizationRunRecord.started_at.desc(), OptimizationRunRecord.id
        )
        .limit(limit)
        .all()
    )
    return [_run_out(r) for r in rows]


@router.get("/optimize/{run_id}", response_model=OptimizationRunDetail)
def get_optimization(run_id: str, db: Session = Depends(get_db)) -> OptimizationRunDetail:
    run = db.get(OptimizationRunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run '{run_id}'")
    base = _run_out(run).model_dump()
    return OptimizationRunDetail(
        **base,
        results=[
            OptimizationResultOut(
                parameters=r.parameters,
                metrics=r.metrics,
                out_of_sample=r.out_of_sample,
                window_index=r.window_index,
                role=r.role,
            )
            for r in sorted(
                run.results, key=lambda r: (r.window_index, not r.out_of_sample, r.role)
            )
        ],
    )
