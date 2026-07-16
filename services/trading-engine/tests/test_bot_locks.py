"""P3: per-bot run locks — one loop per bot, across replicas.

Two "replicas" are two lock stores pointing at the same (fake) Redis server:
a bot locked through one must be unstartable from the other, a crashed
replica's lease must expire, and a replica can never release a lock it does
not own. Redis outages degrade to per-process locking, never raise.
"""

from __future__ import annotations

import fakeredis
import pytest
from app import bot_locks
from app.bot_locks import (
    InMemoryBotLockStore,
    RedisBotLockStore,
    build_lock_store,
)
from app.models import BotRow
from app.orchestrator import BotRunner, mark_orphaned_bots


@pytest.fixture()
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


def make_store(server: fakeredis.FakeServer) -> RedisBotLockStore:
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    return RedisBotLockStore(client)


# --- in-memory store -----------------------------------------------------------


def test_memory_lock_acquire_release_cycle() -> None:
    store = InMemoryBotLockStore()
    assert store.acquire("bot-1", ttl_seconds=60) is True
    assert store.is_locked("bot-1") is True
    assert store.acquire("bot-1", ttl_seconds=60) is False  # already held
    store.release("bot-1")
    assert store.is_locked("bot-1") is False
    assert store.acquire("bot-1", ttl_seconds=60) is True


def test_memory_lock_expires_after_ttl(monkeypatch) -> None:
    fake_now = [1_000.0]
    monkeypatch.setattr(bot_locks.time, "monotonic", lambda: fake_now[0])
    store = InMemoryBotLockStore()
    assert store.acquire("bot-1", ttl_seconds=10) is True
    fake_now[0] += 11.0  # the holder crashed and never refreshed
    assert store.is_locked("bot-1") is False
    assert store.acquire("bot-1", ttl_seconds=10) is True


def test_memory_lock_refresh_extends_the_lease(monkeypatch) -> None:
    fake_now = [1_000.0]
    monkeypatch.setattr(bot_locks.time, "monotonic", lambda: fake_now[0])
    store = InMemoryBotLockStore()
    store.acquire("bot-1", ttl_seconds=10)
    fake_now[0] += 8.0
    store.refresh("bot-1", ttl_seconds=10)  # what each cycle does
    fake_now[0] += 8.0  # 16s after acquire, 8s after refresh
    assert store.is_locked("bot-1") is True


# --- redis store: replicas share the lock ---------------------------------------


def test_second_replica_cannot_take_a_held_lock(redis_server) -> None:
    replica_a = make_store(redis_server)
    replica_b = make_store(redis_server)

    assert replica_a.acquire("bot-1", ttl_seconds=60) is True
    assert replica_b.acquire("bot-1", ttl_seconds=60) is False
    assert replica_b.is_locked("bot-1") is True  # visible, just not ours
    # an unrelated bot is still lockable from either replica
    assert replica_b.acquire("bot-2", ttl_seconds=60) is True


def test_release_only_frees_our_own_lock(redis_server) -> None:
    replica_a = make_store(redis_server)
    replica_b = make_store(redis_server)

    replica_a.acquire("bot-1", ttl_seconds=60)
    replica_b.release("bot-1")  # not the owner: must be a no-op
    assert replica_a.is_locked("bot-1") is True
    replica_a.release("bot-1")
    assert replica_b.acquire("bot-1", ttl_seconds=60) is True


def test_owner_can_reacquire_its_own_lease(redis_server) -> None:
    store = make_store(redis_server)
    assert store.acquire("bot-1", ttl_seconds=60) is True
    # e.g. the endpoint retried: same owner re-acquires instead of deadlocking
    assert store.acquire("bot-1", ttl_seconds=60) is True


def test_redis_lease_carries_a_ttl(redis_server) -> None:
    """The lease must expire on its own — that is what frees a crashed
    replica's bots (nobody calls release after a crash)."""
    store = make_store(redis_server)
    store.acquire("bot-1", ttl_seconds=60)
    client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    ttl_ms = client.pttl("bot_locks:bot-1")
    assert 0 < ttl_ms <= 60_000
    store.refresh("bot-1", ttl_seconds=120)
    assert client.pttl("bot_locks:bot-1") > 60_000


# --- degradation ----------------------------------------------------------------


class BrokenRedis:
    def get(self, *a, **k):
        raise ConnectionError("redis is down")

    def set(self, *a, **k):
        raise ConnectionError("redis is down")

    def delete(self, *a, **k):
        raise ConnectionError("redis is down")

    def exists(self, *a, **k):
        raise ConnectionError("redis is down")

    def pexpire(self, *a, **k):
        raise ConnectionError("redis is down")


def test_redis_outage_degrades_to_in_process_locks() -> None:
    store = RedisBotLockStore(BrokenRedis())
    # single-replica correctness survives the outage
    assert store.acquire("bot-1", ttl_seconds=60) is True
    assert store.acquire("bot-1", ttl_seconds=60) is False
    assert store.is_locked("bot-1") is True
    store.refresh("bot-1", ttl_seconds=60)  # must not raise
    store.release("bot-1")
    assert store.is_locked("bot-1") is False


# --- backend selection from the environment --------------------------------------


def test_build_lock_store_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.delenv("BOT_LOCK_BACKEND", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert isinstance(build_lock_store(), InMemoryBotLockStore)


def test_build_lock_store_memory_forced(monkeypatch) -> None:
    monkeypatch.setenv("BOT_LOCK_BACKEND", "memory")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    assert isinstance(build_lock_store(), InMemoryBotLockStore)


def test_build_lock_store_auto_uses_redis_when_url_set(
    monkeypatch, redis_server
) -> None:
    monkeypatch.delenv("BOT_LOCK_BACKEND", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(
        bot_locks,
        "_connect_redis",
        lambda url: fakeredis.FakeRedis(server=redis_server, decode_responses=True),
    )
    assert isinstance(build_lock_store(), RedisBotLockStore)


def test_build_lock_store_degrades_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("BOT_LOCK_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")

    def _boom(url):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(bot_locks, "_connect_redis", _boom)
    assert isinstance(build_lock_store(), InMemoryBotLockStore)  # boots anyway


# --- BotRunner integration --------------------------------------------------------


def test_runner_on_second_replica_cannot_start_a_locked_bot(redis_server) -> None:
    """The invariant P3 adds: with the shared store, a bot being driven by
    replica A is 'running' for replica B, and B refuses to start a duplicate
    loop (start() raises before any task is created)."""
    replica_a_store = make_store(redis_server)
    replica_b = BotRunner(lock_store=make_store(redis_server))

    replica_a_store.acquire("bot-1", ttl_seconds=60)  # A's loop owns the bot
    assert replica_b.is_running("bot-1") is True
    with pytest.raises(RuntimeError, match="already has a running loop"):
        replica_b.start("bot-1")


def test_mark_orphaned_skips_bots_locked_by_a_live_replica(
    db_session, redis_server
) -> None:
    """Startup reconciliation must not kill bots another replica is driving:
    only unlocked 'running' bots are true orphans."""
    orphan = BotRow(
        name="orphan", account_id="acct-1", broker="binance", symbols=["BTCUSD"],
        timeframe="1h", strategy_keys=["sma_crossover"], status="running",
        created_by="tester",
    )
    driven = BotRow(
        name="driven", account_id="acct-1", broker="binance", symbols=["BTCUSD"],
        timeframe="1h", strategy_keys=["sma_crossover"], status="running",
        created_by="tester",
    )
    db_session.add_all([orphan, driven])
    db_session.commit()

    other_replica = make_store(redis_server)
    other_replica.acquire(driven.id, ttl_seconds=60)

    marked = mark_orphaned_bots(db_session, lock_store=make_store(redis_server))
    db_session.commit()

    assert marked == 1
    db_session.refresh(orphan)
    db_session.refresh(driven)
    assert orphan.status == "error"
    assert driven.status == "running"  # a live replica owns it: untouched
