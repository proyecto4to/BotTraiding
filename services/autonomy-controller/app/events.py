"""Event seam: NATS publish with logging fallback (same pattern as the other
services). autonomy.enabled/disabled/halted/reset/cycle. Never raises."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("autonomy-controller.events")

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
    except Exception as exc:  # noqa: BLE001
        logger.warning("NATS unavailable (%s); logging events only", exc)
        return None


async def publish_event(subject: str, payload: dict) -> bool:
    body = json.dumps(payload, default=str)
    client = await _get_nats()
    if client is not None:
        try:
            await client.publish(subject, body.encode())
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("NATS publish failed (%s); event logged only", exc)
    logger.info("event %s %s", subject, body)
    return False
