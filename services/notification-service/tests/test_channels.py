"""Channel senders called with the correct payloads (mocked SMTP / httpx)."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from app.channels import PermanentSendError, TransientSendError
from app.channels.email import EmailSender
from app.channels.telegram import TelegramSender
from app.channels.webhook import SIGNATURE_HEADER, WebhookSender
from tests.conftest import make_pref

NOTIFICATION = {
    "id": "n-1",
    "subject": "risk.circuit_breaker",
    "severity": "critical",
    "title": "Circuit breaker HARD_HALT on account acc-1",
    "body": "everything is on fire",
    "user_id": "user-1",
    "account_id": "acc-1",
    "payload": {"state": "HARD_HALT"},
    "created_at": "2026-07-11 10:00:00",
}


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------


class FakeSMTP:
    """Stands in for smtplib.SMTP; records the sent message."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.messages = []
        self.logged_in = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.messages.append(message)


async def test_email_sender_builds_message(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "bot")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("SMTP_FROM", "alerts@test")
    monkeypatch.setattr("app.channels.email.smtplib.SMTP", FakeSMTP)
    FakeSMTP.instances = []

    pref = make_pref(email="trader@example.com")
    await EmailSender().send(NOTIFICATION, pref)

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.test", 2525)
    assert smtp.logged_in == ("bot", "pw")
    [message] = smtp.messages
    assert message["To"] == "trader@example.com"
    assert message["From"] == "alerts@test"
    assert message["Subject"] == "[CRITICAL] Circuit breaker HARD_HALT on account acc-1"
    assert "everything is on fire" in message.get_content()


async def test_email_sender_missing_host_is_permanent(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(PermanentSendError):
        await EmailSender().send(NOTIFICATION, make_pref(email="a@x.com"))


async def test_email_sender_connection_error_is_transient(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test")

    def _boom(host, port, timeout=None):
        raise ConnectionRefusedError("no smtp here")

    monkeypatch.setattr("app.channels.email.smtplib.SMTP", _boom)
    with pytest.raises(TransientSendError):
        await EmailSender().send(NOTIFICATION, make_pref(email="a@x.com"))


# ---------------------------------------------------------------------------
# telegram
# ---------------------------------------------------------------------------


async def test_telegram_sender_calls_bot_api(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    sender = TelegramSender(transport=httpx.MockTransport(handler))
    await sender.send(NOTIFICATION, make_pref(telegram="chat-77"))

    [request] = captured
    assert str(request.url) == "https://api.telegram.org/bot123:ABC/sendMessage"
    body = json.loads(request.content)
    assert body["chat_id"] == "chat-77"
    assert "[CRITICAL]" in body["text"]
    assert "everything is on fire" in body["text"]


async def test_telegram_5xx_transient_4xx_permanent(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    pref = make_pref(telegram="chat-77")

    sender = TelegramSender(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    with pytest.raises(TransientSendError):
        await sender.send(NOTIFICATION, pref)

    sender = TelegramSender(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad chat"))
    )
    with pytest.raises(PermanentSendError):
        await sender.send(NOTIFICATION, pref)


async def test_telegram_missing_token_is_permanent(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(PermanentSendError):
        await TelegramSender().send(NOTIFICATION, make_pref(telegram="chat-77"))


# ---------------------------------------------------------------------------
# webhook
# ---------------------------------------------------------------------------


async def test_webhook_sender_posts_signed_json(monkeypatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    pref = make_pref(webhook="https://hooks.example.com/x", webhook_secret="s3cret")
    sender = WebhookSender(transport=httpx.MockTransport(handler))
    await sender.send(NOTIFICATION, pref)

    [request] = captured
    assert str(request.url) == "https://hooks.example.com/x"
    assert json.loads(request.content) == json.loads(
        json.dumps(NOTIFICATION, default=str, sort_keys=True)
    )
    expected = hmac.new(b"s3cret", request.content, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == f"sha256={expected}"


async def test_webhook_falls_back_to_default_secret(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SIGNING_DEFAULT_SECRET", "platform-default")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    pref = make_pref(webhook="https://hooks.example.com/x")  # no per-user secret
    await WebhookSender(transport=httpx.MockTransport(handler)).send(NOTIFICATION, pref)

    [request] = captured
    expected = hmac.new(b"platform-default", request.content, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == f"sha256={expected}"


async def test_webhook_status_mapping() -> None:
    pref = make_pref(webhook="https://hooks.example.com/x", webhook_secret="s")

    sender = WebhookSender(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(TransientSendError):
        await sender.send(NOTIFICATION, pref)

    sender = WebhookSender(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(PermanentSendError):
        await sender.send(NOTIFICATION, pref)


async def test_webhook_missing_url_is_permanent() -> None:
    with pytest.raises(PermanentSendError):
        await WebhookSender().send(NOTIFICATION, make_pref())
