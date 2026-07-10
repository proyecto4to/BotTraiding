"""ai-engine service (Fase 11).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): regimen de mercado,
ranking/seleccion de estrategias, deteccion de anomalias y recomendaciones
de deshabilitacion. La IA no sustituye las reglas de trading: este
servicio NUNCA emite TradeSignals ni deshabilita estrategias - produce
datos/eventos advisory que otros servicios consumen.

Endpoints: POST /ai/regime, POST /ai/regime/refresh, POST /ai/select,
POST /ai/anomalies, POST /ai/underperformance, GET /ai/recommendations.
Schema: own Alembic migration (version table "alembic_version_ai"),
applied by docker-entrypoint.sh before uvicorn starts.
"""

from __future__ import annotations

from fastapi import FastAPI

from trading_strategies import load_builtin_strategies

from .api import router

SERVICE_NAME = "ai-engine"

#: the selector reads category/timeframe metadata from the shared registry.
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
