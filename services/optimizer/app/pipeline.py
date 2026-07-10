"""Optimization/promotion pipeline (Fase 12).

candidates (search.py, bounds from the strategy's own schema)
  -> walk-forward validation vs current params (validation.py, backtests
     via the injectable BacktesterClient)
  -> persist every evaluation (optimization_results) + the decision
     (optimization_runs.decision)
  -> gate passed: promotion RECOMMENDED (event optimizer.promotion.recommended)
  -> gate passed AND caller sent promote=true: params applied to
     strategy-engine via the injectable StrategyEngineClient, logged
     prominently and persisted (applied=True, event optimizer.params.applied).

Un cambio de parametros NUNCA se aplica sin validacion out-of-sample
(docs/ARCHITECTURE.md seccion 10 / Fase 12).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trading_strategies import UnknownStrategyError, load_builtin_strategies, registry

from . import events
from .clients import get_backtester, get_strategy_engine
from .models import OptimizationResultRecord, OptimizationRunRecord
from .schemas import OptimizeRequest
from .search import generate_candidates
from .validation import WalkForwardReport, walk_forward_validate, walk_forward_windows

logger = logging.getLogger("optimizer.pipeline")

load_builtin_strategies()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_run(db: Session, request: OptimizeRequest) -> OptimizationRunRecord:
    """Validate the request against the registry and persist a pending run."""
    try:
        cls = registry.get(request.strategy_key)
    except UnknownStrategyError:
        raise ValueError(f"unknown strategy '{request.strategy_key}'")

    baseline = cls.validate_params(request.current_params)  # raises on bad params
    run = OptimizationRunRecord(
        strategy_key=request.strategy_key,
        strategy_version=cls.version,
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=request.start.replace(tzinfo=None),
        end_date=request.end.replace(tzinfo=None),
        search_type=request.search_type,
        budget=request.budget,
        status="pending",
        search_space=cls().parameters,
        baseline_params=baseline,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def execute_run(db: Session, run_id: str, request: OptimizeRequest) -> None:
    """Run the full pipeline for a persisted run (sync or background)."""
    run = db.get(OptimizationRunRecord, run_id)
    if run is None:
        raise ValueError(f"unknown optimization run '{run_id}'")
    run.status = "running"
    db.commit()

    try:
        cls = registry.get(run.strategy_key)
        candidates = generate_candidates(
            cls, request.search_type, request.budget, request.seed
        )
        if not candidates:
            raise ValueError("search produced no valid candidates")
        windows = walk_forward_windows(
            request.start, request.end, request.n_windows, request.is_fraction
        )
        report = await walk_forward_validate(
            client=get_backtester(),
            strategy_key=run.strategy_key,
            candidates=candidates,
            baseline_params=run.baseline_params,
            symbol=run.symbol,
            timeframe=run.timeframe,
            windows=windows,
            initial_capital=request.initial_capital,
            frictions=request.frictions,
        )
        await _finalize(db, run, request, report)
    except Exception as exc:  # noqa: BLE001 - persist the failure
        logger.exception("optimization run %s failed", run_id)
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = _utcnow()
        db.commit()


async def _finalize(
    db: Session,
    run: OptimizationRunRecord,
    request: OptimizeRequest,
    report: WalkForwardReport,
) -> None:
    for ev in report.evaluations:
        db.add(
            OptimizationResultRecord(
                optimization_run_id=run.id,
                parameters=ev["parameters"],
                metrics=ev["metrics"],
                out_of_sample=ev["out_of_sample"],
                window_index=ev["window_index"],
                role=ev["role"],
            )
        )

    decision = report.decision
    run.best_params = report.recommended_params
    run.decision = decision.model_dump()
    run.promoted = decision.promote
    run.status = "completed"
    run.finished_at = _utcnow()
    db.commit()

    if not decision.promote:
        logger.info(
            "run %s: promotion REJECTED for '%s' (%s)",
            run.id, run.strategy_key, "; ".join(decision.reasons),
        )
        return

    # gate passed -> a promotion is recommended (recommendation record =
    # the persisted run decision; consumers can also react to the event).
    await _publish(
        events.PROMOTION_RECOMMENDED_SUBJECT,
        {
            "run_id": run.id,
            "strategy_key": run.strategy_key,
            "params": report.recommended_params,
            "decision": decision.model_dump(),
        },
    )

    if not request.promote:
        logger.info(
            "run %s: gate passed for '%s' but promote=false; params NOT applied",
            run.id, run.strategy_key,
        )
        return

    # explicit promote=true AND validation passed -> apply, loudly.
    logger.warning(
        "PROMOTION: applying params to strategy-engine | run=%s strategy=%s "
        "params=%s | OOS sharpe %.4f vs baseline %.4f (threshold %.2f)",
        run.id,
        run.strategy_key,
        report.recommended_params,
        decision.candidate_oos_sharpe,
        decision.baseline_oos_sharpe,
        decision.threshold,
    )
    await get_strategy_engine().apply_params(
        run.strategy_key, report.recommended_params
    )
    run.applied = True
    db.commit()
    await _publish(
        events.PARAMS_APPLIED_SUBJECT,
        {
            "run_id": run.id,
            "strategy_key": run.strategy_key,
            "params": report.recommended_params,
        },
    )


async def _publish(subject: str, payload: dict) -> None:
    try:
        await events.get_publisher().publish(subject, payload)
    except Exception:  # noqa: BLE001 - events must never break the pipeline
        logger.exception("failed to publish %s", subject)
