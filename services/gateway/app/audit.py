"""Gateway audit hook: one structured-JSON line to stdout per request.

Every /api/* (proxied) and /config/* (gateway-local) request is logged with
method, path, user (token `sub` if a valid bearer token is present), response
status, duration and client IP. This is the lightweight edge log required by
ARCHITECTURE.md section 8 ("todo endpoint del gateway pasa por middleware de
auditoria"); the full persistent audit trail stays in auth-service's
audit_log table.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from trading_contracts.auth import TokenError, decode_token

AUDITED_PREFIXES = ("/api/", "/config/", "/config")

logger = logging.getLogger("gateway.audit")
if not logger.handlers:  # avoid duplicate handlers on module reimport
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def _user_from_request(request: Request) -> str | None:
    """Best-effort extraction of the caller's user id; never raises."""
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        return decode_token(token).sub
    except TokenError:
        return None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith(AUDITED_PREFIXES):
            return await call_next(request)

        started = time.monotonic()
        response = await call_next(request)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "gateway.request",
            "method": request.method,
            "path": path,
            "user": _user_from_request(request),
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "client_ip": request.client.host if request.client else None,
        }
        logger.info(json.dumps(entry, separators=(",", ":")))
        return response
