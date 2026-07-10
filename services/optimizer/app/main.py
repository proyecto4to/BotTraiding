"""optimizer service (Fase 12).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): busqueda de parametros
+ validacion out-of-sample antes de promover cambios. Un cambio de
parametros SOLO se promueve si supera la validacion walk-forward fuera
de muestra contra los parametros actuales (seccion 10 / Fase 12).

Endpoints: POST /optimize, GET /optimize/{id}, GET /optimize?strategy_key=.
Backtests run through the injectable BacktesterClient (backtester REST
API); promoted params are applied through the injectable
StrategyEngineClient - never silently. Schema: own Alembic migration
(version table "alembic_version_optimizer"), applied by
docker-entrypoint.sh before uvicorn starts.
"""

from __future__ import annotations

from fastapi import FastAPI

from trading_strategies import load_builtin_strategies

from .api import router

SERVICE_NAME = "optimizer"

#: candidate search reads parameter schemas from the shared registry.
_registry = load_builtin_strategies()

app = FastAPI(title=SERVICE_NAME, version="0.2.0")
app.include_router(router)


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: strategy registry loaded, ready for traffic."""
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "strategies_loaded": len(_registry),
    }
