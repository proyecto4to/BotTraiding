"""min_paper_days must measure days TRADED, not days elapsed.

Taken from a real observation on the dev machine: the decision log showed 13.3
calendar days since the first paper cycle, but only 8 days had any activity at
all and the whole record amounted to roughly 18 hours of running. Subtracting
two dates reported "13.3 days of track record" for a bot that was switched off
most of the time, and the gate would have opened on the strength of the wall
clock alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app import controller
from app import db as db_module
from app import statemachine as sm
from app.models import AutonomyDecisionRow


def _session():
    return db_module.SessionLocal()


def _record(db, when: datetime, state: str = sm.TRADING_PAPER) -> None:
    db.add(
        AutonomyDecisionRow(
            state=state,
            summary="cycle",
            regime={},
            selection=[],
            actions=[],
            errors=[],
            created_at=when,
        )
    )


def test_counts_only_days_with_activity():
    """Two weeks of calendar, three days of actual trading."""
    start = datetime(2026, 7, 1, 9, 0)
    with _session() as db:
        _record(db, start)
        _record(db, start + timedelta(hours=2))       # same day again
        _record(db, start + timedelta(days=1))
        _record(db, start + timedelta(days=13))       # 14 calendar days later
        db.commit()

        assert controller.paper_trading_days(db) == 3.0


def test_a_long_gap_does_not_earn_days():
    """The exact shape of the real case: a burst, a long silence, a burst."""
    start = datetime(2026, 7, 1, 9, 0)
    with _session() as db:
        for hour in range(0, 10):
            _record(db, start + timedelta(hours=hour))
        for hour in range(0, 10):
            _record(db, start + timedelta(days=20, hours=hour))
        db.commit()

        # 20 calendar days apart, but the bot only ever traded on two days.
        assert controller.paper_trading_days(db) == 2.0


def test_only_paper_cycles_count():
    """Cycles skipped while OFF are not a track record."""
    start = datetime(2026, 7, 1, 9, 0)
    with _session() as db:
        _record(db, start, state=sm.OFF)
        _record(db, start + timedelta(days=1), state=sm.LEARNING)
        _record(db, start + timedelta(days=2), state=sm.TRADING_PAPER)
        db.commit()

        assert controller.paper_trading_days(db) == 1.0


def test_no_history_is_zero():
    with _session() as db:
        assert controller.paper_trading_days(db) == 0.0
