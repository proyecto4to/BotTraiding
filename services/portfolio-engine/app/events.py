"""Event seam: NATS publish with logging fallback (risk/execution pattern).

Architecture section 7: reconciliation results go over NATS
(`portfolio.reconciliation`) when NATS_URL is configured and nats-py is
importable; otherwise every event is logged. Publication never raises: the
reconcile path must not break because the bus is down. Implemented locally
because services never import each other's code.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("portfolio-engine.events")

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
    """Publish to NATS when configured; always logs. Never raises."""
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
