"""Sync the code registry into the database on startup.

Contract: the code registry is the source of truth for strategy code and
metadata; the DB owns operational state (enable/disable) and per-user
configs. Sync therefore upserts metadata but NEVER touches `enabled`.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from trading_strategies import StrategyRegistry
from trading_strategies.plugin import StrategyPlugin

from .models import StrategyRecord, StrategyVersionRecord

logger = logging.getLogger("strategy-engine.sync")


def ensure_strategy_rows(
    session: Session, cls: type[StrategyPlugin]
) -> tuple[StrategyRecord, StrategyVersionRecord]:
    """Get-or-create the strategies/strategy_versions rows for a plugin."""
    info = cls.describe()
    row = (
        session.query(StrategyRecord)
        .filter_by(strategy_key=info["id"])
        .one_or_none()
    )
    if row is None:
        row = StrategyRecord(
            strategy_key=info["id"],
            name=info["name"],
            category=info["category"],
            description=info["description"],
            markets=info["markets"],
            timeframes=info["timeframes"],
            enabled=True,
        )
        session.add(row)
        session.flush()
    else:  # refresh metadata from code; preserve `enabled`
        row.name = info["name"]
        row.category = info["category"]
        row.description = info["description"]
        row.markets = info["markets"]
        row.timeframes = info["timeframes"]

    version = (
        session.query(StrategyVersionRecord)
        .filter_by(strategy_id=row.id, version=info["version"])
        .one_or_none()
    )
    if version is None:
        version = StrategyVersionRecord(
            strategy_id=row.id,
            version=info["version"],
            parameters={spec["name"]: spec for spec in info["parameters"]},
        )
        session.add(version)
        session.flush()
    else:
        version.parameters = {spec["name"]: spec for spec in info["parameters"]}
    return row, version


def sync_registry(session: Session, registry: StrategyRegistry) -> int:
    """Upsert every registered strategy; returns how many were synced."""
    count = 0
    for cls in registry.all():
        ensure_strategy_rows(session, cls)
        count += 1
    session.commit()
    logger.info("synced %d strategies from code registry into DB", count)
    return count
