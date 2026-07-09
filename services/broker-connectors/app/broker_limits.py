"""Per-broker rate limit defaults (Fase 3 - seccion "Rate Limits").

These numbers are approximate/published defaults for scaffolding purposes
only - they are NOT guaranteed to be accurate to each provider's current
documentation. Refine per broker before going anywhere near production
traffic. Values are expressed as (capacity, refill_per_second) for the
token-bucket rate limiter in ``app/rate_limiter.py``.
"""

from __future__ import annotations

from typing import NamedTuple


class RateLimitConfig(NamedTuple):
    capacity: int
    refill_per_second: float


# Approximate limits (burst capacity, sustained refill rate/sec).
BROKER_RATE_LIMITS: dict[str, RateLimitConfig] = {
    # IBKR Client Portal Gateway: ~50 req/sec published guidance.
    "interactive_brokers": RateLimitConfig(capacity=50, refill_per_second=50.0),
    # Binance: 1200 request-weight/min ~= 20/sec.
    "binance": RateLimitConfig(capacity=1200, refill_per_second=20.0),
    # Bybit: ~120 req in a rolling window for most v5 endpoints.
    "bybit": RateLimitConfig(capacity=120, refill_per_second=10.0),
    # Kraken: notoriously strict, tiered token-bucket (~1 req/sec public tier).
    "kraken": RateLimitConfig(capacity=15, refill_per_second=1.0),
    "okx": RateLimitConfig(capacity=60, refill_per_second=20.0),
    "oanda": RateLimitConfig(capacity=100, refill_per_second=30.0),
    # MetaTrader5 terminal calls are local IPC, not network-limited the same
    # way; a generous default is used to avoid throttling local calls.
    "metatrader5": RateLimitConfig(capacity=200, refill_per_second=50.0),
    # Alpaca: 200 req/min ~= 3.33/sec.
    "alpaca": RateLimitConfig(capacity=200, refill_per_second=3.33),
}

DEFAULT_RATE_LIMIT = RateLimitConfig(capacity=60, refill_per_second=1.0)


def get_rate_limit(broker: str) -> tuple[int, float]:
    """Return (capacity, refill_per_second) for a broker, falling back to a
    conservative default for brokers not in the table."""
    cfg = BROKER_RATE_LIMITS.get(broker, DEFAULT_RATE_LIMIT)
    return cfg.capacity, cfg.refill_per_second
