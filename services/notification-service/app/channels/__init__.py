"""Delivery channels: common ChannelSender protocol + injectable registry.

Every sender implements::

    name: str
    async def send(notification: dict, preference) -> None

where `notification` is the flat dict built by app/routing.py
({id, subject, severity, title, body, user_id, account_id, payload,
created_at}) and `preference` is the target user's PreferenceRow (or any
object with the same attributes).

Failure contract:
- raise TransientSendError for retryable problems (network, 5xx, throttling);
  the dispatcher retries with exponential backoff up to NOTIFY_MAX_RETRIES;
- raise PermanentSendError (or any other exception) for non-retryable
  problems (bad config, 4xx); the dispatcher dead-letters immediately.

The registry is process-global and injectable: tests call set_senders({...})
with mocks; set_senders(None) restores the real senders.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ChannelSendError(Exception):
    """Base class for channel delivery failures."""


class TransientSendError(ChannelSendError):
    """Retryable failure (network hiccup, 5xx, rate limit)."""


class PermanentSendError(ChannelSendError):
    """Non-retryable failure (missing config, rejected payload, 4xx)."""


@runtime_checkable
class ChannelSender(Protocol):
    name: str

    async def send(self, notification: dict, preference) -> None: ...


_overrides: "dict[str, ChannelSender] | None" = None


def get_senders() -> dict[str, ChannelSender]:
    """Channel name -> sender. Real senders unless tests injected mocks."""
    if _overrides is not None:
        return _overrides
    # Imported lazily so importing the package never requires channel deps.
    from app.channels.email import EmailSender
    from app.channels.telegram import TelegramSender
    from app.channels.webhook import WebhookSender

    return {
        "email": EmailSender(),
        "telegram": TelegramSender(),
        "webhook": WebhookSender(),
    }


def set_senders(senders: "dict[str, ChannelSender] | None") -> None:
    """Inject mock senders (tests). Pass None to restore the real ones."""
    global _overrides
    _overrides = senders
