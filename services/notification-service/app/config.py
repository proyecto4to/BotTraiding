"""Environment-driven configuration for notification-service.

Everything is read lazily (function calls, not module constants) so tests can
set/override env vars without import-order games. Env vars consumed here:

- NATS_URL                        optional; unset/unreachable => degraded mode
- NOTIFY_SUBJECTS                 comma-separated NATS subjects to subscribe
- NOTIFY_MAX_RETRIES              transient-failure retries per channel send
- NOTIFY_RETRY_BACKOFF            base backoff seconds (exponential, 2**n)
- NOTIFY_INGEST_TOKEN             optional shared secret for POST /notifications/ingest
- SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM  (email channel)
- TELEGRAM_BOT_TOKEN              (telegram channel)
- TELEGRAM_API_BASE               override for tests (default https://api.telegram.org)
- WEBHOOK_SIGNING_DEFAULT_SECRET  HMAC fallback when a user has no webhook_secret
"""

from __future__ import annotations

import os

DEFAULT_SUBJECTS = "risk.>,execution.>,ai.>,optimizer.>,bot.>"


def nats_url() -> str | None:
    return os.environ.get("NATS_URL") or None


def subjects() -> list[str]:
    raw = os.environ.get("NOTIFY_SUBJECTS", DEFAULT_SUBJECTS)
    return [s.strip() for s in raw.split(",") if s.strip()]


def max_retries() -> int:
    return int(os.environ.get("NOTIFY_MAX_RETRIES", "3"))


def retry_backoff() -> float:
    return float(os.environ.get("NOTIFY_RETRY_BACKOFF", "0.5"))


def ingest_token() -> str | None:
    return os.environ.get("NOTIFY_INGEST_TOKEN") or None


def smtp_settings() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from_addr": os.environ.get("SMTP_FROM", "alerts@tradingplatform.local"),
    }


def telegram_bot_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def telegram_api_base() -> str:
    return os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")


def webhook_default_secret() -> str:
    return os.environ.get("WEBHOOK_SIGNING_DEFAULT_SECRET", "")
