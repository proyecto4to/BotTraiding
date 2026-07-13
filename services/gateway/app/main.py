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

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app import market_config, proxy
from app.audit import AuditMiddleware
from app.deps import get_token_payload, require_admin

SERVICE_NAME = "gateway"

# The master switch proxies to the autonomy-controller. The controller already
# returns {state, enabled, mode, recommendation}; the dashboard consumes
# {enabled, mode, recommendation}.
AUTONOMY_URL = os.environ.get("AUTONOMY_URL", "http://autonomy-controller:8000").rstrip("/")


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
# proxy.router (the /api/{segment} catch-all) is included LAST, at the end of
# this module, so specific gateway-owned routes like /api/automation/* are
# matched before the catch-all forwards them to an upstream.

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


def _automation_view(payload: dict) -> dict:
    """Project the controller's state onto the shape the dashboard reads."""
    return {
        "enabled": bool(payload.get("enabled", False)),
        "mode": payload.get("mode", "unknown"),
        "recommendation": payload.get("recommendation", ""),
    }


_AUTONOMY_DOWN = {
    "enabled": False,
    "mode": "unavailable",
    "recommendation": "Autonomy controller unavailable.",
}


@app.get("/api/automation/state")
async def automation_state(_user=Depends(get_token_payload)) -> dict:
    """Current master-switch state (any authenticated user can view)."""
    client = await proxy.get_http_client()
    try:
        resp = await client.get(f"{AUTONOMY_URL}/autonomy/state")
        resp.raise_for_status()
    except httpx.HTTPError:
        return _AUTONOMY_DOWN
    return _automation_view(resp.json())


@app.get("/api/automation/decisions")
async def automation_decisions(limit: int = 20, _user=Depends(get_token_payload)) -> list:
    """Recent autonomy decisions (regime, selection, actions) for the panel.

    Read-only; any authenticated user. Degrades to an empty list when the
    controller is unreachable so the panel renders an empty state."""
    client = await proxy.get_http_client()
    try:
        resp = await client.get(
            f"{AUTONOMY_URL}/autonomy/decisions", params={"limit": max(1, min(limit, 200))}
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return []
    return resp.json()


@app.post("/api/automation/toggle")
async def toggle_automation(request: Request, _admin=Depends(require_admin)) -> dict:
    """Flip the master switch: enable when off, disable when on (admin only).

    The caller's admin token is forwarded to the controller, which enforces the
    same admin requirement."""
    client = await proxy.get_http_client()
    headers = {"authorization": request.headers.get("authorization", "")}
    try:
        current = await client.get(f"{AUTONOMY_URL}/autonomy/state")
        current.raise_for_status()
        action = "disable" if current.json().get("enabled") else "enable"
        resp = await client.post(f"{AUTONOMY_URL}/autonomy/{action}", headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError:
        return _AUTONOMY_DOWN
    return _automation_view(resp.json())


# The reverse-proxy catch-all is registered last so specific gateway routes
# (config, automation) take precedence over /api/{segment} forwarding.
app.include_router(proxy.router)
