"""BFF session endpoints: the refresh token lives in an httpOnly cookie.

The property under test is that the refresh token never reaches JavaScript. It
goes upstream to auth-service and back into a cookie the browser cannot read, so
an XSS on the dashboard cannot lift it and mint access tokens indefinitely.
"""

from __future__ import annotations

import httpx
import respx
from app.session import CSRF_COOKIE, REFRESH_COOKIE
from fastapi.testclient import TestClient

AUTH = "http://auth-service:8000/auth"


def _token_pair() -> dict:
    return {
        "access_token": "access-abc",
        "refresh_token": "refresh-xyz",
        "token_type": "bearer",
    }


def _csrf_of(client_obj: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client_obj.cookies[CSRF_COOKIE]}


@respx.mock
def test_login_puts_the_refresh_token_in_a_cookie_not_the_body(client) -> None:
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))

    response = client.post("/api/session/login", json={"username": "u", "password": "p"})

    assert response.status_code == 200
    body = response.json()
    # The access token still comes back (it lives in memory, not storage)...
    assert body["access_token"] == "access-abc"
    # ...but the refresh token must not be in anything JS can read.
    assert "refresh_token" not in body

    set_cookie = response.headers.get("set-cookie", "")
    assert REFRESH_COOKIE in set_cookie
    assert "httponly" in set_cookie.lower()
    assert client.cookies[REFRESH_COOKIE] == "refresh-xyz"


@respx.mock
def test_refresh_cookie_is_scoped_to_the_session_endpoints(client) -> None:
    """Path-scoped so it is not attached to ordinary /api/* traffic."""
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))

    response = client.post("/api/session/login", json={"username": "u", "password": "p"})

    cookie_header = next(
        value
        for key, value in response.headers.items()
        if key.lower() == "set-cookie" and REFRESH_COOKIE in value
    )
    assert "Path=/api/session" in cookie_header


@respx.mock
def test_mfa_challenge_passes_through_without_a_cookie(client) -> None:
    """No tokens exist yet at the challenge step, so nothing is stored."""
    respx.post(f"{AUTH}/login").mock(
        return_value=httpx.Response(
            200, json={"mfa_required": True, "mfa_pending_token": "pending-1"}
        )
    )

    response = client.post("/api/session/login", json={"username": "u", "password": "p"})

    assert response.json()["mfa_required"] is True
    assert REFRESH_COOKIE not in client.cookies


@respx.mock
def test_refresh_reads_the_cookie_and_sends_no_token_in_the_body(client) -> None:
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    route = respx.post(f"{AUTH}/refresh").mock(
        return_value=httpx.Response(
            200, json={"access_token": "access-2", "refresh_token": "refresh-2"}
        )
    )
    response = client.post("/api/session/refresh", headers=_csrf_of(client))

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-2"
    assert "refresh_token" not in response.json()
    # The gateway supplied the token from the cookie, not the caller.
    assert b"refresh-xyz" in route.calls.last.request.content
    # Rotation lands in the cookie.
    assert client.cookies[REFRESH_COOKIE] == "refresh-2"


@respx.mock
def test_refresh_keeps_the_same_csrf_token(client) -> None:
    """Rotating it would invalidate the value any in-flight request is already
    carrying, turning a routine refresh into a spurious 403."""
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})
    csrf_at_login = client.cookies[CSRF_COOKIE]

    respx.post(f"{AUTH}/refresh").mock(
        return_value=httpx.Response(
            200, json={"access_token": "access-2", "refresh_token": "refresh-2"}
        )
    )
    client.post("/api/session/refresh", headers={"X-CSRF-Token": csrf_at_login})

    assert client.cookies[CSRF_COOKIE] == csrf_at_login
    # ...and the token still works for the next call (e.g. logout).
    respx.post(f"{AUTH}/logout").mock(return_value=httpx.Response(204))
    assert (
        client.post(
            "/api/session/logout", headers={"X-CSRF-Token": csrf_at_login}
        ).status_code
        == 204
    )


@respx.mock
def test_refresh_without_the_csrf_header_is_rejected(client) -> None:
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    response = client.post("/api/session/refresh")
    assert response.status_code == 403


@respx.mock
def test_refresh_with_a_mismatched_csrf_header_is_rejected(client) -> None:
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    response = client.post(
        "/api/session/refresh", headers={"X-CSRF-Token": "not-the-cookie-value"}
    )
    assert response.status_code == 403


def test_refresh_without_a_session_is_unauthorized(client) -> None:
    client.cookies.set(CSRF_COOKIE, "v")
    response = client.post("/api/session/refresh", headers={"X-CSRF-Token": "v"})
    assert response.status_code == 401


@respx.mock
def test_expired_session_clears_the_cookie(client) -> None:
    """A revoked refresh token must not leave the browser retrying forever."""
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    respx.post(f"{AUTH}/refresh").mock(
        return_value=httpx.Response(401, json={"detail": "revoked"})
    )
    response = client.post("/api/session/refresh", headers=_csrf_of(client))

    assert response.status_code == 401
    assert client.cookies.get(REFRESH_COOKIE) in (None, "")


@respx.mock
def test_logout_revokes_upstream_and_clears_cookies(client) -> None:
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    route = respx.post(f"{AUTH}/logout").mock(return_value=httpx.Response(204))
    response = client.post("/api/session/logout", headers=_csrf_of(client))

    assert response.status_code == 204
    assert b"refresh-xyz" in route.calls.last.request.content
    assert client.cookies.get(REFRESH_COOKIE) in (None, "")


@respx.mock
def test_logout_clears_the_session_even_if_auth_service_is_down(client) -> None:
    """Asking to log out must log you out locally no matter what upstream does."""
    respx.post(f"{AUTH}/login").mock(return_value=httpx.Response(200, json=_token_pair()))
    client.post("/api/session/login", json={"username": "u", "password": "p"})

    respx.post(f"{AUTH}/logout").mock(side_effect=httpx.ConnectError("down"))
    response = client.post("/api/session/logout", headers=_csrf_of(client))

    assert response.status_code == 204
    assert client.cookies.get(REFRESH_COOKIE) in (None, "")


@respx.mock
def test_bad_credentials_surface_as_the_upstream_status(client) -> None:
    respx.post(f"{AUTH}/login").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid credentials"})
    )

    response = client.post("/api/session/login", json={"username": "u", "password": "bad"})

    assert response.status_code == 401
    assert REFRESH_COOKIE not in client.cookies
