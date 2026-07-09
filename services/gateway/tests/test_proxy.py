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

    for segment, (_env, default) in UPSTREAMS.items():
        respx.get(f"{default}/{segment}/ping").mock(
            return_value=httpx.Response(200, json={"pong": segment})
        )
    for segment in UPSTREAMS:
        response = client.get(f"/api/{segment}/ping", headers=auth_headers())
        assert response.status_code == 200, segment
        assert response.json() == {"pong": segment}
