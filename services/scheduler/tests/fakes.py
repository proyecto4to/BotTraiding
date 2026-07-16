"""Deterministic fakes for the scheduler's injectable downstream clients."""

from __future__ import annotations

from typing import Any

from app.clients import (
    AiEngineClient,
    HealthClient,
    OptimizerClient,
    StrategyEngineClient,
)


class FakeStrategyEngineClient(StrategyEngineClient):
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self.calls = 0

    async def list_enabled_strategies(self) -> list[dict[str, Any]]:
        self.calls += 1
        return [{"key": key, "enabled": True} for key in self._keys]


class FakeOptimizerClient(OptimizerClient):
    def __init__(
        self,
        fail_for: set[str] | None = None,
        results: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.triggered: list[tuple[str, dict[str, Any]]] = []
        self.promote_flags: list[bool] = []
        self._fail_for = fail_for or set()
        #: strategy_key -> canned /optimize response (learning-loop tests).
        self._results = results or {}

    async def trigger_optimization(
        self, strategy_key: str, params: dict[str, Any], *, promote: bool = False
    ) -> dict[str, Any]:
        if strategy_key in self._fail_for:
            raise RuntimeError(f"optimizer unavailable for {strategy_key}")
        self.triggered.append((strategy_key, params))
        self.promote_flags.append(promote)
        canned = self._results.get(strategy_key)
        if canned is not None:
            return dict(canned)
        return {"id": f"run-{len(self.triggered)}", "status": "pending"}


class FakeAiEngineClient(AiEngineClient):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def refresh_regime(self, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(params)
        return {"refreshed": [], "detail": "ok"}


class FakeHealthClient(HealthClient):
    def __init__(self, down: set[str] | None = None) -> None:
        self._down = down or set()
        self.pinged: list[tuple[str, str]] = []

    async def ping(self, name: str, base_url: str) -> bool:
        self.pinged.append((name, base_url))
        return name not in self._down
