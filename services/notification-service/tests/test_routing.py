"""Routing: preference matching, min-severity gating, retry + dead-letter."""

from __future__ import annotations

from sqlalchemy import select

from app import routing
from app.channels import set_senders
from app.models import DeadLetterRow, NotificationRow
from app.schemas import EventIn
from tests.conftest import FakeSender, make_pref


def _event(subject="risk.circuit_breaker", payload=None, **kwargs) -> EventIn:
    return EventIn(subject=subject, payload=payload or {"state": "HARD_HALT"}, **kwargs)


# ---------------------------------------------------------------------------
# subject_matches
# ---------------------------------------------------------------------------


def test_subject_matches_patterns() -> None:
    assert routing.subject_matches("risk.>", "risk.circuit_breaker")
    assert routing.subject_matches("risk.>", "risk.a.b.c")
    assert not routing.subject_matches("risk.>", "execution.report")
    assert routing.subject_matches("*.report", "execution.report")
    assert not routing.subject_matches("*.report", "execution.report.extra")
    assert routing.subject_matches("execution.live_order", "execution.live_order")
    assert not routing.subject_matches("execution.live_order", "execution.report")
    assert routing.subject_matches(">", "anything.at.all")


# ---------------------------------------------------------------------------
# preference routing
# ---------------------------------------------------------------------------


async def test_routes_to_matching_users_only(db_session) -> None:
    wants_risk = make_pref(subjects=["risk.>"], email="a@x.com")
    wants_exec = make_pref(subjects=["execution.>"], email="b@x.com")
    db_session.add_all([wants_risk, wants_exec])
    db_session.commit()

    sender = FakeSender("email")
    set_senders({"email": sender})

    rows = await routing.ingest_event(db_session, _event(subject="risk.circuit_breaker"))

    assert [r.user_id for r in rows] == [wants_risk.user_id]
    assert len(sender.calls) == 1
    notification, pref = sender.calls[0]
    assert notification["subject"] == "risk.circuit_breaker"
    assert notification["severity"] == "critical"
    assert pref.user_id == wants_risk.user_id
    assert rows[0].status == "sent"


async def test_min_severity_gates_channel(db_session) -> None:
    # email accepts info+, telegram only critical
    pref = make_pref(email="a@x.com", email_min="info", telegram="123", telegram_min="critical")
    db_session.add(pref)
    db_session.commit()

    email = FakeSender("email")
    telegram = FakeSender("telegram")
    set_senders({"email": email, "telegram": telegram})

    # info event -> email only
    await routing.ingest_event(
        db_session, _event(subject="risk.rejected", payload={"reason": "x"})
    )
    assert len(email.calls) == 1
    assert len(telegram.calls) == 0

    # critical event -> both
    await routing.ingest_event(db_session, _event(subject="risk.circuit_breaker"))
    assert len(email.calls) == 2
    assert len(telegram.calls) == 1


async def test_account_filter(db_session) -> None:
    pref = make_pref(account_ids=["acc-1"], email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email")
    set_senders({"email": sender})

    rows = await routing.ingest_event(
        db_session,
        EventIn(subject="risk.rejected", account_id="acc-2", payload={}),
    )
    # filtered out -> unrouted audit row only
    assert rows[0].user_id is None
    assert len(sender.calls) == 0

    rows = await routing.ingest_event(
        db_session,
        EventIn(subject="risk.rejected", account_id="acc-1", payload={}),
    )
    assert rows[0].user_id == pref.user_id
    assert len(sender.calls) == 1


async def test_directed_event_reaches_user_without_preferences(db_session) -> None:
    set_senders({})
    rows = await routing.ingest_event(
        db_session,
        EventIn(subject="bot.stopped", user_id="user-42", payload={}),
    )
    assert len(rows) == 1
    assert rows[0].user_id == "user-42"
    assert rows[0].status == "sent"  # persisted for the feed; nothing to deliver


async def test_unrouted_event_persisted_for_audit(db_session) -> None:
    set_senders({})
    rows = await routing.ingest_event(db_session, _event())
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].status == "sent"
    stored = db_session.execute(select(NotificationRow)).scalars().all()
    assert len(stored) == 1


async def test_explicit_severity_overrides_rules(db_session) -> None:
    db_session.add(make_pref(email="a@x.com"))
    db_session.commit()
    set_senders({"email": FakeSender("email")})
    rows = await routing.ingest_event(
        db_session,
        EventIn(subject="risk.rejected", severity="critical", payload={}),
    )
    assert rows[0].severity == "critical"


# ---------------------------------------------------------------------------
# retry / dead-letter
# ---------------------------------------------------------------------------


async def test_transient_then_success_retries(db_session, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "3")
    pref = make_pref(email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email", fail_times=2)  # succeed on 3rd attempt
    set_senders({"email": sender})

    rows = await routing.ingest_event(db_session, _event())

    assert rows[0].status == "sent"
    assert len(sender.calls) == 3
    assert db_session.execute(select(DeadLetterRow)).scalars().all() == []


async def test_retries_exhausted_dead_letters(db_session, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "2")
    pref = make_pref(email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email", fail_times=99)  # never succeeds
    set_senders({"email": sender})

    rows = await routing.ingest_event(db_session, _event())

    assert rows[0].status == "dead"
    assert len(sender.calls) == 3  # 1 initial + 2 retries
    letters = db_session.execute(select(DeadLetterRow)).scalars().all()
    assert len(letters) == 1
    assert letters[0].channel == "email"
    assert letters[0].retry_count == 3
    assert letters[0].notification_id == rows[0].id
    assert letters[0].target == "a@x.com"


async def test_permanent_failure_dead_letters_without_retry(db_session, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "5")
    pref = make_pref(email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email", permanent=True)
    set_senders({"email": sender})

    rows = await routing.ingest_event(db_session, _event())

    assert rows[0].status == "dead"
    assert len(sender.calls) == 1  # no retries for permanent errors
    letters = db_session.execute(select(DeadLetterRow)).scalars().all()
    assert len(letters) == 1
    assert letters[0].retry_count == 1


async def test_partial_failure_marks_failed(db_session, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "0")
    pref = make_pref(email="a@x.com", telegram="123")
    db_session.add(pref)
    db_session.commit()
    set_senders(
        {"email": FakeSender("email"), "telegram": FakeSender("telegram", fail_times=99)}
    )

    rows = await routing.ingest_event(db_session, _event())

    assert rows[0].status == "failed"
    letters = db_session.execute(select(DeadLetterRow)).scalars().all()
    assert [l.channel for l in letters] == ["telegram"]


async def test_sender_crash_never_propagates(db_session) -> None:
    """Even a sender raising something unexpected must not crash intake."""

    class ExplodingSender:
        name = "email"

        async def send(self, notification, preference):
            raise RuntimeError("boom")

    pref = make_pref(email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    set_senders({"email": ExplodingSender()})

    rows = await routing.ingest_event(db_session, _event())  # must not raise
    assert rows[0].status == "dead"
    letters = db_session.execute(select(DeadLetterRow)).scalars().all()
    assert len(letters) == 1
    assert "boom" in letters[0].error
