"""Loads the shared trading_strategies registry for this service.

Discovery runs at import time: it is cheap, deterministic and idempotent,
so both the FastAPI lifespan and the test suite see a fully populated
registry without extra wiring.
"""

from __future__ import annotations

from trading_strategies import StrategyRegistry, discover


def load_registry() -> StrategyRegistry:
    """Discover builtin strategies (idempotent) and return the registry."""
    return discover("trading_strategies.builtins")


registry: StrategyRegistry = load_registry()
