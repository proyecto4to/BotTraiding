"""API request/response schemas for strategy-engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from trading_contracts import Bar, TradeSignal


class ParameterSpecOut(BaseModel):
    name: str
    type: str
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[Any]] = None
    description: str = ""


class StrategySummary(BaseModel):
    key: str
    name: str
    version: str
    category: str
    markets: list[str]
    timeframes: list[str]
    enabled: bool
    description: str


class StrategyDetail(StrategySummary):
    parameters: list[ParameterSpecOut]
    recommended_risk_per_trade: float
    historical_metrics: dict[str, float]
    db_id: Optional[str] = None


class StrategyToggleRequest(BaseModel):
    enabled: bool


class ConfigPutRequest(BaseModel):
    user_id: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    is_active: bool = True


class ConfigResponse(BaseModel):
    strategy_key: str
    version: str
    user_id: str
    account_id: Optional[str] = None
    overrides: dict[str, Any]
    is_active: bool
    updated_at: Optional[datetime] = None


class EvaluateRequest(BaseModel):
    bars: list[Bar] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = None
    account_id: Optional[str] = None
    market: Optional[str] = None


class EvaluateResponse(BaseModel):
    strategy_key: str
    signal: Optional[TradeSignal] = None
    params_used: dict[str, Any]
