"""notification-service service - Fase 1 skeleton (sin logica de negocio).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): Alertas (email/push/webhook) sobre eventos de riesgo, ejecucion, sistema
"""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

SERVICE_NAME = "notification-service"

app = FastAPI(title="notification-service", version="0.1.0")

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
    """Readiness probe: the service is ready to receive traffic.

    Fase 1: no dependency checks wired yet (no business logic per
    docs/ARCHITECTURE.md section 11); this always reports ready.
    """
    return {"status": "ready", "service": SERVICE_NAME}
