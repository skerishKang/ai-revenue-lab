"""#8193: signed self-heal report and in-memory admin view. No DB writes."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import ops_pc_self_heal as module
from app.ops_notify_event import KEY_HEADER

KEY_NAME = "PADIEM_OPS_NOTIFY_KEY_PC"
FIXTURE_KEY = "unit-test-pc-key"
REPORT = {"node": "COMP1", "at": 1_700_000_000.0,
          "action": "shell_stopped", "detail": "stale shell cleared", "result": "ok"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv(KEY_NAME, FIXTURE_KEY)
    module.reset_for_test()


async def _post(payload, *, key=FIXTURE_KEY):
    data = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    headers = [(b"content-type", b"application/json")]
    if key is not None:
        headers.append((KEY_HEADER.lower().encode(), key.encode()))

    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/api/ops/pc/self-heal",
                       "query_string": b"", "headers": headers,
                       "app": SimpleNamespace(state=SimpleNamespace())}, receive)
    return await module.report_self_heal(request)


def test_a_signed_report_is_stored_and_readable():
    response = asyncio.run(_post(REPORT))
    assert response.status_code == 200
    view = module.latest("COMP1")
    assert view["reports"][0]["action"] == "shell_stopped"
    assert view["reports"][0]["at"].endswith("Z")
    assert module.latest("OTHER")["reports"] == []


def test_an_unsigned_or_malformed_report_is_refused():
    assert asyncio.run(_post(REPORT, key=None)).status_code == 401
    assert asyncio.run(_post(REPORT, key="wrong")).status_code == 401
    bad = dict(REPORT, secret="x")
    assert asyncio.run(_post(bad)).status_code == 400
    assert asyncio.run(_post(dict(REPORT, node="x" * 200))).status_code == 400
    assert module.latest()["reports"] == []


def test_a_new_report_for_one_pc_replaces_only_that_pc():
    asyncio.run(_post(REPORT))
    other = dict(REPORT, node="COMP2", action="notify_only")
    asyncio.run(_post(other))
    rows = module.latest()["reports"]
    assert {row["node"] for row in rows} == {"COMP1", "COMP2"}
