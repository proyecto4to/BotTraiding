"""Shared typed contracts for TradingPlatform services.

Fase 1: solo definiciones tipadas (pydantic models + interfaces abstractas),
sin ninguna logica de trading. Ver docs/ARCHITECTURE.md seccion 5.
"""

from .models import (
    TradeSignal,
    RiskDecision,
    Order,
    OrderSide,
    OrderType,
    OrderStatus,
    ExecutionMode,
    RiskLimits,
    Position,
    AccountState,
    Tick,
    Bar,
    ExecutionReport,
    StrategyMetadata,
)
from .broker_connector import BrokerConnector
from .strategy import Strategy, StrategyContext
from .auth import TokenPayload, TokenError, decode_token

__all__ = [
    "TradeSignal",
    "RiskDecision",
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "ExecutionMode",
    "RiskLimits",
    "Position",
    "AccountState",
    "Tick",
    "Bar",
    "ExecutionReport",
    "StrategyMetadata",
    "BrokerConnector",
    "Strategy",
    "StrategyContext",
    "TokenPayload",
    "TokenError",
    "decode_token",
]
