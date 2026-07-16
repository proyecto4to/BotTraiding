"""State machine transitions."""

from __future__ import annotations

import pytest
from app import db as db_module
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


def test_starts_off():
    with _session() as db:
        assert sm.get_state(db).state == sm.OFF


def test_enable_goes_to_learning():
    with _session() as db:
        row = sm.enable(db, actor="op")
        assert row.state == sm.LEARNING
        assert sm.presentation(row)["enabled"] is True


def test_enable_is_idempotent_when_active():
    with _session() as db:
        sm.enable(db)
        sm.promote_to_paper(db)
        row = sm.enable(db)  # already active -> unchanged
        assert row.state == sm.TRADING_PAPER


def test_disable_goes_off():
    with _session() as db:
        sm.enable(db)
        row = sm.disable(db)
        assert row.state == sm.OFF
        assert sm.presentation(row)["enabled"] is False


def test_halt_and_reset():
    with _session() as db:
        sm.enable(db)
        halted = sm.halt(db, reason="drawdown")
        assert halted.state == sm.HALTED
        assert "drawdown" in halted.reason
        row = sm.reset(db)
        assert row.state == sm.OFF


def test_enable_from_halted_is_rejected():
    with _session() as db:
        sm.enable(db)
        sm.halt(db, reason="x")
        with pytest.raises(sm.InvalidTransition):
            sm.enable(db)


def test_reset_only_from_halted():
    with _session() as db:
        sm.enable(db)
        with pytest.raises(sm.InvalidTransition):
            sm.reset(db)


def test_promote_to_paper_only_from_learning():
    with _session() as db:
        row = sm.get_state(db)  # OFF
        assert sm.promote_to_paper(db).state == row.state  # no-op from OFF
        sm.enable(db)  # LEARNING
        assert sm.promote_to_paper(db).state == sm.TRADING_PAPER
