"""Strategy interface (seccion 5.5).

Una estrategia solo PROPONE (`TradeSignal`); nunca ejecuta directamente.
Fase 1: solo el contrato, sin implementaciones ni logica de trading.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel

from .models import StrategyMetadata, TradeSignal


class StrategyContext(BaseModel):
    """Contexto pasado a on_bar/on_tick: datos de mercado + estado necesario."""

    symbol: str
    timeframe: str
    data: dict[str, Any] = {}


class Strategy(ABC):
    """Contrato que cada plugin de estrategia debe implementar."""

    @property
    @abstractmethod
    def metadata(self) -> StrategyMetadata:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON-schema-like dict describing configurable parameters."""
        ...

    @abstractmethod
    def on_bar(self, context: StrategyContext) -> Optional[TradeSignal]:
        ...

    def on_tick(self, context: StrategyContext) -> Optional[TradeSignal]:
        """Opcional: solo estrategias intradia."""
        return None

    @abstractmethod
    def required_filters(self) -> list[str]:
        ...
