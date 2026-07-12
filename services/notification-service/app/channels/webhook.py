"""Webhook channel: POST the notification as JSON to the user-configured URL,
HMAC-SHA256 signed so the receiver can authenticate the sender.

Signature: header `X-Notification-Signature: sha256=<hexdigest>` computed over
the exact request body with the user's webhook_secret, falling back to env
WEBHOOK_SIGNING_DEFAULT_SECRET.

Tests inject an httpx.MockTransport via the constructor.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app import config
from app.channels import PermanentSendError, TransientSendError

_TIMEOUT = 10.0

SIGNATURE_HEADER = "X-Notification-Signature"


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class WebhookSender:
    name = "webhook"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def send(self, notification: dict, preference) -> None:
        url = getattr(preference, "webhook_url", None)
        if not url:
            raise PermanentSendError("user has no webhook_url configured")
        secret = getattr(preference, "webhook_secret", None) or config.webhook_default_secret()

        body = json.dumps(notification, default=str, sort_keys=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(secret, body),
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT
            ) as client:
                response = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise TransientSendError(f"webhook request failed: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientSendError(f"webhook returned {response.status_code}")
        if response.status_code >= 400:
            raise PermanentSendError(
                f"webhook rejected the delivery ({response.status_code})"
            )
