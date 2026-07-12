"""Telegram channel: Bot API sendMessage via httpx.

Env: TELEGRAM_BOT_TOKEN (bot credentials), TELEGRAM_API_BASE (test override).
Target chat comes from the user's preference row (telegram_chat_id).

Tests inject an httpx.MockTransport via the constructor.
"""

from __future__ import annotations

import httpx

from app import config
from app.channels import PermanentSendError, TransientSendError

_TIMEOUT = 10.0


class TelegramSender:
    name = "telegram"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def send(self, notification: dict, preference) -> None:
        token = config.telegram_bot_token()
        if not token:
            raise PermanentSendError("TELEGRAM_BOT_TOKEN is not configured")
        chat_id = getattr(preference, "telegram_chat_id", None)
        if not chat_id:
            raise PermanentSendError("user has no telegram_chat_id configured")

        url = f"{config.telegram_api_base()}/bot{token}/sendMessage"
        text = (
            f"[{notification['severity'].upper()}] {notification['title']}\n"
            f"{notification['body']}"
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT
            ) as client:
                response = await client.post(
                    url, json={"chat_id": chat_id, "text": text[:4096]}
                )
        except httpx.HTTPError as exc:  # transport/timeout errors: retryable
            raise TransientSendError(f"telegram request failed: {exc}") from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientSendError(
                f"telegram API returned {response.status_code}"
            )
        if response.status_code >= 400:
            raise PermanentSendError(
                f"telegram API rejected the message ({response.status_code}): "
                f"{response.text[:200]}"
            )
