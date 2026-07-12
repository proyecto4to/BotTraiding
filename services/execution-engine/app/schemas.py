"""Request/response models for execution-engine.

ExecutionRequest carries the approved shared-contract Order together with
the RiskDecision that approved it (architecture principle 2.4: toda orden
pasa por el Risk Engine, sin bypass). Orders without an approved
RiskDecision are rejected with 422 before touching any transport.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from trading_contracts import ExecutionReport, Order, RiskDecision


class ExecutionRequest(BaseModel):
    order: Order
    risk_decision: RiskDecision  # required: missing -> 422 (invariant)
    market_price: Optional[float] = Field(
        default=None,
        gt=0,
        description="Current market price from the caller's market data; "
        "required by the paper transport for market orders.",
    )


class ChildOrderOut(BaseModel):
    id: str
    client_order_id: Optional[str] = None  # deterministic venue idempotency key
    sequence: int
    quantity: float
    status: str
    filled_quantity: float
    average_fill_price: Optional[float] = None
    attempts: int
    last_error: Optional[str] = None


class ExecutionOut(BaseModel):
    id: str
    order_id: str
    signal_id: str
    account_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    price: Optional[float] = None
    broker: str
    execution_mode: str
    status: str
    filled_quantity: float
    average_fill_price: Optional[float] = None
    requested_by: Optional[str] = None
    created_at: datetime
    child_orders: list[ChildOrderOut] = Field(default_factory=list)
    reports: list[ExecutionReport] = Field(default_factory=list)


class CancelResponse(BaseModel):
    execution_id: str
    status: str
    cancelled_children: int
    transport_cancelled: int


class ModeInfo(BaseModel):
    available: bool
    transport: str
    url: str


class ModesResponse(BaseModel):
    default_mode: str
    override_requires_admin: bool = True
    max_child_size: float
    modes: dict[str, ModeInfo]
