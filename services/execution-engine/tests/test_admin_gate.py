"""Admin gate: overriding the env default execution mode requires role
admin; going live is explicit and audited (structured warning + event)."""

from __future__ import annotations

import logging

from tests.conftest import make_execution_payload, make_token


def test_live_without_token_401(harness):
    # Default mode is paper; a live order is an override.
    response = harness.client.post("/executions", json=make_execution_payload(mode="live"))
    assert response.status_code == 401
    assert harness.live.orders == []


def test_live_with_non_admin_token_403(harness, trader_headers):
    response = harness.client.post(
        "/executions", json=make_execution_payload(mode="live"), headers=trader_headers
    )
    assert response.status_code == 403
    assert harness.live.orders == []


def test_live_with_admin_token_allowed_and_audited(harness, admin_headers, caplog):
    with caplog.at_level(logging.WARNING, logger="execution-engine"):
        response = harness.client.post(
            "/executions", json=make_execution_payload(mode="live"), headers=admin_headers
        )
    assert response.status_code == 201
    assert len(harness.live.orders) == 1
    # Structured warning on every live execution.
    assert "live_execution" in caplog.text
    assert '"account_id": "acct-1"' in caplog.text
    # The admin actor is recorded on the execution.
    assert response.json()["requested_by"]


def test_paper_default_needs_no_token(harness):
    response = harness.client.post("/executions", json=make_execution_payload(mode="paper"))
    assert response.status_code == 201


def test_invalid_token_401(harness):
    response = harness.client.post(
        "/executions",
        json=make_execution_payload(mode="live"),
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_refresh_token_rejected_401(harness):
    headers = {"Authorization": f"Bearer {make_token(['admin'], token_type='refresh')}"}
    response = harness.client.post(
        "/executions", json=make_execution_payload(mode="live"), headers=headers
    )
    assert response.status_code == 401


def test_live_still_requires_admin_when_it_is_the_env_default(harness, monkeypatch):
    """Regression: the admin gate used to fire only when the requested mode
    DIFFERED from EXECUTION_MODE. Configuring EXECUTION_MODE=live therefore made
    the comparison false and let unauthenticated live orders through — the one
    configuration where the gate matters most. Live is admin-only, full stop."""
    monkeypatch.setenv("EXECUTION_MODE", "live")

    response = harness.client.post("/executions", json=make_execution_payload(mode="live"))
    assert response.status_code == 401
    assert harness.live.orders == []


def test_live_as_env_default_still_works_for_an_admin(harness, monkeypatch, admin_headers, caplog):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    with caplog.at_level(logging.WARNING, logger="execution-engine"):
        response = harness.client.post(
            "/executions", json=make_execution_payload(mode="live"), headers=admin_headers
        )
    assert response.status_code == 201
    assert len(harness.live.orders) == 1
    assert "live_execution" in caplog.text


def test_paper_is_an_override_when_live_is_the_default(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MODE", "live")
    response = harness.client.post("/executions", json=make_execution_payload(mode="paper"))
    assert response.status_code == 401
