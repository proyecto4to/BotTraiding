"""Email channel: SMTP via stdlib smtplib executed in a thread executor
(keeps the event loop free without pulling in aiosmtplib).

Env: SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
Target address comes from the user's preference row (email_address).
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app import config
from app.channels import PermanentSendError, TransientSendError


class EmailSender:
    name = "email"

    async def send(self, notification: dict, preference) -> None:
        settings = config.smtp_settings()
        if not settings["host"]:
            raise PermanentSendError("SMTP_HOST is not configured")
        to_addr = getattr(preference, "email_address", None)
        if not to_addr:
            raise PermanentSendError("user has no email_address configured")

        message = EmailMessage()
        message["Subject"] = f"[{notification['severity'].upper()}] {notification['title']}"
        message["From"] = settings["from_addr"]
        message["To"] = to_addr
        message.set_content(
            f"{notification['title']}\n\n{notification['body']}\n\n"
            f"subject: {notification['subject']}\n"
            f"severity: {notification['severity']}\n"
            f"notification_id: {notification['id']}"
        )

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._send_sync, settings, message)
        except (smtplib.SMTPException, OSError) as exc:
            # Connection refused, timeouts, transient server errors: retryable.
            raise TransientSendError(f"smtp send failed: {exc}") from exc

    @staticmethod
    def _send_sync(settings: dict, message: EmailMessage) -> None:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=10) as smtp:
            if settings["user"]:
                try:
                    smtp.starttls()
                except smtplib.SMTPNotSupportedError:
                    pass  # local/dev relays without TLS
                smtp.login(settings["user"], settings["password"] or "")
            smtp.send_message(message)
