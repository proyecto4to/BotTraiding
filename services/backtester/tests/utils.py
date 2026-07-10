"""Test helpers: bar builders and a scripted strategy stub."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from uuid import uuid4

from trading_contracts import Bar, OrderSide, TradeSignal

T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def make_bars(
    ohlcv: Sequence[tuple[float, float, float, float, float]],
    start: datetime = T0,
    minutes: int = 60,
    symbol: str = "TEST",
    timeframe: str = "1h",
) -> list[Bar]:
    """Build hourly bars from (open, high, low, close, volume) tuples."""
    return [
        Bar(
            symbol=symbol,
            timeframe=timeframe,
            open=o, high=h, low=lo, close=c, volume=v,
            timestamp=start + timedelta(minutes=minutes * i),
        )
        for i, (o, h, lo, c, v) in enumerate(ohlcv)
    ]


def flat_bars(
    n: int,
    price: float = 100.0,
    volume: float = 10_000.0,
    start: datetime = T0,
    minutes: int = 60,
) -> list[Bar]:
    """n identical bars at *price* (no stop/target can ever trigger)."""
    return make_bars(
        [(price, price, price, price, volume)] * n, start=start, minutes=minutes
    )


class ScriptedStrategy:
    """Emits pre-scripted signals keyed by the LAST bar's timestamp.

    script: {timestamp: {"side": OrderSide, "stop_loss": ..., "take_profit": ...}}
    """

    def __init__(self, script: dict[datetime, dict]) -> None:
        self.script = script
        self.evaluations: list[datetime] = []

    def evaluate(self, bars: list[Bar], market: Optional[str] = None) -> Optional[TradeSignal]:
        last = bars[-1]
        self.evaluations.append(last.timestamp)
        spec = self.script.get(last.timestamp)
        if spec is None:
            return None
        return TradeSignal(
            id=uuid4(),
            strategy_id="scripted",
            symbol=last.symbol,
            market=market or "test",
            side=spec["side"],
            confidence=1.0,
            timeframe=last.timeframe,
            suggested_size=1.0,
            stop_loss=spec.get("stop_loss"),
            take_profit=spec.get("take_profit"),
            generated_at=last.timestamp,
            metadata={},
        )


def buy(stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> dict:
    return {"side": OrderSide.BUY, "stop_loss": stop_loss, "take_profit": take_profit}


def sell(stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> dict:
    return {"side": OrderSide.SELL, "stop_loss": stop_loss, "take_profit": take_profit}
