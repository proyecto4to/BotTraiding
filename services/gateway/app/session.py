"""Session endpoints: the gateway holds the refresh token, the browser never does.

Backend-for-frontend pattern. Before this, the refresh token lived in
``localStorage``, which means any XSS on the dashboard could read it and mint
access tokens for as long as it stayed valid — a full, silent account takeover
that outlives the page it was stolen from.

Here the refresh token only ever exists in an httpOnly cookie that JavaScript
cannot read, scoped to ``/api/session`` so it is not even sent to the rest of
the API. The access token still goes to the browser in the response body and
lives in memory only: it is short-lived, and keeping it out of cookies is what
makes the *other* endpoints immune to CSRF by construction (they authenticate
with an ``Authorization`` header the browser never attaches on its own).

CSRF: the session endpoints are the only ones the browser authenticates
automatically, so they get two independent defences.

1. ``SameSite=Lax`` — a cross-site POST does not carry the cookie at all.
2. Double-submit token — ``tp_csrf`` is a readable cookie that the client must
   echo back in ``X-CSRF-Token``. An attacker's page can force a request but
   cannot read our cookie to forge the header (that is what the same-origin
   policy protects), so the two never match.

Neither is load-bearing alone; the value is that they fail independently.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.proxy import get_http_client, upstream_base_url
from app.rate_limit import get_rate_limiter

router = APIRouter(prefix="/api/session", tags=["session"])

REFRESH_COOKIE = "tp_refresh"
CSRF_COOKIE = "tp_csrf"
CSRF_HEADER = "x-csrf-token"

# Scoped to the session endpoints: the refresh token is not sent to /api/*
# calls that have no use for it, so it is exposed on as few requests as possible.
COOKIE_PATH = "/api/session"


def cookie_secure() -> bool:
    """Secure flag. MUST be true in production; defaults to false so the cookie
    works over plain http on localhost (browsers drop Secure cookies on http)."""
    return os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def cookie_samesite() -> str:
    """``lax`` suits same-site deployments (dashboard and gateway sharing a
    registrable domain, ports do not matter). A genuinely cross-site frontend
    needs ``none``, which browsers only honour together with Secure."""
    return os.environ.get("SESSION_COOKIE_SAMESITE", "lax").lower()


def refresh_max_age() -> int:
    days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    return days * 24 * 3600


def _auth_url(path: str) -> str:
    return f"{upstream_base_url('auth')}/auth/{path.lstrip('/')}"


def _set_session_cookies(
    response: Response, refresh_token: str, *, csrf_token: str | None = None
) -> None:
    """Store the rotated refresh token, and issue a CSRF token when starting a
    session.

    On refresh, `csrf_token` is the value the caller already holds and it is
    reissued unchanged. Rotating it here would invalidate the token any request
    already in flight is carrying, turning a routine refresh into a spurious
    403 — and the CSRF token gains nothing from rotation, since its only job is
    to be unreadable from another origin.
    """
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path=COOKIE_PATH,
        max_age=refresh_max_age(),
    )
    # Deliberately NOT httpOnly: the client has to read this one to echo it
    # back. It is not a credential — it only has to be unguessable by a
    # different origin, which the same-origin policy guarantees.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token or secrets.token_urlsafe(32),
        httponly=False,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path="/",
        max_age=refresh_max_age(),
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")


def _require_csrf(request: Request) -> None:
    """Double-submit check: the header must match the readable cookie."""
    cookie_value = request.cookies.get(CSRF_COOKIE)
    header_value = request.headers.get(CSRF_HEADER)
    if not cookie_value or not header_value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing"
        )
    if not secrets.compare_digest(cookie_value, header_value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch"
        )


def _rate_limit(request: Request) -> None:
    """Same per-IP throttle the /api/* proxy applies.

    These routes are gateway-owned, so they never pass through the proxy's
    catch-all and would otherwise be the only unthrottled path to a password
    check. auth-service has its own brute-force lock, but it keys on
    ``request.client.host`` — which behind the gateway is the gateway for every
    caller — so this is where per-client throttling actually happens.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not get_rate_limiter().allow(f"ip:{client_ip}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": "1"},
        )


async def _post_auth(path: str, payload: dict[str, Any]) -> tuple[int, Any]:
    client = await get_http_client()
    try:
        upstream = await client.post(_auth_url(path), json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="auth-service unavailable"
        ) from exc
    try:
        body = upstream.json() if upstream.content else None
    except ValueError:
        body = None
    return upstream.status_code, body


def _login_result(
    response: Response, status_code: int, body: Any, *, csrf_token: str | None = None
) -> Any:
    """Move the refresh token out of the payload and into the cookie.

    An MFA challenge carries no tokens yet, so it passes through untouched and
    the browser continues to the /login/mfa step."""
    if status_code >= 400 or not isinstance(body, dict):
        raise HTTPException(
            status_code=status_code,
            detail=(body or {}).get("detail", "login failed")
            if isinstance(body, dict)
            else "login failed",
        )

    refresh_token = body.pop("refresh_token", None)
    if refresh_token:
        _set_session_cookies(response, refresh_token, csrf_token=csrf_token)
    return body


async def _json_body(request: Request) -> dict[str, Any]:
    """Parse the body, turning malformed JSON into a 422 rather than a 500."""
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same 422
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid JSON body"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Expected a JSON object"
        )
    return payload


@router.post("/login")
async def login(request: Request, response: Response) -> Any:
    _rate_limit(request)
    payload = await _json_body(request)
    status_code, body = await _post_auth("login", payload)
    return _login_result(response, status_code, body)


@router.post("/login/mfa")
async def login_mfa(request: Request, response: Response) -> Any:
    _rate_limit(request)
    payload = await _json_body(request)
    status_code, body = await _post_auth("login/mfa", payload)
    return _login_result(response, status_code, body)


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> Any:
    """Rotate the session from the cookie alone; the body carries no token."""
    _rate_limit(request)
    _require_csrf(request)

    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No session cookie"
        )

    status_code, body = await _post_auth("refresh", {"refresh_token": refresh_token})
    if status_code >= 400:
        # Expired or revoked: drop the cookie so the browser stops retrying with
        # a token that will never work again. Returned rather than raised —
        # raising HTTPException builds a fresh response and would discard the
        # Set-Cookie headers that do the clearing.
        expired = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Session expired"}
        )
        _clear_session_cookies(expired)
        return expired

    # Keep the caller's CSRF token: rotating it would 403 any request already
    # in flight with the previous value.
    return _login_result(
        response, status_code, body, csrf_token=request.cookies.get(CSRF_COOKIE)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> Response:
    """Revoke the refresh token upstream and clear the cookies.

    The cookies are cleared even if auth-service is unreachable: a user asking
    to log out must end up logged out locally regardless."""
    _rate_limit(request)
    _require_csrf(request)

    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            await _post_auth("logout", {"refresh_token": refresh_token})
        except HTTPException:
            pass

    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
