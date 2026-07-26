"""Mutating account state requires an authenticated caller.

Ingest and mark drive cash, positions, realized PnL and peak equity — the same
numbers the risk limits and the paper->live promotion gate are measured against.
Leaving them open meant anything that could reach the port could quietly rewrite
an account's history, and therefore what the platform believes about its own
track record.

Reads stay open on purpose: they expose no secrets, and the loopback binding
keeps them off the network.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

ACC = "acc-auth"


def _execution_payload() -> dict:
    return {
        "order_id": str(uuid.uuid4()),
        "status": "filled",
        "filled_quantity": 1.0,
        "average_fill_price": 100.0,
        "broker": "sim",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "AAPL",
        "side": "buy",
    }


def test_ingest_without_a_token_is_rejected(anon_client):
    response = anon_client.post(f"/portfolio/{ACC}/executions", json=_execution_payload())
    assert response.status_code == 401


def test_mark_without_a_token_is_rejected(anon_client):
    response = anon_client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 110}})
    assert response.status_code == 401


def test_forged_token_is_rejected(anon_client):
    response = anon_client.post(
        f"/portfolio/{ACC}/executions",
        json=_execution_payload(),
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_rejected_ingest_leaves_no_trace(anon_client, client):
    """The point of the gate: an unauthenticated write must not land."""
    anon_client.post(f"/portfolio/{ACC}/executions", json=_execution_payload())

    state = client.get(f"/portfolio/{ACC}").json()
    assert state["positions"] == []
    assert state["account"]["balance"] == 100000.0


def test_service_token_is_accepted(client):
    response = client.post(f"/portfolio/{ACC}/executions", json=_execution_payload())
    assert response.status_code == 200
    assert response.json()["applied"] is True


def test_reads_stay_open(anon_client):
    assert anon_client.get(f"/portfolio/{ACC}").status_code == 200
    assert anon_client.get(f"/portfolio/{ACC}/drawdown").status_code == 200
