"""Request/response models for paper-trading.

The order API mirrors what execution-engine's paper transport needs; fill
results are shared-contract ExecutionReports (trading_contracts.models).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from trading_contracts import OrderSide, OrderType


class CreateAccountRequest(BaseModel):
    account_id: Optional[str] = None  # generated when omitted
    starting_cash: float = Field(default=100_000.0, gt=0)
    currency: str = "USD"


class PaperAccountResponse(BaseModel):
    account_id: str
    starting_cash: float
    cash: float
    positions_value: float = 0.0  # at average price (the simulator holds no marks)
    equity: float = 0.0  # cash + positions_value
    currency: str = "USD"
    created_at: datetime


class PaperOrderRequest(BaseModel):
    """Body of POST /paper/orders.

    ``price`` is the current market (mid) price supplied by the caller's
    market data; spread/slippage/size-impact are applied on top of it.
    """

    order_id: UUID
    client_order_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="caller idempotency key; a duplicate replays the original "
        "ExecutionReport instead of filling twice (defaults to order_id)",
    )
    signal_id: Optional[UUID] = None
    account_id: str
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    price: float = Field(gt=0, description="reference/mid market price from the caller")


class PaperOrderDetail(BaseModel):
    order_id: str
    client_order_id: Optional[str] = None
    account_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    filled_quantity: float
    average_fill_price: Optional[float] = None
    reference_price: float
    commission: float
    status: str
    raw: dict = Field(default_factory=dict)
    created_at: datetime
