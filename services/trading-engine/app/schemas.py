"""Request/response models for trading-engine.

A Bot is pure configuration (architecture principle 7: configured in DB,
never recompiled): which account/broker/symbols/timeframe to trade, which
strategies to evaluate and how often. BotOut doubles as the in-memory bot
spec the orchestrator consumes, so the cycle logic is testable without a DB.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from trading_contracts import ExecutionMode

TIMEFRAME_RE = re.compile(r"^\d+[smhdw]$")

BOT_STATUS_STOPPED = "stopped"
BOT_STATUS_RUNNING = "running"
BOT_STATUS_ERROR = "error"


def _validate_timeframe(value: str) -> str:
    if not TIMEFRAME_RE.match(value):
        raise ValueError(
            f"invalid timeframe '{value}' (expected <number><s|m|h|d|w>, e.g. '1h')"
        )
    return value


class BotBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_id: str = Field(min_length=1, max_length=64)
    broker: str = Field(min_length=1, max_length=50)
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    symbols: list[str] = Field(min_length=1)
    timeframe: str
    strategy_keys: list[str] = Field(min_length=1)
    params_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-strategy parameter overrides, keyed by strategy key.",
    )
    cycle_interval_seconds: float = Field(default=60.0, gt=0.0)

    @field_validator("timeframe")
    @classmethod
    def _timeframe(cls, value: str) -> str:
        return _validate_timeframe(value)


class BotCreate(BotBase):
    # API-level floor: sub-second loops are a config error in production;
    # the internal spec (BotOut) stays permissive so unit tests can drive
    # fast loops through BotRunner.
    cycle_interval_seconds: float = Field(default=60.0, ge=1.0)


class BotUpdate(BaseModel):
    """PATCH body: every field optional; only allowed while the bot is not
    running (config changes to a live loop would be unauditable)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    account_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    broker: Optional[str] = Field(default=None, min_length=1, max_length=50)
    execution_mode: Optional[ExecutionMode] = None
    symbols: Optional[list[str]] = Field(default=None, min_length=1)
    timeframe: Optional[str] = None
    strategy_keys: Optional[list[str]] = Field(default=None, min_length=1)
    params_overrides: Optional[dict[str, dict[str, Any]]] = None
    cycle_interval_seconds: Optional[float] = Field(default=None, ge=1.0)

    @field_validator("timeframe")
    @classmethod
    def _timeframe(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_timeframe(value)


class BotOut(BotBase):
    id: str
    status: str = BOT_STATUS_STOPPED
    status_reason: Optional[str] = None
    created_by: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CycleReportOut(BaseModel):
    """One orchestrator cycle: what was evaluated, decided, ordered and what
    failed. Persisted per cycle and returned by /bots/{id}/run-once and
    /bots/{id}/cycles."""

    id: str
    bot_id: str
    status: str  # ok | degraded | skipped | error
    reason: Optional[str] = None
    started_at: datetime
    finished_at: datetime
    signals: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    orders: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class BotActionResponse(BaseModel):
    bot: BotOut
    detail: str
