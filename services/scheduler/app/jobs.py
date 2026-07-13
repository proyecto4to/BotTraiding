"""Job handlers + in-memory run tracking (Fase 12).

Each handler is an async function taking its JobDefinition and returning
a JSON-serializable result summary. Handlers only ever call downstream
services through the injectable clients - the scheduler holds NO trading
logic and NEVER promotes parameters itself.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from . import clients
from .config import JobDefinition

logger = logging.getLogger("scheduler.jobs")

JobHandler = Callable[[JobDefinition], Awaitable[dict[str, Any]]]

#: last outcome per job id (in-memory; the scheduler is stateless by design).
last_runs: dict[str, dict[str, Any]] = {}


async def run_reoptimize(job: JobDefinition) -> dict[str, Any]:
    """One optimizer run per enabled strategy (never with promote=true)."""
    strategies = await clients.get_strategy_engine().list_enabled_strategies()
    triggered: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for strategy in strategies:
        key = strategy.get("key") or strategy.get("strategy_key")
        if not key:
            continue
        try:
            run = await clients.get_optimizer().trigger_optimization(key, job.params)
            triggered.append({"strategy_key": key, "run_id": run.get("id")})
        except Exception as exc:  # noqa: BLE001 - isolate per-strategy failures
            logger.warning("reoptimize trigger failed for '%s': %s", key, exc)
            errors.append({"strategy_key": key, "error": str(exc)})
    return {
        "strategies_seen": len(strategies),
        "triggered": triggered,
        "errors": errors,
    }


async def run_regime_refresh(job: JobDefinition) -> dict[str, Any]:
    response = await clients.get_ai_engine().refresh_regime(job.params)
    return {"response": response}


async def run_health_ping(job: JobDefinition) -> dict[str, Any]:
    targets = job.params.get("targets") or clients.health_ping_targets()
    statuses: dict[str, bool] = {}
    for name, url in targets.items():
        statuses[name] = await clients.get_health().ping(name, url)
    down = sorted(name for name, ok in statuses.items() if not ok)
    if down:
        logger.warning("health ping: services DOWN: %s", ", ".join(down))
    return {"statuses": statuses, "down": down}


async def run_autonomy_tick(job: JobDefinition) -> dict[str, Any]:
    """Drive one autonomy cycle. A no-op when the master switch is off, so it
    is safe to schedule frequently; it becomes active the moment the operator
    enables automation."""
    return {"tick": await clients.get_autonomy().tick()}


JOB_HANDLERS: dict[str, JobHandler] = {
    "reoptimize": run_reoptimize,
    "regime_refresh": run_regime_refresh,
    "health_ping": run_health_ping,
    "autonomy_tick": run_autonomy_tick,
}


async def run_job(job: JobDefinition) -> dict[str, Any]:
    """Execute a job now, recording its outcome for GET /jobs."""
    handler = JOB_HANDLERS[job.type]
    started = datetime.now(timezone.utc)
    try:
        result = await handler(job)
        outcome = {"at": started.isoformat(), "status": "ok", "result": result}
    except Exception as exc:  # noqa: BLE001 - record, then propagate
        outcome = {"at": started.isoformat(), "status": "error", "error": str(exc)}
        last_runs[job.id] = outcome
        raise
    last_runs[job.id] = outcome
    logger.info("job '%s' finished: %s", job.id, outcome["status"])
    return outcome
