"""scheduler service (Fase 12).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): cron de reentrenamiento,
reoptimizacion y jobs periodicos. Job definitions are env-config (see
app/config.py for the SCHEDULER_JOBS format); downstream calls go through
injectable httpx clients (app/clients.py). The scheduler only TRIGGERS
work - it never promotes parameters and holds no trading logic.

Endpoints: GET /jobs (definitions + next/last run), POST /jobs/{id}/trigger
(manual run, admin-only via trading_contracts.auth JWT roles).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from trading_contracts.auth import TokenPayload

from .config import JobDefinition
from .deps import require_admin
from .jobs import last_runs, run_job
from .runtime import autostart_enabled, next_run_time, runtime

SERVICE_NAME = "scheduler"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.load()
    if autostart_enabled():
        runtime.start()
    else:
        logger.info("SCHEDULER_AUTOSTART=false; cron clock not started")
    yield
    runtime.shutdown()


app = FastAPI(title=SERVICE_NAME, version="0.2.0", lifespan=lifespan)

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


class JobOut(BaseModel):
    id: str
    type: str
    cron: str
    enabled: bool
    params: dict[str, Any] = Field(default_factory=dict)
    next_run_time: Optional[datetime] = None
    last_run: Optional[dict[str, Any]] = None


class TriggerResponse(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)


def _job_out(job: JobDefinition) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        cron=job.cron,
        enabled=job.enabled,
        params=job.params,
        next_run_time=next_run_time(job),
        last_run=last_runs.get(job.id),
    )


@app.get("/jobs", response_model=list[JobOut])
def list_jobs() -> list[JobOut]:
    """Configured jobs with their next scheduled run and last outcome."""
    return [_job_out(job) for job in runtime.jobs]


@app.post("/jobs/{job_id}/trigger", response_model=TriggerResponse)
async def trigger_job(
    job_id: str, admin: TokenPayload = Depends(require_admin)
) -> TriggerResponse:
    """Run a job immediately (admin-only), outside its cron schedule."""
    job = runtime.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job '{job_id}'")
    logger.info("manual trigger of '%s' by user %s", job_id, admin.sub)
    try:
        outcome = await run_job(job)
    except Exception as exc:  # noqa: BLE001 - surface the failure to the caller
        raise HTTPException(status_code=502, detail=f"job '{job_id}' failed: {exc}")
    return TriggerResponse(
        job_id=job_id, status=outcome["status"], result=outcome.get("result", {})
    )


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: job registry loaded (clock state reported)."""
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "jobs_loaded": len(runtime.jobs),
        "clock_running": runtime.running,
    }
