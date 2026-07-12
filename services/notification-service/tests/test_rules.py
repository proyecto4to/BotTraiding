"""Severity derivation rules (app/rules.py) — table-driven."""

from __future__ import annotations

import pytest

from app import rules

CASES = [
    # (subject, payload, expected severity)
    ("risk.circuit_breaker", {"state": "HARD_HALT", "account_id": "acc-1"}, "critical"),
    ("risk.circuit_breaker", {"state": "hard_halt"}, "critical"),  # case-insensitive
    ("risk.circuit_breaker", {"state": "SOFT_HALT"}, "warning"),
    ("risk.circuit_breaker", {}, "warning"),
    ("risk.circuit_breaker_reset", {"account_id": "acc-1"}, "info"),
    ("risk.rejected", {"reason": "max_daily_loss"}, "info"),
    ("risk.decision", {"approved": False, "reason": "x"}, "info"),
    ("risk.decision", {"approved": True}, "info"),
    ("risk.limits_updated", {}, "info"),
    ("execution.live_order", {"symbol": "AAPL"}, "warning"),
    ("execution.report", {"status": "filled", "symbol": "AAPL"}, "info"),
    ("execution.report", {"status": "partially_filled"}, "info"),
    ("execution.cancelled", {}, "info"),
    ("order.submitted", {"symbol": "AAPL"}, "info"),
    ("ai.recommendation.created", {}, "info"),
    ("optimizer.promotion.recommended", {}, "info"),
    ("bot.started", {}, "info"),
    ("something.unknown", {}, "info"),
]


@pytest.mark.parametrize("subject,payload,expected", CASES)
def test_derive_severity(subject: str, payload: dict, expected: str) -> None:
    assert rules.derive_severity(subject, payload) == expected


def test_severity_rank_ordering() -> None:
    assert (
        rules.severity_rank("info")
        < rules.severity_rank("warning")
        < rules.severity_rank("critical")
    )
    # Unknown severities rank lowest instead of raising.
    assert rules.severity_rank("nonsense") == rules.severity_rank("info")


def test_build_message_defaults() -> None:
    title, body = rules.build_message(
        "risk.circuit_breaker", {"state": "HARD_HALT", "account_id": "acc-9"}
    )
    assert "HARD_HALT" in title
    assert "acc-9" in title
    assert "HARD_HALT" in body  # JSON dump of payload


def test_build_message_explicit_title_body() -> None:
    title, body = rules.build_message(
        "custom.subject", {"title": "My title", "body": "My body"}
    )
    assert title == "My title"
    assert body == "My body"


def test_build_message_live_order_title() -> None:
    title, _ = rules.build_message("execution.live_order", {"symbol": "EURUSD"})
    assert "LIVE" in title
    assert "EURUSD" in title
