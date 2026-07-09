"""backtester service - Fase 1 skeleton (sin logica de negocio).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): Simula estrategias contra historico con spread/slippage/comision/latencia
"""

from fastapi import FastAPI

SERVICE_NAME = "backtester"

app = FastAPI(title="backtester", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic.

    Fase 1: no dependency checks wired yet (no business logic per
    docs/ARCHITECTURE.md section 11); this always reports ready.
    """
    return {"status": "ready", "service": SERVICE_NAME}
