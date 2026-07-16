"""Request/response models for autonomy-controller."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StateOut(BaseModel):
    state: str
    enabled: bool
    mode: str
    recommendation: str
    reason: Optional[str] = None
    updated_at: Optional[str] = None


class HaltRequest(BaseModel):
    reason: str = "manual kill switch"


class DecisionOut(BaseModel):
    id: str
    created_at: datetime
    state: str
    summary: str
    regime: dict = Field(default_factory=dict)
    selection: list = Field(default_factory=list)
    actions: list = Field(default_factory=list)
    errors: list = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TickResult(BaseModel):
    state: str
    acted: bool
    summary: str
    selection: list = Field(default_factory=list)
    actions: list = Field(default_factory=list)
    governor: list = Field(default_factory=list)
    errors: list = Field(default_factory=list)


class GovernorActionOut(BaseModel):
    """One audited strategy lifecycle decision (P5)."""

    id: str
    created_at: datetime
    strategy_key: str
    action: str
    mode: str
    status: str
    reason: str
    rule: Optional[str] = None
    severity: Optional[str] = None
    recommendation_id: Optional[str] = None

    model_config = {"from_attributes": True}


class GovernorStatusOut(BaseModel):
    """Governor mode + guardrails + recent actions (newest first)."""

    mode: str
    max_changes_per_window: int
    window_minutes: float
    actions: list[GovernorActionOut] = Field(default_factory=list)


class GateOut(BaseModel):
    name: str
    passed: bool
    detail: str


class ReadinessOut(BaseModel):
    """Paper -> live promotion readiness (P18)."""

    ready: bool
    state: str
    gates: list[GateOut] = Field(default_factory=list)
