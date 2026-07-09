"""Circuit breaker state machine: NORMAL -> SOFT_HALT -> HARD_HALT -> reset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import circuit_breaker as cb
from app.limits import default_limits

ACC = "acc-cb"


def metrics(daily=0.0, dd=0.0, errors=0):
    return cb.BreakerMetrics(daily_loss_fraction=daily, drawdown=dd, error_count=errors)


def test_defaults_to_normal(db_session):
    row = cb.get_breaker(db_session, ACC)
    assert row.state == "NORMAL"


def test_at_threshold_does_not_trip(db_session):
    # soft daily-loss default == max_daily_loss (0.03); AT the limit the
    # plain risk check already rejects -- the breaker trips strictly above.
    row, escalated = cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.03))
    assert escalated is False
    assert row.state == "NORMAL"


def test_normal_to_soft_on_daily_loss(db_session):
    row, escalated = cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.031))
    assert escalated is True
    assert row.state == "SOFT_HALT"
    assert "daily_loss" in row.reason


def test_normal_to_hard_on_daily_loss(db_session):
    # hard default = 1.5 * 0.03 = 0.045
    row, _ = cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.046))
    assert row.state == "HARD_HALT"


def test_soft_to_hard_escalation(db_session):
    cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.031))
    row, escalated = cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.05))
    assert escalated is True
    assert row.state == "HARD_HALT"


def test_never_de_escalates_automatically(db_session):
    cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.031))
    row, escalated = cb.evaluate(db_session, ACC, default_limits(), metrics())
    assert escalated is False
    assert row.state == "SOFT_HALT"


def test_drawdown_thresholds(db_session):
    row, _ = cb.evaluate(db_session, ACC, default_limits(), metrics(dd=0.201))
    assert row.state == "SOFT_HALT"
    row, _ = cb.evaluate(db_session, ACC, default_limits(), metrics(dd=0.26))  # > 0.25 hard
    assert row.state == "HARD_HALT"


def test_error_rate_with_custom_thresholds(db_session):
    limits = default_limits().model_copy(
        update={"circuit_breaker_thresholds": {"errors_soft": 2, "errors_hard": 5}}
    )
    for _ in range(3):
        cb.record_error(db_session, ACC)
    count = cb.current_error_count(cb.get_breaker(db_session, ACC))
    assert count == 3

    row, _ = cb.evaluate(db_session, ACC, limits, metrics(errors=count))
    assert row.state == "SOFT_HALT"

    for _ in range(3):
        cb.record_error(db_session, ACC)
    count = cb.current_error_count(cb.get_breaker(db_session, ACC))
    row, _ = cb.evaluate(db_session, ACC, limits, metrics(errors=count))
    assert row.state == "HARD_HALT"


def test_error_window_expiry(db_session):
    row = cb.get_breaker(db_session, ACC)
    row.error_count = 99
    row.error_window_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        seconds=cb.ERROR_WINDOW_SECONDS + 10
    )
    db_session.flush()
    assert cb.current_error_count(row) == 0
    # a new error restarts the window at 1
    assert cb.record_error(db_session, ACC) == 1


def test_reset_returns_to_normal_and_clears_errors(db_session):
    cb.record_error(db_session, ACC)
    cb.evaluate(db_session, ACC, default_limits(), metrics(daily=0.99))
    assert cb.get_breaker(db_session, ACC).state == "HARD_HALT"

    row = cb.reset(db_session, ACC)
    assert row.state == "NORMAL"
    assert row.reason is None
    assert row.error_count == 0
    assert row.error_window_start is None
