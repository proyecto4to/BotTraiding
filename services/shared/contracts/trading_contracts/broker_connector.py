"""BrokerConnector interface (seccion 5.4).

Cada conector de broker/exchange (IBKR, Binance, MT5, simulado...) implementa
esta interfaz. Fase 1: solo el contrato, sin implementaciones reales.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator

from .models import AccountState, Bar, ExecutionReport, Order, Position, Tick


class BrokerConnector(ABC):
    """Contrato comun que independiza a la plataforma del proveedor de broker."""

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    async def place_order(self, order: Order) -> ExecutionReport:
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        ...

    @abstractmethod
    async def get_account_state(self) -> AccountState:
        ...

    @abstractmethod
    def stream_market_data(self, symbols: list[str]) -> AsyncIterator[Tick]:
        ...

    @abstractmethod
    async def get_historical_data(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        ...
