"""trading_strategies: shared strategy plugin library (Fase 5/6).

Lives in services/shared/ because the backtester (Fase 8) must load the
exact same strategy code the strategy-engine serves. Strategies only
PROPOSE TradeSignals (docs/ARCHITECTURE.md, principle 3).

Usage:
    from trading_strategies import discover, registry
    discover()                       # loads all builtin strategies
    plugin = registry.create("sma_crossover", {"fast_period": 5})
    signal = plugin.evaluate(bars)
"""

from .categories import ALL_CATEGORIES, StrategyCategory
from .plugin import (
    ParameterSpec,
    ParameterValidationError,
    StrategyPlugin,
    atr_exit_specs,
)
from .registry import (
    DuplicateStrategyError,
    StrategyRegistry,
    UnknownStrategyError,
    discover,
    register_strategy,
    registry,
)

__all__ = [
    "ALL_CATEGORIES",
    "StrategyCategory",
    "ParameterSpec",
    "ParameterValidationError",
    "StrategyPlugin",
    "atr_exit_specs",
    "DuplicateStrategyError",
    "StrategyRegistry",
    "UnknownStrategyError",
    "discover",
    "register_strategy",
    "registry",
]


def load_builtin_strategies() -> StrategyRegistry:
    """Convenience alias: discover the builtin strategy package."""
    return discover("trading_strategies.builtins")
