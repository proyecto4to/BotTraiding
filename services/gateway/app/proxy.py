"""Reverse proxy: the gateway is the single entry point for frontend/mobile
(ARCHITECTURE.md section 3 - clients never call an internal service directly).

Routing convention: /api/<segment>/<rest> forwards to the mapped upstream as
/<segment>/<rest> (e.g. /api/auth/login -> {AUTH_SERVICE_URL}/auth/login).
Auth endpoints (/api/auth/*) pass through unauthenticated so login/register/
refresh work; every other upstream requires a valid access token, verified
here with the shared DB-free helper. Verified identity is forwarded to
upstreams as X-User-Id / X-User-Roles headers.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.deps import payload_from_request
from app.rate_limit import get_rate_limiter

# segment -> (env var with upstream base URL, docker-compose-network default)
UPSTREAMS: dict[str, tuple[str, str]] = {
    "auth": ("AUTH_SERVICE_URL", "http://auth-service:8000"),
    "strategies": ("STRATEGY_ENGINE_URL", "http://strategy-engine:8000"),
    "risk": ("RISK_ENGINE_URL", "http://risk-engine:8000"),
    "portfolio": ("PORTFOLIO_ENGINE_URL", "http://portfolio-engine:8000"),
    "brokers": ("BROKER_CONNECTORS_URL", "http://broker-connectors:8000"),
    "backtests": ("BACKTESTER_URL", "http://backtester:8000"),
    "ai": ("AI_ENGINE_URL", "http://ai-engine:8000"),
    "executions": ("EXECUTION_ENGINE_URL", "http://execution-engine:8000"),
}

# Segments reachable without a JWT (login/register/refresh/oauth live here).
PUBLIC_SEGMENTS = {"auth"}

PROXY_TIMEOUT_SECONDS = float(os.environ.get("PROXY_TIMEOUT_SECONDS", "30"))

# Hop-by-hop headers must not be forwarded in either direction (RFC 2616 13.5.1).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_REQUEST_DROP = _HOP_BY_HOP | {"host", "content-length"}
# httpx transparently decodes the body, so length/encoding no longer match.
_RESPONSE_DROP = _HOP_BY_HOP | {"content-length", "content-encoding"}

router = APIRouter()

_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Lazily-created shared AsyncClient (closed from the app lifespan)."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS, follow_redirects=False)
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def upstream_base_url(segment: str) -> str:
    env_var, default = UPSTREAMS[segment]
    return os.environ.get(env_var, default).rstrip("/")


@router.api_route(
    "/api/{segment}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy(segment: str, path: str, request: Request) -> Response:
    if segment not in UPSTREAMS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown API route")

    payload = None
    if segment not in PUBLIC_SEGMENTS:
        payload = payload_from_request(request)  # raises 401

    client_ip = request.client.host if request.client else "unknown"
    rate_key = payload.sub if payload is not None else f"ip:{client_ip}"
    if not get_rate_limiter().allow(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": "1"},
        )

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _REQUEST_DROP
    }
    headers["x-forwarded-for"] = client_ip
    if payload is not None:
        headers["x-user-id"] = payload.sub
        headers["x-user-roles"] = ",".join(payload.roles)

    url = f"{upstream_base_url(segment)}/{segment}/{path}"
    body = await request.body()
    client = await get_http_client()
    try:
        upstream_response = await client.request(
            request.method,
            url,
            params=request.query_params,
            content=body,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream '{segment}' unavailable",
        ) from exc

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in _RESPONSE_DROP
    }
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
