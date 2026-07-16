"""Per-bot run locks: exactly one loop per bot, across replicas (P3).

``BotRunner`` owns one asyncio task per running bot inside a process; the
lock store is what makes "one loop per bot" hold across *processes*. Two
implementations satisfy ``BotLockStore``:

- ``InMemoryBotLockStore``: per-process (previous implicit behaviour --
  ``BotRunner._tasks`` was the only guard).
- ``RedisBotLockStore``: a ``SET NX EX`` lease in Redis keyed by bot id and
  owned by this store instance. Replicas pointing at the same Redis cannot
  start a second loop for the same bot; the TTL (refreshed every cycle by
  the loop) guarantees a crashed replica's bots become startable again.

Backend selection (``build_lock_store``):

- ``BOT_LOCK_BACKEND=memory``: force per-process locks.
- ``BOT_LOCK_BACKEND=redis``: use Redis at ``REDIS_URL``.
- unset / ``auto``: Redis when ``REDIS_URL`` is set, memory otherwise.

Redis missing/unreachable at startup degrades to in-memory locks with a
warning -- the service never fails to start. A Redis blip at runtime
delegates the operation to an embedded in-memory store so single-replica
correctness is preserved during the outage.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional, Protocol

logger = logging.getLogger("trading-engine.bot_locks")


class BotLockStore(Protocol):
    """Cross-replica mutual exclusion for bot loops. Implementations must
    never raise from these methods (degrade + log instead)."""

    def acquire(self, bot_id: str, ttl_seconds: float) -> bool:
        """Take the bot's lock. False when another holder (or replica) has it."""
        ...  # pragma: no cover - protocol

    def refresh(self, bot_id: str, ttl_seconds: float) -> None:
        """Extend the lease of a lock this store already holds."""
        ...  # pragma: no cover - protocol

    def release(self, bot_id: str) -> None:
        """Release the lock if this store holds it."""
        ...  # pragma: no cover - protocol

    def is_locked(self, bot_id: str) -> bool:
        """Is the bot's lock currently held (by anyone)?"""
        ...  # pragma: no cover - protocol


class InMemoryBotLockStore:
    """Per-process lock table with TTL expiry (single-instance semantics)."""

    def __init__(self) -> None:
        self._expiry: dict[str, float] = {}  # bot_id -> monotonic deadline

    def _alive(self, bot_id: str) -> bool:
        deadline = self._expiry.get(bot_id)
        if deadline is None:
            return False
        if deadline < time.monotonic():
            self._expiry.pop(bot_id, None)
            return False
        return True

    def acquire(self, bot_id: str, ttl_seconds: float) -> bool:
        if self._alive(bot_id):
            return False
        self._expiry[bot_id] = time.monotonic() + ttl_seconds
        return True

    def refresh(self, bot_id: str, ttl_seconds: float) -> None:
        if self._alive(bot_id):
            self._expiry[bot_id] = time.monotonic() + ttl_seconds

    def release(self, bot_id: str) -> None:
        self._expiry.pop(bot_id, None)

    def is_locked(self, bot_id: str) -> bool:
        return self._alive(bot_id)


class RedisBotLockStore:
    """Redis lease per bot: ``SET bot_locks:{bot_id} <owner> NX PX <ttl>``.

    Each store instance has a unique owner token, so refresh/release only
    act on locks this instance took (a replica can never release another
    replica's lock). Redis errors are logged and delegated to an embedded
    in-memory store: never raises, keeps single-replica behaviour correct
    while Redis is down.
    """

    def __init__(
        self,
        client,
        *,
        key_prefix: str = "bot_locks:",
        owner: Optional[str] = None,
        fallback: Optional[InMemoryBotLockStore] = None,
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self.owner = owner or uuid.uuid4().hex
        self._fallback = fallback or InMemoryBotLockStore()

    def _key(self, bot_id: str) -> str:
        return f"{self._prefix}{bot_id}"

    def _held_by_me(self, bot_id: str) -> bool:
        raw = self._client.get(self._key(bot_id))
        if isinstance(raw, bytes):
            raw = raw.decode()
        return raw == self.owner

    @staticmethod
    def _ttl_ms(ttl_seconds: float) -> int:
        return max(1, int(ttl_seconds * 1000))

    def acquire(self, bot_id: str, ttl_seconds: float) -> bool:
        key = self._key(bot_id)
        ttl_ms = self._ttl_ms(ttl_seconds)
        try:
            if self._client.set(key, self.owner, nx=True, px=ttl_ms):
                return True
            if self._held_by_me(bot_id):  # re-acquire our own lease
                self._client.pexpire(key, ttl_ms)
                return True
            return False
        except Exception as exc:  # noqa: BLE001 - degrade to per-process lock
            logger.warning("redis bot lock unavailable (%s); using in-process lock", exc)
            return self._fallback.acquire(bot_id, ttl_seconds)

    def refresh(self, bot_id: str, ttl_seconds: float) -> None:
        try:
            if self._held_by_me(bot_id):
                self._client.pexpire(self._key(bot_id), self._ttl_ms(ttl_seconds))
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis bot lock refresh failed (%s)", exc)
            self._fallback.refresh(bot_id, ttl_seconds)

    def release(self, bot_id: str) -> None:
        try:
            if self._held_by_me(bot_id):
                self._client.delete(self._key(bot_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis bot lock release failed (%s)", exc)
        self._fallback.release(bot_id)

    def is_locked(self, bot_id: str) -> bool:
        try:
            return bool(self._client.exists(self._key(bot_id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis bot lock check failed (%s)", exc)
            return self._fallback.is_locked(bot_id)


def _connect_redis(url: str):
    """Build a pinged sync Redis client (import deferred: redis is optional)."""
    import redis

    client = redis.Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=1.0
    )
    client.ping()
    return client


def build_lock_store() -> BotLockStore:
    """Pick the lock backend from the environment (see module docstring)."""
    backend = os.environ.get("BOT_LOCK_BACKEND", "auto").strip().lower()
    url = os.environ.get("REDIS_URL") or None
    if backend == "redis" or (backend == "auto" and url):
        try:
            if not url:
                raise RuntimeError("BOT_LOCK_BACKEND=redis requires REDIS_URL")
            client = _connect_redis(url)
            logger.info("bot lock backend: redis (%s)", url)
            return RedisBotLockStore(client)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash startup
            logger.warning(
                "redis bot locks unavailable (%s); degrading to in-memory "
                "per-process locks",
                exc,
            )
    return InMemoryBotLockStore()
