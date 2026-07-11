"""backtester service - Fase 8.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): simula estrategias contra
historico con spread/slippage/comision/latencia.

Runs the SAME strategy code the strategy-engine serves (the shared
`trading_strategies` registry) through an event-driven engine with
realistic frictions (see app/engine.py for the fill-timing and
conservatism rules), persists runs/results in backtester-owned tables
(Alembic, version_table="alembic_version_backtester") and exposes:

- POST /backtests            run a backtest synchronously, persist, return results
- GET  /backtests/{id}       full results: metrics, equity curve, trade list
- GET  /backtests            list/compare runs (filter by strategy_key/symbol)

Runs are synchronous and bounded by BACKTESTER_MAX_BARS (default 20000);
larger datasets are rejected rather than silently queued (async jobs are a
later fase, together with the optimizer).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from trading_strategies import (
    ParameterValidationError,
    UnknownStrategyError,
    load_builtin_strategies,
)

from app import models, schemas
from app.data import (
    CsvDataSource,
    DataLoadError,
    HistoricalDataSource,
    SyntheticDataSource,
)
from app.db import get_db
from app.engine import BacktestConfig, EngineError, run_backtest

SERVICE_NAME = "backtester"
MAX_BARS = int(os.environ.get("BACKTESTER_MAX_BARS", "20000"))

#: Shared registry with every builtin strategy loaded (idempotent).
strategy_registry = load_builtin_strategies()

app = FastAPI(title="backtester", version="0.2.0")

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


# --- helpers ---------------------------------------------------------------------


def _naive_utc(ts: Optional[datetime]) -> Optional[datetime]:
    """DB columns are naive UTC; normalize any tz-aware timestamp."""
    if ts is None:
        return None
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _build_data_source(
    cfg: schemas.CsvDataConfig | schemas.SyntheticDataConfig,
) -> HistoricalDataSource:
    """Injectable seam: CSV / synthetic today, broker history later."""
    if isinstance(cfg, schemas.CsvDataConfig):
        return CsvDataSource(path=cfg.path, content=cfg.content)
    return SyntheticDataSource(
        regime=cfg.regime,
        n_bars=cfg.n_bars,
        seed=cfg.seed,
        start_price=cfg.start_price,
        drift=cfg.drift,
        volatility=cfg.volatility,
        mean_reversion=cfg.mean_reversion,
        base_volume=cfg.base_volume,
    )


def _detail(
    run: models.BacktestRun, result: Optional[models.BacktestResult]
) -> schemas.BacktestDetail:
    return schemas.BacktestDetail(
        id=run.id,
        strategy_key=run.strategy_key,
        symbol=run.symbol,
        timeframe=run.timeframe,
        status=run.status,
        initial_capital=run.initial_capital,
        parameters=run.parameters,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        friction=run.friction,
        data_config=run.data_config,
        start_at=run.start_at,
        end_at=run.end_at,
        metrics=result.metrics if result else None,
        equity_curve=result.equity_curve if result else [],
        trades=result.trades if result else [],
        stats=result.stats if result else {},
    )


def _summary(run: models.BacktestRun, metrics: Optional[dict]) -> schemas.BacktestSummary:
    return schemas.BacktestSummary(
        id=run.id,
        strategy_key=run.strategy_key,
        symbol=run.symbol,
        timeframe=run.timeframe,
        status=run.status,
        initial_capital=run.initial_capital,
        parameters=run.parameters,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        metrics=metrics,
    )


# --- endpoints --------------------------------------------------------------------


@app.post("/backtests", response_model=schemas.BacktestDetail, status_code=201)
def create_backtest(
    request: schemas.BacktestCreateRequest, db: Session = Depends(get_db)
) -> schemas.BacktestDetail:
    """Run one strategy over one symbol's history, synchronously.

    Validates the strategy key/params against the shared registry, loads
    the requested data, runs the engine and persists run + results.
    """
    try:
        strategy = strategy_registry.create(request.strategy_key, request.params)
    except UnknownStrategyError:
        raise HTTPException(
            status_code=404, detail=f"unknown strategy_key '{request.strategy_key}'"
        )
    except ParameterValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid params: {exc}")

    try:
        source = _build_data_source(request.data)
        bars = source.get_bars(
            request.symbol, request.timeframe, start=request.start, end=request.end
        )
    except DataLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not bars:
        raise HTTPException(status_code=400, detail="no bars in the requested range")
    if len(bars) > MAX_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"{len(bars)} bars exceeds the synchronous limit of {MAX_BARS} "
            "(BACKTESTER_MAX_BARS)",
        )

    run = models.BacktestRun(
        strategy_key=request.strategy_key,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_at=_naive_utc(bars[0].timestamp),
        end_at=_naive_utc(bars[-1].timestamp),
        initial_capital=request.initial_capital,
        parameters=strategy.params,
        friction=request.friction.model_dump(),
        data_config=request.data.model_dump(exclude_none=True),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    config = BacktestConfig(
        initial_capital=request.initial_capital,
        position_size_pct=request.position_size_pct,
        allow_reverse=request.allow_reverse,
        friction=request.friction,
        sessions=request.sessions,
        lookback_bars=request.lookback_bars,
        periods_per_year=request.periods_per_year,
        risk_free_rate=request.risk_free_rate,
        market=request.market,
    )
    try:
        engine_result = run_backtest(strategy, bars, config)
    except Exception as exc:  # persist the failure, then surface it
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        detail = f"backtest failed: {exc}"
        status_code = 400 if isinstance(exc, EngineError) else 500
        raise HTTPException(status_code=status_code, detail=detail)

    result = models.BacktestResult(
        backtest_run_id=run.id,
        metrics=engine_result.metrics,
        equity_curve=engine_result.equity_curve,
        trades=engine_result.trades,
        stats=engine_result.stats,
    )
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(result)
    db.commit()
    db.refresh(run)
    db.refresh(result)
    return _detail(run, result)


@app.get("/backtests/{run_id}", response_model=schemas.BacktestDetail)
def get_backtest(run_id: str, db: Session = Depends(get_db)) -> schemas.BacktestDetail:
    """Full persisted results for one run: metrics, equity curve, trades."""
    run = db.get(models.BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"backtest run '{run_id}' not found")
    result = (
        db.execute(
            select(models.BacktestResult)
            .where(models.BacktestResult.backtest_run_id == run.id)
            .order_by(models.BacktestResult.created_at.desc())
        )
        .scalars()
        .first()
    )
    return _detail(run, result)


@app.get("/backtests", response_model=list[schemas.BacktestSummary])
def list_backtests(
    strategy_key: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[schemas.BacktestSummary]:
    """List runs (newest first) with headline metrics, for comparison."""
    stmt = select(models.BacktestRun).order_by(models.BacktestRun.started_at.desc())
    if strategy_key is not None:
        stmt = stmt.where(models.BacktestRun.strategy_key == strategy_key)
    if symbol is not None:
        stmt = stmt.where(models.BacktestRun.symbol == symbol)
    if status is not None:
        stmt = stmt.where(models.BacktestRun.status == status)
    runs = db.execute(stmt.limit(limit)).scalars().all()
    run_ids = [r.id for r in runs]
    metrics_by_run: dict[str, dict] = {}
    if run_ids:
        for row in (
            db.execute(
                select(models.BacktestResult)
                .where(models.BacktestResult.backtest_run_id.in_(run_ids))
                .order_by(models.BacktestResult.created_at.asc())
            ).scalars()
        ):
            metrics_by_run[row.backtest_run_id] = row.metrics  # newest wins
    return [_summary(run, metrics_by_run.get(run.id)) for run in runs]
