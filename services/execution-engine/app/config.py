"""Runtime configuration for execution-engine.

Values are read from the environment at call time so tests can monkeypatch
per case and operators can tune without code changes.

Env vars:
- EXECUTION_MODE: default execution mode ("paper"|"live", default "paper").
  Per-request override (an order whose execution_mode differs from this
  default) requires an admin JWT.
- EXECUTION_LIVE_ENABLED: register the live transport at all (default true).
- EXECUTION_MAX_CHILD_SIZE: orders larger than this are split into
  sequentially executed child orders (0 = no splitting, default 0).
- EXECUTION_RETRY_MAX_ATTEMPTS / _BASE_DELAY / _MAX_DELAY / _JITTER:
  transient-transport retry policy (defaults 3 / 0.2s / 5s / 0.25).
- PAPER_TRADING_URL / BROKER_CONNECTORS_URL / PORTFOLIO_ENGINE_URL:
  downstream service base URLs.
- EXECUTION_TRANSPORT_TIMEOUT: HTTP timeout towards transports (default 10s).
- JWT_SECRET: shared with auth-service (trading_contracts.auth).
- NATS_URL: optional event bus; events fall back to logging when unset.
"""

from __future__ import annotations

import os

from trading_contracts import ExecutionMode


def default_execution_mode() -> ExecutionMode:
    return ExecutionMode(os.environ.get("EXECUTION_MODE", "paper").lower())


def live_enabled() -> bool:
    return os.environ.get("EXECUTION_LIVE_ENABLED", "true").lower() in ("1", "true", "yes")


def max_child_size() -> float:
    return float(os.environ.get("EXECUTION_MAX_CHILD_SIZE", "0"))


def retry_max_attempts() -> int:
    return int(os.environ.get("EXECUTION_RETRY_MAX_ATTEMPTS", "3"))


def retry_base_delay() -> float:
    return float(os.environ.get("EXECUTION_RETRY_BASE_DELAY", "0.2"))


def retry_max_delay() -> float:
    return float(os.environ.get("EXECUTION_RETRY_MAX_DELAY", "5.0"))


def retry_jitter() -> float:
    return float(os.environ.get("EXECUTION_RETRY_JITTER", "0.25"))


def paper_trading_url() -> str:
    return os.environ.get("PAPER_TRADING_URL", "http://paper-trading:8000").rstrip("/")


def broker_connectors_url() -> str:
    return os.environ.get("BROKER_CONNECTORS_URL", "http://broker-connectors:8000").rstrip("/")


def portfolio_engine_url() -> str:
    return os.environ.get("PORTFOLIO_ENGINE_URL", "http://portfolio-engine:8000").rstrip("/")


def transport_timeout() -> float:
    return float(os.environ.get("EXECUTION_TRANSPORT_TIMEOUT", "10"))
