"""#3782 original Engine admission read crosses the trusted client, no grant.

The Engine test D1 is synthetic. The product Broker association and production
service identity are independently missing and MUST NOT be inferred here.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from test_browser_control_broker_original_read_3782 import harness
from test_browser_control_broker_receipt_client_3782 import _client

_CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
if str(_CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLIENT_ROOT))

from padiem_ai_engine_client import (
    ENGINE_BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH,
    ENGINE_INTERNAL_ORIGIN,
    PadiemAiEngineClientError,
)


def test_trusted_client_reads_only_consumed_original_engine_d1():
    db, executor, request, fields, service = harness()
    try:
        client, transport = _client(service, fields["app_id"])
        with pytest.raises(PadiemAiEngineClientError):
            asyncio.run(client.read_browser_control_original_admission(
                continuation_ref=fields["continuation_ref"],
            ))
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        original = asyncio.run(client.read_browser_control_original_admission(
            continuation_ref=fields["continuation_ref"],
        ))
        assert original == fields
        assert len(transport.requests) == 2
        method, url, _headers, wire = transport.requests[-1]
        assert method == "POST"
        assert url == ENGINE_INTERNAL_ORIGIN + ENGINE_BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH
        assert wire == {
            "app_id": fields["app_id"],
            "continuation_ref": fields["continuation_ref"],
        }
    finally:
        db.db.close()


@pytest.mark.parametrize("bad", ["", "other", "cont_bad", "../cont_12345678", 123])
def test_rejects_invalid_continuation_before_transport(bad):
    db, _executor, _request, fields, service = harness()
    try:
        client, transport = _client(service, fields["app_id"])
        with pytest.raises(PadiemAiEngineClientError):
            asyncio.run(client.read_browser_control_original_admission(
                continuation_ref=bad,
            ))
        assert transport.requests == []
    finally:
        db.db.close()


def test_original_reader_cannot_request_other_engine_app():
    db, executor, request, fields, service = harness()
    try:
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        client, transport = _client(service, "another.engine.app")
        with pytest.raises(PadiemAiEngineClientError):
            asyncio.run(client.read_browser_control_original_admission(
                continuation_ref=fields["continuation_ref"],
            ))
        assert len(transport.requests) == 1
        assert transport.requests[0][-1]["app_id"] == "another.engine.app"
    finally:
        db.db.close()
