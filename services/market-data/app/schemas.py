"""Request/response models for market-data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from trading_contracts import Bar


class Subscription(BaseModel):
    broker: str = "binance"
    symbol: str
    timeframe: str = "1h"


class SubscriptionStatus(BaseModel):
    broker: str
    symbol: str
    timeframe: str
    bar_count: int = 0
    last_refresh: Optional[datetime] = None
    last_error: Optional[str] = None


class BarsResponse(BaseModel):
    broker: str
    symbol: str
    timeframe: str
    source: Literal["cache", "upstream"]
    count: int
    bars: list[Bar] = Field(default_factory=list)


class RefreshResult(BaseModel):
    refreshed: int
    errors: int
