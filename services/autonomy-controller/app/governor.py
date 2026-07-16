"""Strategy lifecycle governor (P5): the AI's advice finally acts.

Each tick (when the automation is active) the governor:

  1. reads ai-engine's persisted underperformance recommendations
     (GET /ai/recommendations) — the ONLY thing that can turn a strategy off;
  2. reads the strategy catalog state (GET /strategies);
  3. plans disables (enabled strategy + fresh validated recommendation) and
     enables (disabled strategy favored by the current regime selection, with
     no fresh disable recommendation standing against it);
  4. applies each plan via strategy-engine PATCH /strategies/{key} — but only
     in `active` mode and within the change cap.

Guardrails (all env-configurable, see config.py):

- a strategy is NEVER disabled without a validated, fresh recommendation
  (rule + reason + severity persisted by ai-engine);
- at most AUTONOMY_GOVERNOR_MAX_CHANGES applied changes per rolling window;
  excess plans are recorded as `capped` and retried in a later window;
- one action per (strategy, direction) per window — no flapping, no audit spam;
- every planned action (applied or not) is persisted (autonomy_governor_actions)
  and published (`autonomy.governor`);
- mode: `off` (skip) | `shadow` (default: record only) | `active` (apply).

Disabling here only flips the catalog flag; strategy-engine stops serving the
strategy and the bots' signals dry up — risk-engine still vets every order of
whatever remains enabled.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, events
from .clients import Clients, DownstreamError
from .models import GovernorActionRow

logger = logging.getLogger("autonomy-controller.governor")

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"


def resolved_mode() -> str:
    """The configured mode; anything unrecognized degrades to shadow (safe)."""
    raw = config.governor_mode()
    if raw in (MODE_OFF, MODE_SHADOW, MODE_ACTIVE):
        return raw
    logger.warning("unknown AUTONOMY_GOVERNOR_MODE %r; treating as shadow", raw)
    return MODE_SHADOW


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rec_created_at(rec: dict) -> datetime | None:
    raw = rec.get("created_at")
    if isinstance(raw, datetime):
        dt = raw
    elif raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _is_fresh(rec: dict, now: datetime) -> bool:
    """A recommendation without a parseable timestamp is never acted on."""
    created = _rec_created_at(rec)
    if created is None:
        return False
    return (now - created) <= timedelta(minutes=config.governor_rec_max_age_minutes())


def _decided_recently(db: Session, window_start: datetime) -> set[tuple[str, str]]:
    """(strategy_key, action) pairs already recorded in the window (dedup)."""
    rows = db.execute(
        select(GovernorActionRow.strategy_key, GovernorActionRow.action).where(
            GovernorActionRow.created_at >= window_start
        )
    ).all()
    return {(key, action) for key, action in rows}


def _applied_in_window(db: Session, window_start: datetime) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(GovernorActionRow)
            .where(
                GovernorActionRow.created_at >= window_start,
                GovernorActionRow.status == "applied",
            )
        ).scalar_one()
    )


def _plan(recs: list[dict], strategies: list[dict], selection: list[dict]) -> list[dict]:
    """Decide which catalog changes the AI's advice justifies right now."""
    now = _utcnow()
    enabled_by_key = {
        s["key"]: bool(s.get("enabled", True)) for s in strategies if s.get("key")
    }

    # Freshest disable recommendation per strategy (the API is newest-first).
    disable_recs: dict[str, dict] = {}
    for rec in recs:
        key = rec.get("strategy_key")
        if not key or rec.get("action") != "disable" or key in disable_recs:
            continue
        if _is_fresh(rec, now):
            disable_recs[key] = rec

    plans: list[dict] = []
    for key, rec in sorted(disable_recs.items()):
        if enabled_by_key.get(key):  # only known, currently-enabled strategies
            plans.append(
                {
                    "strategy_key": key,
                    "action": "disable",
                    "reason": rec.get("reason") or "ai underperformance recommendation",
                    "rule": rec.get("rule"),
                    "severity": rec.get("severity"),
                    "recommendation_id": (
                        str(rec["id"]) if rec.get("id") is not None else None
                    ),
                }
            )

    favored = {s.get("strategy_key") for s in selection if s.get("strategy_key")}
    for key in sorted(favored):
        if enabled_by_key.get(key) is False and key not in disable_recs:
            plans.append(
                {
                    "strategy_key": key,
                    "action": "enable",
                    "reason": "favored by the AI selection for the current regime",
                    "rule": None,
                    "severity": None,
                    "recommendation_id": None,
                }
            )
    return plans


async def run_governor(
    db: Session, clients: Clients, selection: list[dict], errors: list
) -> list[dict]:
    """One governor pass. Returns the actions taken/recorded this tick; every
    downstream failure is recorded in *errors* and never aborts the cycle."""
    mode = resolved_mode()
    if mode == MODE_OFF:
        return []

    try:
        recs = await clients.ai.recommendations(limit=100)
    except DownstreamError as exc:
        errors.append({"stage": "governor_recommendations", "error": str(exc)})
        return []
    try:
        strategies = await clients.strategies.list_strategies()
    except DownstreamError as exc:
        errors.append({"stage": "governor_strategies", "error": str(exc)})
        return []

    plans = _plan(recs, strategies, selection)
    if not plans:
        return []

    window_start = _utcnow() - timedelta(minutes=config.governor_window_minutes())
    decided = _decided_recently(db, window_start)
    budget = max(0, config.governor_max_changes() - _applied_in_window(db, window_start))

    actions: list[dict] = []
    for plan in plans:
        if (plan["strategy_key"], plan["action"]) in decided:
            continue  # already decided this window
        if mode == MODE_SHADOW:
            status = "shadow"
        elif budget <= 0:
            status = "capped"
        else:
            try:
                await clients.strategies.set_enabled(
                    plan["strategy_key"], plan["action"] == "enable"
                )
                status = "applied"
                budget -= 1
            except DownstreamError as exc:
                status = "failed"
                errors.append(
                    {
                        "stage": "governor_apply",
                        "strategy_key": plan["strategy_key"],
                        "error": str(exc),
                    }
                )

        row = GovernorActionRow(
            strategy_key=plan["strategy_key"],
            action=plan["action"],
            mode=mode,
            status=status,
            reason=plan["reason"],
            rule=plan["rule"],
            severity=plan["severity"],
            recommendation_id=plan["recommendation_id"],
        )
        db.add(row)
        db.commit()

        action = {
            "strategy_key": plan["strategy_key"],
            "action": plan["action"],
            "mode": mode,
            "status": status,
            "reason": plan["reason"],
        }
        await events.publish_event(
            "autonomy.governor",
            {**action, "rule": plan["rule"], "severity": plan["severity"]},
        )
        if status == "applied":
            logger.info(
                "governor %sd strategy '%s': %s",
                plan["action"], plan["strategy_key"], plan["reason"],
            )
        else:
            logger.info(
                "governor (%s) would %s strategy '%s': %s",
                status, plan["action"], plan["strategy_key"], plan["reason"],
            )
        actions.append(action)
    return actions


def recent_actions(db: Session, limit: int) -> list[GovernorActionRow]:
    return list(
        db.scalars(
            select(GovernorActionRow)
            .order_by(GovernorActionRow.created_at.desc(), GovernorActionRow.id.desc())
            .limit(limit)
        )
    )
