"""Check plumbing: every risk check is a class with a stable `name` and a
pure `run(ctx) -> CheckResult`. Results feed RiskDecision.risk_checks_passed
/ risk_checks_failed; `reason` is machine-readable ("metric=value>limit").

Boundary convention: a metric exactly at its limit PASSES; strictly over it
fails. Checks that need data the signal/state does not carry fail safe when
the corresponding limit is enabled, and pass with a note when disabled.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.context import ValidationContext


@dataclass
class CheckResult:
    name: str
    passed: bool
    reason: str = ""
    value: Optional[float] = None
    limit: Optional[float] = None


class RiskCheck(ABC):
    name: str = "check"

    @abstractmethod
    def run(self, ctx: ValidationContext) -> CheckResult:  # pragma: no cover - interface
        ...

    def _pass(self, reason: str = "", value: float | None = None, limit: float | None = None):
        return CheckResult(self.name, True, reason, value, limit)

    def _fail(self, reason: str, value: float | None = None, limit: float | None = None):
        return CheckResult(self.name, False, reason, value, limit)

    def limit_check(self, value: float, limit: float, metric: str) -> CheckResult:
        """value <= limit passes (boundary inclusive)."""
        if value <= limit:
            return self._pass(f"{metric}={value:.6g}<={limit:.6g}", value, limit)
        return self._fail(f"{metric}={value:.6g}>{limit:.6g}", value, limit)
