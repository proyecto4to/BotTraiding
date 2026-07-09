"""Audit hook: one structured JSON record per /api/* and /config/* request."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from app.audit import logger as audit_logger
from tests.conftest import auth_headers


@pytest.fixture()
def audit_records():
    """Capture audit log records emitted during the test."""
    records: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(json.loads(record.getMessage()))

    collector = _Collector()
    audit_logger.addHandler(collector)
    yield records
    audit_logger.removeHandler(collector)


def test_config_request_is_audited(client, seeded_markets, audit_records) -> None:
    client.get("/config/markets", headers=auth_headers(sub="user-7"))

    assert len(audit_records) == 1
    entry = audit_records[0]
    assert entry["event"] == "gateway.request"
    assert entry["method"] == "GET"
    assert entry["path"] == "/config/markets"
    assert entry["user"] == "user-7"
    assert entry["status"] == 200
    assert "ts" in entry and "duration_ms" in entry


@respx.mock
def test_proxy_request_is_audited(client, audit_records) -> None:
    respx.get("http://strategy-engine:8000/strategies/list").mock(
        return_value=httpx.Response(200, json=[])
    )
    client.get("/api/strategies/list", headers=auth_headers(sub="user-9"))

    assert len(audit_records) == 1
    assert audit_records[0]["path"] == "/api/strategies/list"
    assert audit_records[0]["user"] == "user-9"
    assert audit_records[0]["status"] == 200


def test_unauthenticated_request_audited_with_null_user(client, audit_records) -> None:
    client.get("/api/strategies/list")  # 401, no token

    assert len(audit_records) == 1
    assert audit_records[0]["user"] is None
    assert audit_records[0]["status"] == 401


def test_health_is_not_audited(client, audit_records) -> None:
    client.get("/health")
    assert audit_records == []
