"""Strategy registry: decorator-based registration + package discovery.

Designed for a library of 1000+ strategies:
- registration is O(1) and validates metadata/param schema up front, so a
  broken plugin fails fast at import time, not at trade time;
- secondary indexes by category/market/timeframe make filtered listing
  O(matching set) instead of scanning every class;
- ``discover()`` imports every module under ``trading_strategies.builtins``
  (or any other package), so adding strategy #1001 is just adding a module
  with a ``@register_strategy`` class - no central list to edit.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict
from collections.abc import Iterator
from typing import Any, Optional

from .categories import StrategyCategory
from .plugin import ParameterValidationError, StrategyPlugin


class DuplicateStrategyError(ValueError):
    pass


class UnknownStrategyError(KeyError):
    pass


class StrategyRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, type[StrategyPlugin]] = {}
        self._by_category: dict[str, set[str]] = defaultdict(set)
        self._by_market: dict[str, set[str]] = defaultdict(set)
        self._by_timeframe: dict[str, set[str]] = defaultdict(set)

    # --- registration -------------------------------------------------------

    def register(self, cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
        if not (isinstance(cls, type) and issubclass(cls, StrategyPlugin)):
            raise TypeError("register expects a StrategyPlugin subclass")
        sid = cls.strategy_id
        if not sid:
            raise ValueError(f"{cls.__name__} must define a non-empty strategy_id")
        existing = self._classes.get(sid)
        if existing is cls:  # idempotent re-registration (module reloads)
            return cls
        if existing is not None:
            raise DuplicateStrategyError(
                f"strategy_id '{sid}' already registered by {existing.__name__}"
            )
        if not isinstance(cls.category, StrategyCategory):
            raise ValueError(f"{cls.__name__}.category must be a StrategyCategory")
        if not cls.name:
            raise ValueError(f"{cls.__name__} must define a display name")
        try:  # defaults must satisfy their own schema
            cls.validate_params({})
        except ParameterValidationError as exc:
            raise ValueError(
                f"{cls.__name__} default parameters are invalid: {exc}"
            ) from exc

        self._classes[sid] = cls
        self._by_category[cls.category.value].add(sid)
        for market in cls.markets:
            self._by_market[market].add(sid)
        for tf in cls.timeframes:
            self._by_timeframe[tf].add(sid)
        return cls

    # --- lookup ---------------------------------------------------------------

    def get(self, strategy_id: str) -> type[StrategyPlugin]:
        try:
            return self._classes[strategy_id]
        except KeyError:
            raise UnknownStrategyError(strategy_id) from None

    def create(
        self, strategy_id: str, params: Optional[dict[str, Any]] = None
    ) -> StrategyPlugin:
        return self.get(strategy_id)(params)

    def ids(
        self,
        category: Optional[str] = None,
        market: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> list[str]:
        """Filtered, sorted strategy ids using the secondary indexes."""
        result: Optional[set[str]] = None
        for index, key in (
            (self._by_category, category),
            (self._by_market, market),
            (self._by_timeframe, timeframe),
        ):
            if key is None:
                continue
            matched = index.get(key, set())
            result = matched.copy() if result is None else (result & matched)
        if result is None:
            result = set(self._classes)
        return sorted(result)

    def all(self) -> Iterator[type[StrategyPlugin]]:
        for sid in sorted(self._classes):
            yield self._classes[sid]

    def categories(self) -> dict[str, int]:
        return {cat: len(ids) for cat, ids in sorted(self._by_category.items())}

    def __contains__(self, strategy_id: object) -> bool:
        return strategy_id in self._classes

    def __len__(self) -> int:
        return len(self._classes)


#: Default process-wide registry used by ``@register_strategy``.
registry = StrategyRegistry()


def register_strategy(cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
    """Class decorator registering a plugin in the default registry."""
    return registry.register(cls)


def discover(package: str = "trading_strategies.builtins") -> StrategyRegistry:
    """Import every module under *package* so decorators register plugins.

    Idempotent: already-imported modules are cached and re-registration of
    the same class is a no-op.
    """
    pkg = importlib.import_module(package)
    for module_info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        importlib.import_module(module_info.name)
    return registry
