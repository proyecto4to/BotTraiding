"""Request/response models for the optimizer API (Fase 12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .validation import PromotionDecision


class OptimizeRequest(BaseModel):
    strategy_key: str
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    search_type: Literal["grid", "random"] = "grid"
    #: number of parameter candidates to evaluate.
    budget: int = Field(default=16, ge=1, le=500)
    seed: Optional[int] = None
    #: walk-forward protocol shape.
    n_windows: int = Field(default=3, ge=1, le=20)
    is_fraction: float = Field(default=0.75, gt=0.0, lt=1.0)
    #: params currently live (baseline). Empty -> the plugin's defaults.
    current_params: dict[str, Any] = Field(default_factory=dict)
    initial_capital: float = Field(default=10_000.0, gt=0.0)
    frictions: dict[str, Any] = Field(default_factory=dict)
    #: apply the winning params to strategy-engine IF the gate passes.
    promote: bool = False

    @model_validator(mode="after")
    def _range_ok(self) -> "OptimizeRequest":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class OptimizationResultOut(BaseModel):
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    out_of_sample: bool
    window_index: int
    role: str


class OptimizationRunOut(BaseModel):
    id: str
    strategy_key: str
    strategy_version: Optional[str] = None
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    search_type: str
    budget: int
    status: str
    baseline_params: dict[str, Any] = Field(default_factory=dict)
    best_params: Optional[dict[str, Any]] = None
    promoted: bool = False
    applied: bool = False
    decision: Optional[PromotionDecision] = None
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class OptimizationRunDetail(OptimizationRunOut):
    results: list[OptimizationResultOut] = Field(default_factory=list)
