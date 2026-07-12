"""Runtime configuration for trading-engine.

Values are read from the environment at call time so tests can monkeypatch
per case and operators can tune without code changes.

Env vars:
- STRATEGY_ENGINE_URL / RISK_ENGINE_URL / EXECUTION_ENGINE_URL /
  BROKER_CONNECTORS_URL: downstream service base URLs.
- TRADING_HTTP_TIMEOUT: per-call HTTP timeout towards downstream services
  (seconds, default 10).
- BOT_MAX_CONSECUTIVE_ERRORS: consecutive degraded/error cycles before a
  running bot is auto-stopped with status=error (default 5).
- BOT_BAR_LOOKBACK: how many recent bars to request per cycle (default 100).
- DATABASE_URL: bot/cycle persistence (see app/db.py).
- JWT_SECRET: shared with auth-service (trading_contracts.auth).
- NATS_URL: optional event bus; events fall back to logging when unset.
"""

from __future__ import annotations

import os


def strategy_engine_url() -> str:
    return os.environ.get("STRATEGY_ENGINE_URL", "http://strategy-engine:8000").rstrip("/")


def risk_engine_url() -> str:
    return os.environ.get("RISK_ENGINE_URL", "http://risk-engine:8000").rstrip("/")


def execution_engine_url() -> str:
    return os.environ.get("EXECUTION_ENGINE_URL", "http://execution-engine:8000").rstrip("/")


def broker_connectors_url() -> str:
    return os.environ.get("BROKER_CONNECTORS_URL", "http://broker-connectors:8000").rstrip("/")


def http_timeout() -> float:
    return float(os.environ.get("TRADING_HTTP_TIMEOUT", "10"))


def max_consecutive_errors() -> int:
    return int(os.environ.get("BOT_MAX_CONSECUTIVE_ERRORS", "5"))


def bar_lookback() -> int:
    return int(os.environ.get("BOT_BAR_LOOKBACK", "100"))
