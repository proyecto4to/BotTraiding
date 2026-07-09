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

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from trading_contracts.models import AccountState, Bar, ExecutionReport, Order, Position

from .connectors.http_base import BrokerConfig
from .credential_store import BrokerCredentials, InMemoryCredentialStore
from .registry import CONNECTOR_CLASSES, registry

SERVICE_NAME = "broker-connectors"

app = FastAPI(title="broker-connectors", version="0.1.0")

# Fase 3: in-memory credential store. Swap for a Vault/KMS-backed
# CredentialStore implementation later without touching the endpoints below.
credential_store = InMemoryCredentialStore()


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


def _require_known_broker(broker: str) -> None:
    if broker not in CONNECTOR_CLASSES:
        raise HTTPException(status_code=404, detail=f"unknown broker '{broker}'")


def _require_connected(broker: str, account_id: str = "default"):
    connector = registry.get(broker, account_id)
    if connector is None or not connector.is_connected():
        raise HTTPException(
            status_code=409,
            detail=f"{broker}/{account_id} is not connected; call /connectors/{broker}/connect first",
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


@app.post("/connectors/{broker}/connect", response_model=ConnectResponse)
async def connect(broker: str, body: ConnectRequest) -> ConnectResponse:
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

    return ConnectResponse(
        broker=broker, account_id=body.account_id, connected=connector.is_connected(), demo=body.demo
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
    broker: str, symbol: str, timeframe: str, start: datetime, end: datetime, account_id: str = "default"
) -> list[Bar]:
    _require_known_broker(broker)
    connector = _require_connected(broker, account_id)
    return await connector.get_historical_data(symbol, timeframe, start, end)


@app.post("/connectors/{broker}/orders", response_model=ExecutionReport)
async def place_order(broker: str, body: PlaceOrderRequest) -> ExecutionReport:
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
