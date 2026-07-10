"""Retry-with-backoff behavior: transient recovery, exhaustion, permanent."""

from __future__ import annotations

import asyncio

import pytest

from app.retry import (
    PermanentTransportError,
    RetryExhaustedError,
    TransientTransportError,
    retry_with_backoff,
)
from tests.conftest import full_fill, make_execution_payload


class FlakyBehavior:
    """Raise TransientTransportError ``failures`` times, then fill."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, order, market_price):
        self.calls += 1
        if self.calls <= self.failures:
            return TransientTransportError(f"blip #{self.calls}")
        return full_fill(order, market_price)


def test_retry_then_success(harness):
    harness.paper.behavior = FlakyBehavior(failures=2)

    response = harness.client.post("/executions", json=make_execution_payload())
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == "filled"
    assert len(harness.paper.orders) == 3  # 2 failures + 1 success
    assert body["child_orders"][0]["attempts"] == 3


def test_retry_exhausted_marks_execution_error(harness):
    harness.paper.behavior = lambda order, market_price: TransientTransportError("down")

    response = harness.client.post("/executions", json=make_execution_payload())
    assert response.status_code == 201  # submission accepted; result is error
    body = response.json()

    assert body["status"] == "error"
    assert len(harness.paper.orders) == 3  # max_attempts, then gave up
    child = body["child_orders"][0]
    assert child["status"] == "error"
    assert child["attempts"] == 3
    assert "3 attempts" in child["last_error"]
    assert body["reports"] == []  # no report was ever produced
    assert harness.forwarder.calls == []


def test_permanent_error_is_not_retried(harness):
    harness.paper.behavior = lambda order, market_price: PermanentTransportError("bad broker")

    response = harness.client.post("/executions", json=make_execution_payload())
    body = response.json()

    assert body["status"] == "error"
    assert len(harness.paper.orders) == 1  # exactly one attempt, no retries
    assert body["child_orders"][0]["attempts"] == 1


def test_error_stops_remaining_children(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "100")
    harness.paper.behavior = lambda order, market_price: TransientTransportError("down")

    response = harness.client.post(
        "/executions", json=make_execution_payload(quantity=250.0)
    )
    body = response.json()

    assert body["status"] == "error"
    statuses = [child["status"] for child in body["child_orders"]]
    assert statuses == ["error", "pending", "pending"]  # loop stopped at child 1


def test_retry_helper_backoff_delays():
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    calls = {"n": 0}

    async def attempt() -> str:
        calls["n"] += 1
        if calls["n"] < 4:
            raise TransientTransportError("nope")
        return "ok"

    result, attempts = asyncio.run(
        retry_with_backoff(
            attempt, max_attempts=5, base_delay=1.0, max_delay=3.0, jitter=0.0, sleep=fake_sleep
        )
    )
    assert result == "ok"
    assert attempts == 4
    assert sleeps == [1.0, 2.0, 3.0]  # exponential, capped at max_delay


def test_retry_helper_exhaustion_raises():
    async def attempt() -> str:
        raise TransientTransportError("always")

    async def no_sleep(_delay: float) -> None:
        return None

    with pytest.raises(RetryExhaustedError) as excinfo:
        asyncio.run(retry_with_backoff(attempt, max_attempts=2, jitter=0.0, sleep=no_sleep))
    assert excinfo.value.attempts == 2
