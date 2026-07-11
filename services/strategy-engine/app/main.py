"""strategy-engine service (Fase 5/6).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): carga plugins de
estrategia, evalua condiciones y emite TradeSignal. Las estrategias solo
PROPONEN; el Risk Engine decide (principio 3).

Startup: discovers the shared trading_strategies registry (import time)
and syncs it into the DB (lifespan) - code registry is the source of
truth for code/metadata, the DB owns enable/disable state and per-user
configs.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from . import db as db_module
from .api import router
from .registry import registry
from .sync import sync_registry

SERVICE_NAME = "strategy-engine"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with db_module.SessionLocal() as session:
            count = sync_registry(session, registry)
        logger.info("startup sync complete: %d strategies", count)
    except Exception:  # noqa: BLE001
        # The service can still serve registry metadata from code; the
        # entrypoint runs `alembic upgrade head` before uvicorn, so this
        # normally only happens when Postgres is temporarily unavailable.
        logger.exception("startup registry->DB sync failed")
    yield


app = FastAPI(title=SERVICE_NAME, version="0.2.0", lifespan=lifespan)
app.include_router(router)

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
    """Readiness probe: registry loaded and ready to receive traffic."""
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "strategies_loaded": len(registry),
    }
