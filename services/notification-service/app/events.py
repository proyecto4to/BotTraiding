"""Event intake seam: async NATS subscriber with degraded-mode fallback.

Mirrors the per-service events.py convention (risk-engine et al.) from the
consuming side: when NATS_URL is unset or the server is unreachable the
service keeps running with a warning — REST intake (POST /notifications/ingest)
still works — instead of crashing. Subjects are configurable via
NOTIFY_SUBJECTS (default: risk.>, execution.>, ai.>, optimizer.>, bot.>;
bot.* comes from trading-engine which is built in parallel, so we subscribe
by wildcard and never import it).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app import config, routing
from app.schemas import EventIn

logger = logging.getLogger("notification-service.events")

_CONNECT_TIMEOUT_SECONDS = 5.0


@dataclass
class SubscriberState:
    connected: bool = False
    subjects: list[str] = field(default_factory=list)
    error: str | None = None
    client: Any = None


async def _handle_message(msg: Any) -> None:
    """One NATS message -> ingest pipeline. Never raises: a poison message or
    a delivery failure must not kill the subscription."""
    from app import db as db_module  # late import: tests swap the sessionmaker

    try:
        try:
            payload = json.loads(msg.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": repr(msg.data[:1024])}
        if not isinstance(payload, dict):
            payload = {"value": payload}

        event = EventIn(
            subject=msg.subject,
            account_id=payload.get("account_id"),
            user_id=payload.get("user_id"),
            payload=payload,
        )
        session = db_module.SessionLocal()
        try:
            await routing.ingest_event(session, event)
        finally:
            session.close()
    except Exception:
        logger.exception("failed to process NATS message on %s", getattr(msg, "subject", "?"))


async def start(app: Any) -> SubscriberState:
    """Connect + subscribe. Stores a SubscriberState on app.state.nats and
    returns it. Degrades (connected=False + warning log) when NATS_URL is
    unset, nats-py is missing, or the server is unreachable."""
    state = SubscriberState(subjects=config.subjects())
    app.state.nats = state

    url = config.nats_url()
    if not url:
        logger.warning(
            "NATS_URL not set; running degraded — event intake via "
            "POST /notifications/ingest only"
        )
        state.error = "NATS_URL not set"
        return state

    try:
        import nats  # type: ignore

        state.client = await asyncio.wait_for(
            nats.connect(
                url,
                connect_timeout=2,
                allow_reconnect=True,
                max_reconnect_attempts=-1,
            ),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # ImportError, timeout, connection refused, ...
        logger.warning(
            "NATS unreachable at %s (%s); running degraded — event intake via "
            "POST /notifications/ingest only",
            url,
            exc,
        )
        state.error = str(exc) or exc.__class__.__name__
        state.client = None
        return state

    for subject in state.subjects:
        await state.client.subscribe(subject, cb=_handle_message)
    state.connected = True
    logger.info("subscribed to NATS subjects: %s", ", ".join(state.subjects))
    return state


async def stop(app: Any) -> None:
    state: SubscriberState | None = getattr(app.state, "nats", None)
    if state is None or state.client is None:
        return
    try:
        await state.client.drain()
    except Exception:  # already closed / never fully connected
        logger.debug("NATS drain failed", exc_info=True)
    state.connected = False
    state.client = None
