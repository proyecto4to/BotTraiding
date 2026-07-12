"""Event -> notifications pipeline: derive severity, resolve target users from
persisted preferences, persist one notification row per target, and dispatch
to each enabled channel (min-severity gated) with retry + dead-lettering.

Delivery failures NEVER propagate out of ingest_event: a broken SMTP server
must not crash the NATS subscriber or return 500 to an ingesting service.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, rules
from app.channels import ChannelSender, TransientSendError, get_senders
from app.models import DeadLetterRow, NotificationRow, PreferenceRow
from app.schemas import EventIn

logger = logging.getLogger("notification-service.routing")

CHANNELS = ("email", "telegram", "webhook")


class DeliveryError(Exception):
    """A channel send that failed for good (retries exhausted or permanent)."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


def subject_matches(pattern: str, subject: str) -> bool:
    """NATS-style subject matching: `*` = one token, `>` = rest of subject."""
    if pattern in ("", ">"):
        return True
    pattern_tokens = pattern.split(".")
    subject_tokens = subject.split(".")
    for index, token in enumerate(pattern_tokens):
        if token == ">":
            return True
        if index >= len(subject_tokens):
            return False
        if token not in ("*", subject_tokens[index]):
            return False
    return len(subject_tokens) == len(pattern_tokens)


def _pref_wants(pref: PreferenceRow, event_subject: str, account_id: str | None) -> bool:
    subjects = pref.subjects or []
    if subjects and not any(subject_matches(p, event_subject) for p in subjects):
        return False
    accounts = pref.account_ids or []
    if accounts and account_id is not None and account_id not in accounts:
        return False
    return True


def _channels_for(pref: PreferenceRow, severity: str) -> list[str]:
    """Enabled channels whose min-severity admits this event's severity."""
    rank = rules.severity_rank(severity)
    routed: list[str] = []
    for channel in CHANNELS:
        if not getattr(pref, f"{channel}_enabled"):
            continue
        if rank < rules.severity_rank(getattr(pref, f"{channel}_min_severity")):
            continue
        routed.append(channel)
    return routed


def _channel_target(pref: PreferenceRow, channel: str) -> str | None:
    return {
        "email": pref.email_address,
        "telegram": pref.telegram_chat_id,
        "webhook": pref.webhook_url,
    }.get(channel)


def notification_dict(row: NotificationRow) -> dict:
    """Flat payload handed to channel senders (and signed for webhooks)."""
    return {
        "id": row.id,
        "subject": row.subject,
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "user_id": row.user_id,
        "account_id": row.account_id,
        "payload": row.payload,
        "created_at": str(row.created_at),
    }


async def send_with_retry(sender: ChannelSender, notification: dict, pref) -> int:
    """Send through one channel, retrying transient failures with exponential
    backoff. Returns the number of attempts made; raises DeliveryError when
    the send is undeliverable."""
    max_retries = config.max_retries()
    backoff = config.retry_backoff()
    attempts = 0
    while True:
        attempts += 1
        try:
            await sender.send(notification, pref)
            return attempts
        except TransientSendError as exc:
            if attempts > max_retries:
                raise DeliveryError(f"retries exhausted: {exc}", attempts) from exc
            delay = backoff * (2 ** (attempts - 1))
            if delay > 0:
                await asyncio.sleep(delay)
        except Exception as exc:  # PermanentSendError and unexpected bugs
            raise DeliveryError(str(exc), attempts) from exc


async def dispatch(db: Session, row: NotificationRow, pref: PreferenceRow) -> None:
    """Deliver `row` to every routed channel; update row.status and write a
    dead-letter row per undeliverable channel."""
    channels = _channels_for(pref, row.severity)
    senders = get_senders()
    payload = notification_dict(row)
    successes = 0
    failures = 0
    for channel in channels:
        sender = senders.get(channel)
        if sender is None:
            continue
        try:
            await send_with_retry(sender, payload, pref)
            successes += 1
        except DeliveryError as exc:
            failures += 1
            logger.warning(
                "delivery failed (notification=%s channel=%s attempts=%s): %s",
                row.id, channel, exc.attempts, exc,
            )
            db.add(
                DeadLetterRow(
                    notification_id=row.id,
                    user_id=row.user_id,
                    channel=channel,
                    target=_channel_target(pref, channel),
                    error=str(exc),
                    retry_count=exc.attempts,
                    payload=payload,
                )
            )
    if failures == 0:
        row.status = "sent"  # includes "no channels routed": nothing outstanding
    elif successes > 0:
        row.status = "failed"  # partial delivery
    else:
        row.status = "dead"  # every routed channel exhausted


def _resolve_targets(
    db: Session, event: EventIn, account_id: str | None
) -> list[tuple[str | None, PreferenceRow | None]]:
    """(user_id, preference|None) per target.

    - Directed event (explicit user_id): always one target — the notification
      is persisted for that user's feed even without a preference row; channel
      dispatch only happens when their preference filters admit the event.
    - Broadcast event: every user whose preference filters (subjects,
      account_ids) match. Empty => one unrouted (user_id=None) audit row.
    """
    if event.user_id:
        pref = db.get(PreferenceRow, event.user_id)
        if pref is not None and not _pref_wants(pref, event.subject, account_id):
            pref = None  # persist for the user, but no channel delivery
        return [(event.user_id, pref)]
    prefs = db.execute(select(PreferenceRow)).scalars().all()
    matched = [(p.user_id, p) for p in prefs if _pref_wants(p, event.subject, account_id)]
    return matched or [(None, None)]


async def ingest_event(db: Session, event: EventIn) -> list[NotificationRow]:
    """Persist + route one event. Always commits; never raises for delivery
    problems (they become failed/dead rows + dead letters)."""
    severity = event.severity or rules.derive_severity(event.subject, event.payload)
    title, body = rules.build_message(event.subject, event.payload)
    account_id = event.account_id or event.payload.get("account_id")

    rows: list[NotificationRow] = []
    for user_id, pref in _resolve_targets(db, event, account_id):
        row = NotificationRow(
            user_id=user_id,
            account_id=account_id,
            subject=event.subject,
            severity=severity,
            title=title,
            body=body,
            payload=event.payload,
            status="pending" if pref is not None else "sent",  # sent = nothing to deliver
        )
        db.add(row)
        db.flush()
        if pref is not None:
            try:
                await dispatch(db, row, pref)
            except Exception:  # defensive: intake must never crash
                logger.exception("dispatch crashed for notification %s", row.id)
                row.status = "failed"
        rows.append(row)

    db.commit()
    return rows
