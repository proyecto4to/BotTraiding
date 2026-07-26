"""broker-connectors service - Fase 3 (conectores de broker/exchange).

Responsabilidad (docs/ARCHITECTURE.md seccion 3): Adaptadores por
broker/exchange implementando el contrato `BrokerConnector` compartido.
Sin logica de estrategia/riesgo/ejecucion real - solo conectar, colocar
ordenes vía el conector, consultar posiciones/cuenta/historico y exponer
el registry por HTTP para que otros servicios (execution-engine,
backtester) lo consuman.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from trading_contracts.models import AccountState, Bar, ExecutionReport, Order, Position

from .connectors.errors import (
    ConnectorRateLimitError,
    OrderNotFoundError,
    OrderRejectedError,
    UnsupportedTimeframeError,
)
from .connectors.http_base import BrokerConfig
from .credential_store import (
    BrokerCredentials,
    CredentialKeyError,
    EncryptedDbCredentialStore,
    build_credential_store,
)
from .deps import require_admin, require_caller
from .registry import CONNECTOR_CLASSES, registry

SERVICE_NAME = "broker-connectors"

app = FastAPI(title="broker-connectors", version="0.1.0")

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

# Credential store selected by CREDENTIAL_STORE (default in-memory; "db"
# uses Fernet-encrypted rows and requires BROKER_CRED_KEY). Secrets are never
# returned or logged regardless of backend (see BrokerCredentials.__repr__).
credential_store = build_credential_store()


class ConnectRequest(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    demo: bool = True
    account_id: str = "default"


class ConnectResponse(BaseModel):
    broker: str
    account_id: str
    connected: bool
    demo: bool


class StatusResponse(BaseModel):
    broker: str
    account_id: str
    connected: bool


class PlaceOrderRequest(BaseModel):
    id: UUID
    signal_id: UUID
    symbol: str
    side: str
    quantity: float
    order_type: str
    price: Optional[float] = None
    account_id: str = "default"
    execution_mode: str = "paper"


class CancelOrderRequest(BaseModel):
    account_id: str = "default"


class CancelOrderResponse(BaseModel):
    broker: str
    account_id: str
    order_id: str
    cancelled: bool


# Typed connector errors -> meaningful HTTP statuses (instead of a blanket
# 500) so trading-engine can distinguish "order rejected by exchange filters"
# from "broker throttling us".
_CONNECTOR_ERROR_STATUS: list[tuple[type[Exception], int]] = [
    (ConnectorRateLimitError, 429),
    (OrderNotFoundError, 404),
    (UnsupportedTimeframeError, 422),
    (OrderRejectedError, 422),
]


def _register_connector_error_handlers() -> None:
    for error_cls, status_code in _CONNECTOR_ERROR_STATUS:
        def handler(
            request: Request, exc: Exception, status_code: int = status_code
        ) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})

        app.add_exception_handler(error_cls, handler)


_register_connector_error_handlers()


def _require_known_broker(broker: str) -> None:
    if broker not in CONNECTOR_CLASSES:
        raise HTTPException(status_code=404, detail=f"unknown broker '{broker}'")


def _require_connected(broker: str, account_id: str = "default"):
    connector = registry.get(broker, account_id)
    if connector is None or not connector.is_connected():
        raise HTTPException(
            status_code=409,
            detail=(
                f"{broker}/{account_id} is not connected; "
                f"call /connectors/{broker}/connect first"
            ),
        )
    return connector


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe: the service is ready to receive traffic."""
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/connectors")
def list_connectors() -> dict:
    """List brokers with a registered connector implementation."""
    return {"brokers": registry.available_brokers()}


class RotateKeyRequest(BaseModel):
    new_key: str


class RotateKeyResponse(BaseModel):
    rotated: int


@app.post("/connectors/credentials/rotate", response_model=RotateKeyResponse)
def rotate_credentials(
    body: RotateKeyRequest, _admin=Depends(require_admin)
) -> RotateKeyResponse:
    """Re-encrypt all stored broker credentials under a new key (admin only).

    Operational action: provide a freshly generated Fernet key; every row is
    re-encrypted and the old key can no longer decrypt them. Only valid with
    CREDENTIAL_STORE=db."""
    if not isinstance(credential_store, EncryptedDbCredentialStore):
        raise HTTPException(
            status_code=400,
            detail="credential rotation requires CREDENTIAL_STORE=db",
        )
    try:
        rotated = credential_store.rotate(body.new_key)
    except CredentialKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RotateKeyResponse(rotated=rotated)


@app.post("/connectors/{broker}/connect", response_model=ConnectResponse)
async def connect(
    broker: str, body: ConnectRequest, _caller=Depends(require_caller)
) -> ConnectResponse:
    _require_known_broker(broker)

    credentials = BrokerCredentials(
        broker=broker,
        account_id=body.account_id,
        api_key=body.api_key,
        api_secret=body.api_secret,
        demo=body.demo,
    )
    credential_store.save(credentials)  # never returned/logged, see BrokerCredentials.__repr__

    config = BrokerConfig(
        broker=broker,
        api_key=body.api_key,
        api_secret=body.api_secret,
        demo=body.demo,
        account_id=body.account_id,
    )
    connector = registry.get_or_create(broker, config)
    try:
        await connector.connect()
    except Exception as exc:  # noqa: BLE001 - surfaced as a generic upstream failure
        raise HTTPException(status_code=502, detail=f"could not connect to {broker}") from exc

    # P3: share the session state so other replicas can serve this session.
    registry.mark_connected(broker, body.account_id, connector.is_connected())

    return ConnectResponse(
        broker=broker, account_id=body.account_id,
        connected=connector.is_connected(), demo=body.demo,
    )


@app.get("/connectors/{broker}/status", response_model=StatusResponse)
def status(broker: str, account_id: str = "default") -> StatusResponse:
    _require_known_broker(broker)
    connector = registry.get(broker, account_id)
    return StatusResponse(
        broker=broker, account_id=account_id, connected=bool(connector and connector.is_connected())
    )


@app.get("/connectors/{broker}/positions", response_model=list[Position])
async def get_positions(broker: str, account_id: str = "default") -> list[Position]:
    _require_known_broker(broker)
    connector = _require_connected(broker, account_id)
    return await connector.get_positions()


@app.get("/connectors/{broker}/account", response_model=AccountState)
async def get_account(broker: str, account_id: str = "default") -> AccountState:
    _require_known_broker(broker)
    connector = _require_connected(broker, account_id)
    return await connector.get_account_state()


@app.get("/connectors/{broker}/historical", response_model=list[Bar])
async def get_historical(
    broker: str,
    symbol: str,
    timeframe: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
    account_id: str = "default",
) -> list[Bar]:
    """Historical bars for trading-engine.

    Two request shapes (existing ``start``+``end`` contract is unchanged):
    * ``start`` + ``end``: explicit range (all connectors).
    * ``limit``: last N bars, for connectors exposing ``get_recent_bars``
      (binance today).
    """
    _require_known_broker(broker)
    connector = _require_connected(broker, account_id)
    if start is not None and end is not None:
        return await connector.get_historical_data(symbol, timeframe, start, end)
    if limit is not None:
        if not hasattr(connector, "get_recent_bars"):
            raise HTTPException(
                status_code=422,
                detail=f"{broker} does not support limit-based history; pass start and end",
            )
        return await connector.get_recent_bars(symbol, timeframe, limit)
    raise HTTPException(status_code=422, detail="provide either start and end, or limit")


class StreamStatusResponse(BaseModel):
    broker: str
    account_id: str
    connected: bool
    streaming: bool
    streams: list[str] = []


@app.get("/connectors/{broker}/stream/status", response_model=StreamStatusResponse)
def stream_status(broker: str, account_id: str = "default") -> StreamStatusResponse:
    """Which websocket market-data streams (if any) this connector has open."""
    _require_known_broker(broker)
    connector = registry.get(broker, account_id)
    streams = list(getattr(connector, "active_streams", []) or []) if connector else []
    return StreamStatusResponse(
        broker=broker,
        account_id=account_id,
        connected=bool(connector and connector.is_connected()),
        streaming=bool(streams),
        streams=streams,
    )


@app.post("/connectors/{broker}/orders", response_model=ExecutionReport)
async def place_order(
    broker: str, body: PlaceOrderRequest, _caller=Depends(require_caller)
) -> ExecutionReport:
    _require_known_broker(broker)
    connector = _require_connected(broker, body.account_id)
    order = Order(
        id=body.id,
        signal_id=body.signal_id,
        symbol=body.symbol,
        side=body.side,
        quantity=body.quantity,
        order_type=body.order_type,
        price=body.price,
        broker=broker,
        account_id=body.account_id,
        execution_mode=body.execution_mode,
        created_at=datetime.utcnow(),
    )
    return await connector.place_order(order)


@app.post("/connectors/{broker}/orders/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(
    broker: str,
    order_id: str,
    body: Optional[CancelOrderRequest] = None,
    _caller=Depends(require_caller),
) -> CancelOrderResponse:
    """Cancel an order previously placed through this connector.

    execution-engine's LiveTransport POSTs this exact path with
    {"account_id": ...}; the body is optional so manual calls work too.
    """
    _require_known_broker(broker)
    account_id = body.account_id if body is not None else "default"
    connector = _require_connected(broker, account_id)
    try:
        await connector.cancel_order(order_id)
    except Exception as exc:  # noqa: BLE001 - surfaced as a generic upstream failure
        raise HTTPException(
            status_code=502, detail=f"could not cancel order '{order_id}' at {broker}"
        ) from exc
    return CancelOrderResponse(
        broker=broker, account_id=account_id, order_id=order_id, cancelled=True
    )
