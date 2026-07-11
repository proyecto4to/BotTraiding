"""gateway service - Fase 4: mercados configurables + capa API.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): AuthN/AuthZ, rate limiting,
enrutamiento API, agregacion para el frontend.

- /config/*      market/symbol configuration API (gateway-owned tables)
- /api/<svc>/*   httpx reverse proxy to internal services (single entry point)
- audit middleware: structured JSON log line per request to stdout
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app import market_config, proxy
from app.audit import AuditMiddleware

SERVICE_NAME = "gateway"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await proxy.close_http_client()


app = FastAPI(title="gateway", version="0.4.0", lifespan=lifespan)
app.add_middleware(AuditMiddleware)
app.include_router(market_config.router)
app.include_router(proxy.router)

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
