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
    errors: list = Field(default_factory=list)
