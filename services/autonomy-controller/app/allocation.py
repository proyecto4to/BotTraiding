"""Capital allocation (P7): turn AI weights into a per-strategy budget.

The AI decides WHICH strategies to run; this decides HOW MUCH each gets. Each
selected strategy's share of the deployable budget (and its per-trade risk) is
proportional to its AI weight, capped so no single position dominates. The
totals never exceed the budget; the Risk Engine still has the final say on
every individual order.
"""

from __future__ import annotations

from . import config


def build_allocation_plan(
    selection: list[dict],
    *,
    deployable: float | None = None,
    base_risk: float | None = None,
    max_per_symbol: float | None = None,
) -> list[dict]:
    """Enrich each selection item with share/capital_fraction/risk_per_trade.

    share_i          = weight_i / sum(weights)        (equal split if no weights)
    capital_fraction = min(deployable * share_i, max_per_symbol)
    risk_per_trade   = base_risk * share_i

    sum(capital_fraction) <= deployable and sum(risk_per_trade) <= base_risk,
    so the budget is never exceeded.
    """
    deployable = deployable if deployable is not None else config.deployable_fraction()
    base_risk = base_risk if base_risk is not None else config.base_risk_per_trade()
    max_per_symbol = (
        max_per_symbol if max_per_symbol is not None else config.max_exposure_per_symbol()
    )

    weights = [max(float(s.get("weight", 0.0) or 0.0), 0.0) for s in selection]
    total = sum(weights)
    n = len(selection)

    enriched: list[dict] = []
    for item, weight in zip(selection, weights):
        share = (weight / total) if total > 0 else (1.0 / n if n else 0.0)
        capital_fraction = min(deployable * share, max_per_symbol)
        out = dict(item)
        out["share"] = round(share, 6)
        out["capital_fraction"] = round(capital_fraction, 6)
        out["risk_per_trade"] = round(base_risk * share, 6)
        enriched.append(out)
    return enriched


def allocation_of(item: dict) -> dict:
    """The bot-facing risk_allocation payload for a selection item."""
    return {
        "capital_fraction": item.get("capital_fraction", 0.0),
        "risk_per_trade": item.get("risk_per_trade", 0.0),
    }


def allocation_changed(current: dict | None, new: dict, *, threshold: float | None = None) -> bool:
    """True when the bot's risk_per_trade drifted enough to warrant a rebalance."""
    threshold = threshold if threshold is not None else config.rebalance_threshold()
    cur = float((current or {}).get("risk_per_trade", 0.0) or 0.0)
    nxt = float(new.get("risk_per_trade", 0.0) or 0.0)
    if cur == 0.0:
        return nxt != 0.0
    return abs(nxt - cur) / abs(cur) > threshold
