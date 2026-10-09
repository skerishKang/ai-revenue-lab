"""#3782 authenticated internal Engine client reads only ORIGINAL approved P01.

Uses a hermetic same-process transport backed by the REAL Engine D1 reader.
Not a Production Broker credential or browser authority.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Engine standalone CI intentionally installs Engine + Core, not the separately
# packaged first-party Python client. Import that repo-local client only for
# this transport contract test; do NOT widen Production dependencies.
_CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
if str(_CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLIENT_ROOT))

from padiem_ai_engine_client import (
    ENGINE_BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH,
    ENGINE_INTERNAL_ORIGIN,
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)
from test_browser_control_broker_receipt_read_3782 import _harness

CALLER = "broker.browser.3782"


class _InternalTransport:
    def __init__(self, reader):
        self.reader = reader
        self.requests = []

    async def request(self, *, method, url, headers, body):
        self.requests.append((method, url, headers, json.loads(body)))
        assert headers["X-Padiem-Engine-Caller"] == CALLER
        assert headers["X-Padiem-Engine-Credential"] == "S" * 40
        reply = await self.reader.handle(
            method=method,
            path=url.removeprefix(ENGINE_INTERNAL_ORIGIN),
            content_type=headers["Content-Type"],
            body=body,
        )
        return EngineTransportResponse(
            status=reply.status_code,
            body=json.dumps(reply.body).encode("utf-8"),
            headers={},
        )


def _client(reader, app_id):
    transport = _InternalTransport(reader)
    return PadiemAiEngineClient(
        transport=transport, app_id=app_id,
        caller_id=CALLER, credential="S" * 40,
    ), transport


def _read(client, fields):
    return asyncio.run(client.read_browser_control_broker_receipt(
        **{k: v for k, v in fields.items() if k != "app_id"}
    ))


def test_real_engine_d1_projection_crosses_only_private_authenticated_client():
    db, service, request, fields, reader, _receipts = _harness()
    try:
        client, transport = _client(reader, fields["app_id"])
        with pytest.raises(PadiemAiEngineClientError):
            _read(client, fields)  # not consumed / not approved
        assert asyncio.run(service.resume_payload(request)).status_code == 200
        receipt = _read(client, fields)
        assert receipt["continuation_ref"] == fields["continuation_ref"]
        assert receipt["run_id"] == fields["run_id"]
        assert receipt["invocation_sha256"] == fields["invocation_sha256"]
        assert receipt["evidence_ref"] == fields["user_approval_evidence_ref"]
        assert datetime.fromisoformat(receipt["expires_at"]).utcoffset() is not None
        assert len(transport.requests) == 2
        method, url, headers, wire = transport.requests[-1]
        assert method == "POST"
        assert url == ENGINE_INTERNAL_ORIGIN + ENGINE_BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH
        assert wire == fields
        assert set(headers) == {
            "Content-Type", "X-Padiem-Engine-Caller", "X-Padiem-Engine-Credential",
        }
    finally:
        db.db.close()


@pytest.mark.parametrize("field", [
    "user_subject_id", "original_request_fingerprint",
    "original_admission_decision_id", "run_id", "invocation_sha256",
    "user_approval_evidence_ref",
])
def test_client_cannot_widen_or_read_different_admission(field):
    db, service, request, fields, reader, _receipts = _harness()
    try:
        assert asyncio.run(service.resume_payload(request)).status_code == 200
        client, transport = _client(reader, fields["app_id"])
        wrong = dict(fields)
        wrong[field] = "f" * 64 if "fingerprint" in field or field == "invocation_sha256" else "wrong.original"
        with pytest.raises(PadiemAiEngineClientError):
            _read(client, wrong)
        assert len(transport.requests) == 1
    finally:
        db.db.close()


def test_bad_client_admission_ref_refused_before_transport():
    db, _service, _request, fields, reader, _receipts = _harness()
    try:
        client, transport = _client(reader, fields["app_id"])
        bad = {**fields, "invocation_sha256": "INVALID"}
        with pytest.raises(PadiemAiEngineClientError, match="Invalid admitted"):
            _read(client, bad)
        assert transport.requests == []
    finally:
        db.db.close()


def test_b54_worker_allowlist_deliberately_excludes_broker_only_read():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    module = (root / "padiem-chat/app/worker_orchestration.py").read_text(encoding="utf-8")
    assert "ENGINE_BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH" not in module
