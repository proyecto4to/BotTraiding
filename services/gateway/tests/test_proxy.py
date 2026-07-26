"""Reverse proxy: JWT enforcement, auth pass-through, forwarding, 502s."""

from __future__ import annotations

import httpx
import respx

from tests.conftest import auth_headers


def test_proxy_requires_token(client) -> None:
    response = client.get("/api/strategies/list")
    assert response.status_code == 401


def test_proxy_rejects_invalid_token(client) -> None:
    response = client.get(
        "/api/strategies/list", headers={"Authorization": "Bearer garbage"}
    )
    assert response.status_code == 401


def test_unknown_segment_is_404(client) -> None:
    response = client.get("/api/nonexistent/thing", headers=auth_headers())
    assert response.status_code == 404


@respx.mock
def test_auth_passthrough_without_token(client) -> None:
    route = respx.post("http://auth-service:8000/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "abc", "token_type": "bearer"})
    )
    response = client.post(
        "/api/auth/login", json={"email": "a@b.c", "password": "pw"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "abc"
    assert route.called
    sent = route.calls.last.request
    assert b'"email"' in sent.content


@respx.mock
def test_authenticated_request_is_forwarded_with_identity_headers(client) -> None:
    route = respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[{"id": "s1"}])
    )
    response = client.get(
        "/api/strategies/list",
        headers=auth_headers(sub="user-42", roles=["trader", "viewer"]),
    )
    assert response.status_code == 200
    assert response.json() == [{"id": "s1"}]
    sent = route.calls.last.request
    assert sent.headers["x-user-id"] == "user-42"
    assert sent.headers["x-user-roles"] == "trader,viewer"
    assert "x-forwarded-for" in sent.headers


@respx.mock
def test_client_supplied_identity_headers_are_stripped_on_public_routes(client) -> None:
    """/api/auth/* verifies no token, so nothing overwrites the identity headers.
    They must be dropped from the incoming request, or a caller could simply
    declare itself admin to whatever upstream later decides to trust them."""
    route = respx.post("http://auth-service:8000/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "abc"})
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "a@b.c", "password": "pw"},
        headers={"X-User-Id": "somebody-else", "X-User-Roles": "admin"},
    )
    assert response.status_code == 200
    sent = route.calls.last.request
    assert "x-user-id" not in sent.headers
    assert "x-user-roles" not in sent.headers


@respx.mock
def test_client_cannot_override_identity_on_authenticated_routes(client) -> None:
    """On authenticated routes the spoofed values must lose to the token's."""
    route = respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[])
    )
    headers = auth_headers(sub="user-42", roles=["viewer"])
    headers.update({"X-User-Id": "attacker", "X-User-Roles": "admin"})
    response = client.get("/api/strategies/list", headers=headers)
    assert response.status_code == 200
    sent = route.calls.last.request
    assert sent.headers["x-user-id"] == "user-42"
    assert sent.headers["x-user-roles"] == "viewer"


@respx.mock
def test_query_params_and_method_forwarded(client) -> None:
    route = respx.delete("http://risk-engine:8000/risk/limits/abc").mock(
        return_value=httpx.Response(204)
    )
    response = client.delete(
        "/api/risk/limits/abc?force=true", headers=auth_headers(roles=["admin"])
    )
    assert response.status_code == 204
    assert route.calls.last.request.url.params["force"] == "true"


@respx.mock
def test_upstream_status_and_body_pass_through(client) -> None:
    respx.get("http://portfolio-engine:8000/portfolio/positions").mock(
        return_value=httpx.Response(404, json={"detail": "no positions"})
    )
    response = client.get("/api/portfolio/positions", headers=auth_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "no positions"}


@respx.mock
def test_upstream_connection_error_is_502(client) -> None:
    respx.get("http://backtester:8000/backtests/run-1").mock(
        side_effect=httpx.ConnectError("boom")
    )
    response = client.get("/api/backtests/run-1", headers=auth_headers())
    assert response.status_code == 502
    assert "backtests" in response.json()["detail"]


@respx.mock
def test_env_var_overrides_upstream_url(client, monkeypatch) -> None:
    monkeypatch.setenv("AI_ENGINE_URL", "http://ai-custom:9999")
    route = respx.get("http://ai-custom:9999/ai/models").mock(
        return_value=httpx.Response(200, json={"models": []})
    )
    response = client.get("/api/ai/models", headers=auth_headers())
    assert response.status_code == 200
    assert route.called


@respx.mock
def test_all_upstream_segments_are_routable(client) -> None:
    """Every mapped segment forwards to its docker-compose default host."""
    from app.proxy import UPSTREAMS

    for segment, (_env, default, prefix) in UPSTREAMS.items():
        upstream_path = f"{prefix}/ping" if prefix else "ping"
        respx.get(f"{default}/{upstream_path}").mock(
            return_value=httpx.Response(200, json={"pong": segment})
        )
    for segment in UPSTREAMS:
        response = client.get(f"/api/{segment}/ping", headers=auth_headers())
        assert response.status_code == 200, segment
        assert response.json() == {"pong": segment}


@respx.mock
def test_bare_segment_forwards_without_redirect(client) -> None:
    """GET /api/strategies (frontend list call, no trailing slash) must reach
    the upstream /strategies route directly - no 307 (fetch breaks on it)."""
    route = respx.get("http://strategy-engine:8000/strategies").mock(
        return_value=httpx.Response(200, json=[{"key": "sma"}])
    )
    response = client.get(
        "/api/strategies", headers=auth_headers(), follow_redirects=False
    )
    assert response.status_code == 200
    assert response.json() == [{"key": "sma"}]
    assert route.called


@respx.mock
def test_trailing_slash_is_normalised(client) -> None:
    """GET /api/executions/ (frontend executions list) forwards to
    /executions without the trailing slash (upstream would 307 otherwise)."""
    route = respx.get("http://execution-engine:8000/executions").mock(
        return_value=httpx.Response(200, json=[])
    )
    response = client.get(
        "/api/executions/",
        params={"account_id": "default"},
        headers=auth_headers(),
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert route.called
    assert route.calls.last.request.url.params["account_id"] == "default"


@respx.mock
def test_brokers_segment_maps_to_connectors_routes(client) -> None:
    """/api/brokers/connectors/* must reach broker-connectors' /connectors/*
    (the service has no /brokers prefix)."""
    list_route = respx.get("http://broker-connectors:8000/connectors").mock(
        return_value=httpx.Response(200, json={"brokers": ["binance"]})
    )
    status_route = respx.get(
        "http://broker-connectors:8000/connectors/binance/status"
    ).mock(return_value=httpx.Response(200, json={"connected": False}))

    response = client.get(
        "/api/brokers/connectors", headers=auth_headers(), follow_redirects=False
    )
    assert response.status_code == 200
    assert response.json() == {"brokers": ["binance"]}
    assert list_route.called

    response = client.get(
        "/api/brokers/connectors/binance/status", headers=auth_headers()
    )
    assert response.status_code == 200
    assert status_route.called


@respx.mock
def test_executions_modes_alias(client) -> None:
    """execution-engine exposes /modes at its root; the frontend calls
    /api/executions/modes."""
    route = respx.get("http://execution-engine:8000/modes").mock(
        return_value=httpx.Response(200, json={"default_mode": "paper"})
    )
    response = client.get("/api/executions/modes", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["default_mode"] == "paper"
    assert route.called
