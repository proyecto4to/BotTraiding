"""StrategyPlugin: the Fase 5/6 base class every library strategy extends.

Builds on the shared ``Strategy`` ABC (trading_contracts) and adds the
Fase 6 catalogue metadata: description, typed parameter schema
(name/type/default/min/max), compatible markets/timeframes, recommended
risk, historical-metrics placeholder and version.

Key invariant (docs/ARCHITECTURE.md, principle 3): strategies only
PROPOSE ``TradeSignal``s; sizing/approval belongs to the Risk Engine, so
``suggested_size`` is always an advisory 1.0 unit here.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from typing import Any, ClassVar, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from trading_contracts import (
    Bar,
    OrderSide,
    Strategy,
    StrategyContext,
    StrategyMetadata,
    TradeSignal,
)

from .categories import StrategyCategory

ParamType = Literal["int", "float", "bool", "str"]


class ParameterSpec(BaseModel):
    """One configurable parameter: name/type/default plus optional bounds."""

    name: str
    type: ParamType
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list[Any]] = None
    description: str = ""


class ParameterValidationError(ValueError):
    """Raised when user-supplied parameters do not satisfy the schema."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def atr_exit_specs(
    atr_period: int = 14, stop_mult: float = 2.0, risk_reward: float = 2.0
) -> tuple[ParameterSpec, ...]:
    """Common ATR-based stop-loss / take-profit parameters."""
    return (
        ParameterSpec(
            name="atr_period",
            type="int",
            default=atr_period,
            min=2,
            max=100,
            description="ATR lookback used for stop/target placement.",
        ),
        ParameterSpec(
            name="stop_atr_mult",
            type="float",
            default=stop_mult,
            min=0.25,
            max=10.0,
            description="Stop distance in ATR multiples.",
        ),
        ParameterSpec(
            name="risk_reward",
            type="float",
            default=risk_reward,
            min=0.5,
            max=10.0,
            description="Take-profit distance as a multiple of the stop distance.",
        ),
    )


def _check_type(spec: ParameterSpec, value: Any) -> tuple[Any, Optional[str]]:
    """Validate/coerce one value against its spec. Returns (coerced, error)."""
    t = spec.type
    if t == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, f"'{spec.name}' must be an integer"
        if isinstance(value, float):
            if not value.is_integer():
                return value, f"'{spec.name}' must be an integer"
            value = int(value)
    elif t == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value, f"'{spec.name}' must be a number"
        value = float(value)
    elif t == "bool":
        if not isinstance(value, bool):
            return value, f"'{spec.name}' must be a boolean"
    elif t == "str":
        if not isinstance(value, str):
            return value, f"'{spec.name}' must be a string"
    if spec.choices is not None and value not in spec.choices:
        return value, f"'{spec.name}' must be one of {spec.choices}"
    if spec.min is not None and isinstance(value, (int, float)) and value < spec.min:
        return value, f"'{spec.name}' must be >= {spec.min} (got {value})"
    if spec.max is not None and isinstance(value, (int, float)) and value > spec.max:
        return value, f"'{spec.name}' must be <= {spec.max} (got {value})"
    return value, None


class StrategyPlugin(Strategy):
    """Base class for all library strategies (Fase 5 plugins).

    Subclasses declare class-level metadata and implement ``_evaluate``.
    """

    # --- Fase 6 catalogue metadata (override in subclasses) ---------------
    strategy_id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    category: ClassVar[StrategyCategory] = StrategyCategory.TREND
    markets: ClassVar[tuple[str, ...]] = ()
    timeframes: ClassVar[tuple[str, ...]] = ()
    description: ClassVar[str] = ""
    param_specs: ClassVar[tuple[ParameterSpec, ...]] = ()
    recommended_risk_per_trade: ClassVar[float] = 0.01
    #: Placeholder until the backtester (Fase 8) persists real metrics.
    historical_metrics: ClassVar[dict[str, float]] = {}

    def __init__(self, params: Optional[dict[str, Any]] = None) -> None:
        self.params: dict[str, Any] = self.validate_params(params or {})
        self._active_market: Optional[str] = None

    # --- parameter schema ---------------------------------------------------

    @classmethod
    def validate_params(cls, overrides: dict[str, Any]) -> dict[str, Any]:
        """Merge *overrides* over defaults, validating types/bounds.

        Raises ``ParameterValidationError`` listing every problem found.
        """
        specs = {s.name: s for s in cls.param_specs}
        errors: list[str] = []
        coerced: dict[str, Any] = {}
        for key, value in (overrides or {}).items():
            spec = specs.get(key)
            if spec is None:
                errors.append(f"unknown parameter '{key}'")
                continue
            val, err = _check_type(spec, value)
            if err:
                errors.append(err)
            else:
                coerced[key] = val
        if errors:
            raise ParameterValidationError(errors)
        merged = {s.name: s.default for s in cls.param_specs}
        merged.update(coerced)
        cross_errors = cls.check_params(merged)
        if cross_errors:
            raise ParameterValidationError(list(cross_errors))
        return merged

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        """Cross-field validation hook (e.g. fast < slow). Returns errors."""
        return []

    # --- Strategy ABC contract ----------------------------------------------

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            id=self.strategy_id,
            name=self.name,
            version=self.version,
            category=self.category.value,
            markets=list(self.markets),
            timeframes=list(self.timeframes),
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON-schema-like dict (Strategy ABC contract, seccion 5.5)."""
        props: dict[str, Any] = {}
        for spec in self.param_specs:
            prop: dict[str, Any] = {"type": spec.type, "default": spec.default}
            if spec.min is not None:
                prop["minimum"] = spec.min
            if spec.max is not None:
                prop["maximum"] = spec.max
            if spec.choices is not None:
                prop["enum"] = spec.choices
            if spec.description:
                prop["description"] = spec.description
            props[spec.name] = prop
        return {"type": "object", "properties": props, "additionalProperties": False}

    def required_filters(self) -> list[str]:
        return []

    def on_bar(self, context: StrategyContext) -> Optional[TradeSignal]:
        """Adapter from the shared StrategyContext to ``evaluate``.

        Expects ``context.data["bars"]`` to be a list of Bars (or dicts)
        and optionally ``context.data["market"]``.
        """
        bars = context.data.get("bars") or []
        return self.evaluate(bars, market=context.data.get("market"))

    # --- evaluation -----------------------------------------------------------

    def evaluate(
        self,
        bars: Sequence[Bar | dict[str, Any]],
        market: Optional[str] = None,
    ) -> Optional[TradeSignal]:
        """Evaluate the strategy over a Bar sequence (oldest first).

        Returns a ``TradeSignal`` when the LAST bar triggers an entry,
        else ``None``. This is the seam the strategy-engine evaluate
        endpoint and the backtester (Fase 8) call.
        """
        if not bars:
            return None
        coerced = [b if isinstance(b, Bar) else Bar.model_validate(b) for b in bars]
        self._active_market = market
        try:
            return self._evaluate(coerced)
        finally:
            self._active_market = None

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        raise NotImplementedError

    # --- catalogue ------------------------------------------------------------

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Full Fase 6 metadata used by the API/DB sync."""
        doc = cls.description or (cls.__doc__ or "")
        return {
            "id": cls.strategy_id,
            "name": cls.name,
            "version": cls.version,
            "category": cls.category.value,
            "markets": list(cls.markets),
            "timeframes": list(cls.timeframes),
            "description": textwrap.dedent(doc).strip(),
            "parameters": [spec.model_dump() for spec in cls.param_specs],
            "recommended_risk_per_trade": cls.recommended_risk_per_trade,
            "historical_metrics": dict(cls.historical_metrics),
        }

    # --- helpers for subclasses -------------------------------------------------

    @staticmethod
    def _closes(bars: Sequence[Bar]) -> list[float]:
        return [b.close for b in bars]

    @staticmethod
    def _highs(bars: Sequence[Bar]) -> list[float]:
        return [b.high for b in bars]

    @staticmethod
    def _lows(bars: Sequence[Bar]) -> list[float]:
        return [b.low for b in bars]

    @staticmethod
    def _volumes(bars: Sequence[Bar]) -> list[float]:
        return [b.volume for b in bars]

    def _atr_exits(
        self, entry: float, side: OrderSide, atr_value: float
    ) -> tuple[Optional[float], Optional[float]]:
        """ATR-multiple stop plus risk-reward take profit."""
        mult = float(self.params.get("stop_atr_mult", 2.0))
        rr = float(self.params.get("risk_reward", 2.0))
        risk = mult * atr_value
        if not (risk > 0.0):
            return None, None
        if side is OrderSide.BUY:
            return entry - risk, entry + rr * risk
        return entry + risk, entry - rr * risk

    def _signal(
        self,
        bars: Sequence[Bar],
        side: OrderSide,
        confidence: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> TradeSignal:
        """Build a deterministic TradeSignal from the last bar.

        ``generated_at`` is the last bar's timestamp so identical inputs
        produce identical signals (except the random ``id``).
        """
        last = bars[-1]
        md: dict[str, Any] = {
            "entry_price": last.close,
            "strategy_version": self.version,
        }
        md.update(metadata or {})
        return TradeSignal(
            id=uuid4(),
            strategy_id=self.strategy_id,
            symbol=last.symbol,
            market=self._active_market
            or (self.markets[0] if self.markets else "any"),
            side=side,
            confidence=round(clamp(confidence), 4),
            timeframe=last.timeframe,
            suggested_size=1.0,
            stop_loss=None if stop_loss is None else round(float(stop_loss), 8),
            take_profit=None if take_profit is None else round(float(take_profit), 8),
            generated_at=last.timestamp,
            metadata=md,
        )
