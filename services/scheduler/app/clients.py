"""Injectable httpx clients for the scheduler's downstream services.

Every downstream call goes through one of these seams so tests can mock
them (get_*/set_* pattern shared with the other services). URLs come
from env: STRATEGY_ENGINE_URL, OPTIMIZER_URL, AI_ENGINE_URL, plus
HEALTH_PING_URLS for the ping job.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

DEFAULT_TIMEOUT = 30.0


def _url(env_var: str, default: str) -> str:
    return os.environ.get(env_var, default).rstrip("/")


# --- strategy-engine ------------------------------------------------------------


class StrategyEngineClient(ABC):
    @abstractmethod
    async def list_enabled_strategies(self) -> list[dict[str, Any]]:
        """Enabled strategies (key, category, ...) from strategy-engine."""


class HttpStrategyEngineClient(StrategyEngineClient):
    async def list_enabled_strategies(self) -> list[dict[str, Any]]:
        base = _url("STRATEGY_ENGINE_URL", "http://strategy-engine:8000")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(f"{base}/strategies", params={"enabled": "true"})
            resp.raise_for_status()
            return resp.json()


# --- optimizer -------------------------------------------------------------------


class OptimizerClient(ABC):
    @abstractmethod
    async def trigger_optimization(
        self, strategy_key: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Start one re-optimization run for a strategy."""


def build_optimize_payload(strategy_key: str, params: dict[str, Any]) -> dict[str, Any]:
    """POST /optimize body for a scheduled re-optimization.

    ``promote`` is HARDCODED to False: a cron job may trigger the search,
    but applying params stays an explicit, out-of-sample-validated act
    (docs/ARCHITECTURE.md Fase 12).
    """
    lookback_days = int(params.get("lookback_days", 180))
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=lookback_days)
    return {
        "strategy_key": strategy_key,
        "symbol": params.get("symbol", os.environ.get("OPTIMIZE_SYMBOL", "BTC/USDT")),
        "timeframe": params.get(
            "timeframe", os.environ.get("OPTIMIZE_TIMEFRAME", "1h")
        ),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "search_type": params.get("search_type", "grid"),
        "budget": int(params.get("budget", 16)),
        "promote": False,
    }


class HttpOptimizerClient(OptimizerClient):
    async def trigger_optimization(
        self, strategy_key: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        base = _url("OPTIMIZER_URL", "http://optimizer:8000")
        payload = build_optimize_payload(strategy_key, params)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(f"{base}/optimize", json=payload)
            resp.raise_for_status()
            return resp.json()


# --- ai-engine -------------------------------------------------------------------


class AiEngineClient(ABC):
    @abstractmethod
    async def refresh_regime(self, params: dict[str, Any]) -> dict[str, Any]:
        """Trigger ai-engine's periodic regime refresh."""


class HttpAiEngineClient(AiEngineClient):
    async def refresh_regime(self, params: dict[str, Any]) -> dict[str, Any]:
        base = _url("AI_ENGINE_URL", "http://ai-engine:8000")
        body: dict[str, Any] = {}
        if "timeframe" in params:
            body["timeframe"] = params["timeframe"]
        if "symbols" in params:
            body["symbols"] = params["symbols"]
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(f"{base}/ai/regime/refresh", json=body)
            resp.raise_for_status()
            return resp.json()


# --- autonomy-controller ---------------------------------------------------------


class AutonomyClient(ABC):
    @abstractmethod
    async def tick(self) -> dict[str, Any]:
        """Run one autonomy cycle (no-op when the master switch is off)."""


class HttpAutonomyClient(AutonomyClient):
    async def tick(self) -> dict[str, Any]:
        base = _url("AUTONOMY_URL", "http://autonomy-controller:8000")
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(f"{base}/autonomy/tick")
            resp.raise_for_status()
            return resp.json()


# --- health ping -------------------------------------------------------------------


class HealthClient(ABC):
    @abstractmethod
    async def ping(self, name: str, base_url: str) -> bool:
        """True when the service answers /health with 200."""


class HttpHealthClient(HealthClient):
    async def ping(self, name: str, base_url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


def health_ping_targets() -> dict[str, str]:
    """name->base_url map for the ping job.

    Env HEALTH_PING_URLS: comma-separated ``name=url`` pairs; defaults to
    the three services this scheduler drives.
    """
    raw = os.environ.get("HEALTH_PING_URLS", "").strip()
    if raw:
        targets: dict[str, str] = {}
        for pair in raw.split(","):
            name, _, url = pair.strip().partition("=")
            if name and url:
                targets[name] = url
        return targets
    return {
        "strategy-engine": _url("STRATEGY_ENGINE_URL", "http://strategy-engine:8000"),
        "optimizer": _url("OPTIMIZER_URL", "http://optimizer:8000"),
        "ai-engine": _url("AI_ENGINE_URL", "http://ai-engine:8000"),
    }


# --- injection seams (tests replace these) -----------------------------------

_strategy_engine: Optional[StrategyEngineClient] = None
_optimizer: Optional[OptimizerClient] = None
_ai_engine: Optional[AiEngineClient] = None
_autonomy: Optional[AutonomyClient] = None
_health: Optional[HealthClient] = None


def get_autonomy() -> AutonomyClient:
    global _autonomy
    if _autonomy is None:
        _autonomy = HttpAutonomyClient()
    return _autonomy


def set_autonomy(client: Optional[AutonomyClient]) -> None:
    global _autonomy
    _autonomy = client


def get_strategy_engine() -> StrategyEngineClient:
    global _strategy_engine
    if _strategy_engine is None:
        _strategy_engine = HttpStrategyEngineClient()
    return _strategy_engine


def set_strategy_engine(client: Optional[StrategyEngineClient]) -> None:
    global _strategy_engine
    _strategy_engine = client


def get_optimizer() -> OptimizerClient:
    global _optimizer
    if _optimizer is None:
        _optimizer = HttpOptimizerClient()
    return _optimizer


def set_optimizer(client: Optional[OptimizerClient]) -> None:
    global _optimizer
    _optimizer = client


def get_ai_engine() -> AiEngineClient:
    global _ai_engine
    if _ai_engine is None:
        _ai_engine = HttpAiEngineClient()
    return _ai_engine


def set_ai_engine(client: Optional[AiEngineClient]) -> None:
    global _ai_engine
    _ai_engine = client


def get_health() -> HealthClient:
    global _health
    if _health is None:
        _health = HttpHealthClient()
    return _health


def set_health(client: Optional[HealthClient]) -> None:
    global _health
    _health = client
