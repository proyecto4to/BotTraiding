from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.connectors.http_base import BrokerConfig
from app.main import app
from app.registry import registry

from .conftest import default_handler, make_mock_client

client = TestClient(app)


def _seed_connected_connector(broker: str = "binance", account_id: str = "default"):
    config = BrokerConfig(broker=broker, demo=True, account_id=account_id)
    return registry.get_or_create(broker, config, client=make_mock_client(default_handler))


def test_list_connectors_includes_all_brokers():
    response = client.get("/connectors")
    assert response.status_code == 200
    brokers = response.json()["brokers"]
    assert len(brokers) == 8
    assert "binance" in brokers
    assert "metatrader5" in brokers


def test_connect_unknown_broker_returns_404():
    response = client.post("/connectors/notabroker/connect", json={"api_key": "x"})
    assert response.status_code == 404


def test_positions_without_connect_returns_409():
    response = client.get("/connectors/binance/positions")
    assert response.status_code == 409


def test_status_reports_not_connected_when_never_connected():
    response = client.get("/connectors/binance/status")
    assert response.status_code == 200
    assert response.json()["connected"] is False


def test_connect_then_read_positions_account_and_historical():
    _seed_connected_connector("binance")

    connect_resp = client.post(
        "/connectors/binance/connect",
        json={"api_key": "secret-key", "api_secret": "secret-value", "demo": True},
    )
    assert connect_resp.status_code == 200
    body = connect_resp.json()
    assert body["connected"] is True
    # Credentials must never come back in the response.
    assert "secret-key" not in connect_resp.text
    assert "secret-value" not in connect_resp.text

    status_resp = client.get("/connectors/binance/status")
    assert status_resp.json()["connected"] is True

    positions_resp = client.get("/connectors/binance/positions")
    assert positions_resp.status_code == 200
    assert positions_resp.json()[0]["symbol"] == "BTCUSD"

    account_resp = client.get("/connectors/binance/account")
    assert account_resp.status_code == 200
    assert account_resp.json()["balance"] == 1000.0

    start = (datetime.utcnow() - timedelta(days=1)).isoformat()
    end = datetime.utcnow().isoformat()
    hist_resp = client.get(
        "/connectors/binance/historical",
        params={"symbol": "BTCUSD", "timeframe": "1h", "start": start, "end": end},
    )
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) == 1


def test_place_order_via_api():
    _seed_connected_connector("binance")
    client.post(
        "/connectors/binance/connect",
        json={"api_key": "k", "api_secret": "s", "demo": True},
    )

    order_resp = client.post(
        "/connectors/binance/orders",
        json={
            "id": str(uuid4()),
            "signal_id": str(uuid4()),
            "symbol": "BTCUSD",
            "side": "buy",
            "quantity": 1.0,
            "order_type": "market",
            "account_id": "default",
            "execution_mode": "paper",
        },
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["filled_quantity"] == 1.0
