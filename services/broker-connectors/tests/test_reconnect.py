from __future__ import annotations

import pytest

from app.reconnect import ReconnectError, reconnect_with_backoff


@pytest.mark.asyncio
async def test_succeeds_after_a_few_retries():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("dropped")
        return "ok"

    result = await reconnect_with_backoff(flaky, max_attempts=5, base_delay=0.01, max_delay=0.05)

    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_raises_reconnect_error_after_exhausting_attempts():
    async def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ReconnectError):
        await reconnect_with_backoff(always_fail, max_attempts=3, base_delay=0.01, max_delay=0.02)
