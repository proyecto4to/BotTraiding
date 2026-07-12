"""gateway service - Fase 4: mercados configurables + capa API.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): AuthN/AuthZ, rate limiting,
enrutamiento API, agregacion para el frontend.

- /config/*      market/symbol configuration API (gateway-owned tables)
- /api/<svc>/*   httpx reverse proxy to internal services (single entry point)
- audit middleware: structured JSON log line per request to stdout
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app import market_config, proxy
from app.audit import AuditMiddleware


class AutomationState:
    def __init__(self) -> None:
        self.enabled = False
        self.mode = "manual"
        self.recommendation = "Waiting for market data and recent performance."


AUTOMATION_STATE = AutomationState()

SERVICE_NAME = "gateway"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await proxy.close_http_client()


app = FastAPI(title="gateway", version="0.4.0", lifespan=lifespan)
app.add_middleware(AuditMiddleware)

# The browser-based dashboard runs on a different origin (localhost:3000)
# than the gateway; without CORS headers every fetch is blocked client-side
# and surfaces as "Gateway unreachable" (status 0).
_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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


@app.get("/api/automation/state")
def automation_state() -> dict:
    return {
        "enabled": AUTOMATION_STATE.enabled,
        "mode": AUTOMATION_STATE.mode,
        "recommendation": AUTOMATION_STATE.recommendation,
    }


@app.post("/api/automation/toggle")
def toggle_automation() -> dict:
    AUTOMATION_STATE.enabled = not AUTOMATION_STATE.enabled
    AUTOMATION_STATE.mode = "auto" if AUTOMATION_STATE.enabled else "manual"
    AUTOMATION_STATE.recommendation = (
        "Automation is active. Risk controls remain enforced."
        if AUTOMATION_STATE.enabled
        else "Automation is paused. You can re-enable it at any time."
    )
    return automation_state()
