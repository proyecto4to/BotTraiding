"""Event seam: NATS publish with logging fallback + risk_events audit rows.

Architecture section 4/7: risk decisions flow as NATS events
(`risk.decision`, `risk.rejected`, `risk.circuit_breaker`). Fase 7 wires a
lazy NATS client when NATS_URL is set and nats-py is importable; otherwise
every event is logged. Independently of the bus, every rejection/halt is
persisted to the risk_events table for audit (persist_event).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.models import RiskEvent

logger = logging.getLogger("risk-engine.events")

_nats_client: Any = None


async def _get_nats():
    global _nats_client
    if _nats_client is not None:
        return _nats_client
    nats_url = os.environ.get("NATS_URL")
    if not nats_url:
        return None
    try:
        import nats  # type: ignore

        _nats_client = await nats.connect(nats_url)
        return _nats_client
    except Exception as exc:  # ImportError, connection errors, ...
        logger.warning("NATS unavailable (%s); falling back to log-only events", exc)
        return None


async def publish_event(subject: str, payload: dict) -> bool:
    """Publish to NATS when configured; always logs. Never raises: event
    publication must not break the synchronous validate path."""
    body = json.dumps(payload, default=str)
    client = await _get_nats()
    if client is not None:
        try:
            await client.publish(subject, body.encode())
            return True
        except Exception as exc:
            logger.warning("NATS publish failed (%s); event logged only", exc)
    logger.info("event %s %s", subject, body)
    return False


def persist_event(
    db: Session,
    account_id: str,
    event_type: str,
    payload: dict,
    signal_id: str | None = None,
) -> RiskEvent:
    row = RiskEvent(
        account_id=account_id,
        event_type=event_type,
        signal_id=signal_id,
        payload=payload,
    )
    db.add(row)
    db.flush()
    return row
