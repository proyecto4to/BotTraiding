"""Autonomy state machine.

    OFF --enable--> LEARNING --(data+selection)--> TRADING_PAPER
     ^                                                   |
     |                                       (gates + admin, future P18)
     +--disable-- (any) --halt--> HALTED --reset--> OFF   |
                                    ^                      v
                                    +---- TRADING_LIVE ----+

- OFF: nothing operates.
- LEARNING: gathering data / first ticks; not yet acting on bots.
- TRADING_PAPER: acting in paper (default "on" state).
- TRADING_LIVE: only via explicit admin + paper->live gates (future).
- HALTED: forced by the kill switch / auto-halt; needs an admin reset.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import STATE_SINGLETON_ID, AutonomyStateRow

OFF = "OFF"
LEARNING = "LEARNING"
TRADING_PAPER = "TRADING_PAPER"
TRADING_LIVE = "TRADING_LIVE"
HALTED = "HALTED"

ACTIVE_STATES = {LEARNING, TRADING_PAPER, TRADING_LIVE}
TRADING_STATES = {TRADING_PAPER, TRADING_LIVE}


class InvalidTransition(Exception):
    """A requested transition is not allowed from the current state."""


def get_state(db: Session) -> AutonomyStateRow:
    row = db.get(AutonomyStateRow, STATE_SINGLETON_ID)
    if row is None:
        row = AutonomyStateRow(id=STATE_SINGLETON_ID, state=OFF, reason="initialised")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _set(db: Session, state: str, *, reason: str, actor: str | None) -> AutonomyStateRow:
    row = get_state(db)
    row.state = state
    row.reason = reason
    row.updated_by = actor
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return row


def enable(db: Session, *, actor: str | None = None) -> AutonomyStateRow:
    row = get_state(db)
    if row.state in ACTIVE_STATES:
        return row  # already on
    if row.state == HALTED:
        raise InvalidTransition("system is HALTED; reset before enabling")
    return _set(db, LEARNING, reason="enabled by operator", actor=actor)


def disable(db: Session, *, actor: str | None = None) -> AutonomyStateRow:
    return _set(db, OFF, reason="disabled by operator", actor=actor)


def halt(db: Session, *, reason: str, actor: str | None = None) -> AutonomyStateRow:
    """Kill switch / auto-halt: force HALTED (needs a reset to leave)."""
    return _set(db, HALTED, reason=reason, actor=actor)


def reset(db: Session, *, actor: str | None = None) -> AutonomyStateRow:
    row = get_state(db)
    if row.state != HALTED:
        raise InvalidTransition("reset is only valid from HALTED")
    return _set(db, OFF, reason="reset by operator", actor=actor)


def promote_to_paper(db: Session, *, actor: str | None = None) -> AutonomyStateRow:
    """LEARNING -> TRADING_PAPER once the first usable selection is produced."""
    row = get_state(db)
    if row.state == LEARNING:
        return _set(db, TRADING_PAPER, reason="learning complete; trading paper", actor=actor)
    return row


def promote_to_live(db: Session, *, actor: str | None = None) -> AutonomyStateRow:
    """TRADING_PAPER -> TRADING_LIVE. Only valid from paper; the promotion
    gates (app/gates.py) and admin confirmation are enforced by the caller."""
    row = get_state(db)
    if row.state != TRADING_PAPER:
        raise InvalidTransition("promotion to live is only valid from TRADING_PAPER")
    return _set(db, TRADING_LIVE, reason="promoted to live (gates passed)", actor=actor)


# --- presentation helpers (for the gateway master switch) --------------------

_RECOMMENDATION = {
    OFF: "Automation is off. Enable it to let the system trade on its own.",
    LEARNING: "Learning the market; will start paper trading shortly.",
    TRADING_PAPER: "Automation is active (paper). Risk controls remain enforced.",
    TRADING_LIVE: "Automation is active (LIVE). Risk controls remain enforced.",
    HALTED: "Automation HALTED by a safety trigger. Review and reset to resume.",
}


def presentation(row: AutonomyStateRow) -> dict:
    """Map the state to the {enabled, mode, recommendation} shape the dashboard
    master switch already consumes."""
    return {
        "state": row.state,
        "enabled": row.state in ACTIVE_STATES,
        "mode": row.state.lower(),
        "recommendation": _RECOMMENDATION.get(row.state, ""),
        "reason": row.reason,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
