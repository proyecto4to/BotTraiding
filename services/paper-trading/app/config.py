"""Fill-model and account configuration for the simulated broker.

Every parameter is read from the environment at request time
(FillConfig.from_env) so operators can tune the simulation without a
redeploy and tests can monkeypatch individual env vars per case.

Fill model (see app/engine.py for the exact application):
- spread_bps: full bid/ask spread in basis points; half is charged per fill.
- slippage_bps: fixed slippage term in basis points.
- size_impact_bps_per_unit: size-impact slippage term; multiplied by the
  *requested* order quantity and added to the slippage (larger orders move
  the simulated market more).
- commission_bps + commission_per_unit: commission = notional * bps/10000
  + per_unit * filled_quantity (both terms always applied; set to 0 to
  disable one).
- max_fill_quantity: orders larger than this fill partially (0 = no cap).
- latency_ms: simulated broker latency before the fill is produced.
- default_starting_cash: cash for accounts auto-created on first order.
- allow_short: when false, sells beyond the held quantity are rejected
  with reason "insufficient_position".
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class FillConfig:
    spread_bps: float
    slippage_bps: float
    size_impact_bps_per_unit: float
    commission_bps: float
    commission_per_unit: float
    max_fill_quantity: float  # 0 => unlimited (no partial fills)
    latency_ms: float
    default_starting_cash: float
    allow_short: bool

    @classmethod
    def from_env(cls) -> "FillConfig":
        return cls(
            spread_bps=_f("PAPER_SPREAD_BPS", 2.0),
            slippage_bps=_f("PAPER_SLIPPAGE_BPS", 1.0),
            size_impact_bps_per_unit=_f("PAPER_SIZE_IMPACT_BPS_PER_UNIT", 0.0),
            commission_bps=_f("PAPER_COMMISSION_BPS", 1.0),
            commission_per_unit=_f("PAPER_COMMISSION_PER_UNIT", 0.0),
            max_fill_quantity=_f("PAPER_MAX_FILL_QUANTITY", 0.0),
            latency_ms=_f("PAPER_LATENCY_MS", 0.0),
            default_starting_cash=_f("PAPER_DEFAULT_STARTING_CASH", 100_000.0),
            allow_short=os.environ.get("PAPER_ALLOW_SHORT", "true").lower()
            in ("1", "true", "yes"),
        )


def get_fill_config() -> FillConfig:
    """FastAPI dependency seam (overridable in tests)."""
    return FillConfig.from_env()
