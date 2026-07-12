"""Severity derivation + human-readable title/body for incoming events.

Table-driven: each rule inspects (subject, payload) and returns a severity or
None; the first non-None wins. Rules encode the platform conventions:

- risk.circuit_breaker HARD_HALT           -> critical
- risk.circuit_breaker SOFT_HALT/other     -> warning
- risk rejections / decisions              -> info (by default)
- execution.live_order (real-money order)  -> warning
- execution.report fills                   -> info
- ai.* / optimizer.* recommendations       -> info
- anything else                            -> info

An explicit `severity` on a REST-ingested event overrides derivation
(handled by the caller, app/routing.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable

SEVERITIES = ("info", "warning", "critical")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(SEVERITIES)}

DEFAULT_SEVERITY = "info"

Rule = Callable[[str, dict], "str | None"]


def severity_rank(severity: str) -> int:
    """Rank for min-severity comparisons; unknown severities rank lowest."""
    return _SEVERITY_RANK.get(severity, 0)


def _rule_circuit_breaker(subject: str, payload: dict) -> str | None:
    if subject != "risk.circuit_breaker":
        return None
    state = str(payload.get("state", "")).upper()
    if state == "HARD_HALT":
        return "critical"
    # SOFT_HALT or a breaker event without a state: still a halt-side event.
    return "warning"


def _rule_risk_rejection(subject: str, payload: dict) -> str | None:
    if subject == "risk.rejected":
        return "info"
    if subject == "risk.decision":
        return "info"  # approved or rejected: informational by default
    return None


def _rule_risk_other(subject: str, payload: dict) -> str | None:
    # risk.circuit_breaker_reset, risk.limits_updated, ...
    return "info" if subject.startswith("risk.") else None


def _rule_live_order(subject: str, payload: dict) -> str | None:
    return "warning" if subject == "execution.live_order" else None


def _rule_execution_report(subject: str, payload: dict) -> str | None:
    return "info" if subject == "execution.report" else None


def _rule_execution_other(subject: str, payload: dict) -> str | None:
    # execution.cancelled, order.submitted, ...
    if subject.startswith("execution.") or subject.startswith("order."):
        return "info"
    return None


def _rule_recommendations(subject: str, payload: dict) -> str | None:
    if subject.startswith("ai.") or subject.startswith("optimizer."):
        return "info"
    return None


RULES: tuple[Rule, ...] = (
    _rule_circuit_breaker,
    _rule_risk_rejection,
    _rule_risk_other,
    _rule_live_order,
    _rule_execution_report,
    _rule_execution_other,
    _rule_recommendations,
)


def derive_severity(subject: str, payload: dict | None = None) -> str:
    payload = payload or {}
    for rule in RULES:
        severity = rule(subject, payload)
        if severity is not None:
            return severity
    return DEFAULT_SEVERITY


def _default_title(subject: str, payload: dict) -> str:
    if subject == "risk.circuit_breaker":
        return (
            f"Circuit breaker {payload.get('state', '?')} "
            f"on account {payload.get('account_id', '?')}"
        )
    if subject == "risk.circuit_breaker_reset":
        return f"Circuit breaker reset on account {payload.get('account_id', '?')}"
    if subject == "risk.rejected":
        return f"Signal rejected: {payload.get('reason') or 'risk checks failed'}"
    if subject == "risk.decision":
        if payload.get("approved"):
            return "Risk decision: approved"
        return f"Risk decision: rejected ({payload.get('reason', '')})"
    if subject == "execution.live_order":
        return f"LIVE order routed: {payload.get('symbol', '?')}"
    if subject == "execution.report":
        return (
            f"Execution {payload.get('status', 'report')}: "
            f"{payload.get('symbol', '?')} x {payload.get('filled_quantity', '?')}"
        )
    if subject == "execution.cancelled":
        return f"Execution cancelled: {payload.get('execution_id', '?')}"
    if subject == "order.submitted":
        return f"Order submitted: {payload.get('symbol', '?')}"
    if subject == "ai.recommendation.created":
        return "New AI recommendation"
    if subject == "optimizer.promotion.recommended":
        return "Optimizer: promotion recommended"
    return subject


def build_message(subject: str, payload: dict | None = None) -> tuple[str, str]:
    """(title, body) for a notification. An event payload may carry explicit
    title/body (REST ingest); otherwise both are derived."""
    payload = payload or {}
    title = str(payload.get("title") or _default_title(subject, payload))[:255]
    body = payload.get("body")
    if body is None:
        body = json.dumps(payload, default=str, sort_keys=True)
    return title, str(body)[:4000]
