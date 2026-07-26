"""/risk/validate requires an authenticated caller.

Validation is not a read: it persists risk_events and feeds the circuit
breaker's error/rejection counters. An anonymous caller could push the breaker
toward SOFT/HARD halt — stopping the platform from trading at all — or fill the
audit trail with decisions nobody asked for.
"""

from __future__ import annotations

import json

from .conftest import make_signal, make_state

ACC = "acc-auth"


def _validate_body() -> dict:
    """The same shape test_validate.py uses, so a failure here can only be
    about auth and never about the payload."""
    return json.loads(
        json.dumps(
            {
                "account_id": ACC,
                "signal": make_signal().model_dump(mode="json"),
                "portfolio_state": make_state(account_id=ACC).model_dump(mode="json"),
            }
        )
    )


def test_validate_without_a_token_is_rejected(anon_client):
    assert anon_client.post("/risk/validate", json=_validate_body()).status_code == 401


def test_validate_with_a_forged_token_is_rejected(anon_client):
    response = anon_client.post(
        "/risk/validate",
        json=_validate_body(),
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_validate_accepts_a_service_token(client):
    """trading-engine's identity is enough — it does not need to be an admin."""
    response = client.post("/risk/validate", json=_validate_body())
    assert response.status_code == 200
    assert "approved" in response.json()
