"""#3782 first-party private Broker reads real consumed original Engine P01.

Hermetic Core human evidence fixtures do NOT represent real product approval.
No private reader binding is activated in Production.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_browser_control_p01_receipt_3782 import db_state, setup

from app.browser_control_broker_receipt_read import (
    BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH,
    BROWSER_CONTROL_BROKER_RECEIPT_READ_WIRED,
    AuthenticatedBrowserP01ReceiptReadEngineService,
)


def _harness():
    db, service, receipts, request = setup(with_human_source=True)
    store = service._continuation_store
    record = asyncio.run(store.resolve(
        app_id=request["app_id"], continuation_ref=request["continuation_ref"],
    ))
    orig, pause, identity = (
        record.original_admission, record.pause, record.execution_identity,
    )
    assert orig is not None and identity is not None and receipts is not None
    fields = {
        "app_id": request["app_id"],
        "continuation_ref": request["continuation_ref"],
        "user_subject_id": identity.subject_id,
        "original_request_fingerprint": orig.request_fingerprint,
        "original_admission_decision_id": orig.decision_id,
        "run_id": pause.run_id,
        "invocation_sha256": pause.invocation_sha256,
        "user_approval_evidence_ref": request["decision"]["evidence_ref"],
    }
    reader = AuthenticatedBrowserP01ReceiptReadEngineService(receipts=receipts)
    return db, service, request, fields, reader, receipts


def _call(reader, fields):
    return asyncio.run(reader.handle(
        method="POST", path=BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH,
        content_type="application/json", body=json.dumps(fields).encode(),
    ))


def test_only_actual_consumed_engine_receipt_is_readable_for_original_broker_join():
    db, service, request, fields, reader, _receipts = _harness()
    try:
        assert BROWSER_CONTROL_BROKER_RECEIPT_READ_WIRED is False
        before = _call(reader, fields)
        assert before.status_code == 404
        assert db_state(db)[1] == 0
        resumed = asyncio.run(service.resume_payload(request))
        assert resumed.status_code == 200
        assert resumed.body["tool"]["browser_action_executed"] is False
        assert resumed.body["tool"]["broker_command_dispatched"] is False
        receipt = _call(reader, fields)
        assert receipt.status_code == 200, receipt.body
        assert receipt.body["ok"] is True
        assert receipt.body["browser_action_executed"] is False
        assert receipt.body["broker_command_dispatched"] is False
        assert set(receipt.body["receipt"]) == {
            "app_id", "continuation_ref", "pause_id", "decision_id",
            "evidence_ref", "authority_ref", "run_id", "invocation_sha256",
            "approved_at", "expires_at",
        }
        assert receipt.body["receipt"]["invocation_sha256"] == fields["invocation_sha256"]
        assert receipt.body["receipt"]["evidence_ref"] == fields["user_approval_evidence_ref"]
        assert db_state(db)[1] == 1
    finally:
        db.db.close()


@pytest.mark.parametrize("changed", [
    "app_id", "continuation_ref", "user_subject_id", "original_request_fingerprint",
    "original_admission_decision_id", "run_id", "invocation_sha256",
    "user_approval_evidence_ref",
])
def test_changed_engine_or_broker_identity_never_projects_receipt(changed):
    db, service, request, fields, reader, _receipts = _harness()
    try:
        assert asyncio.run(service.resume_payload(request)).status_code == 200
        forged = dict(fields)
        forged[changed] = "f" * 64 if "fingerprint" in changed or changed == "invocation_sha256" else "foreign.3782"
        result = _call(reader, forged)
        assert result.status_code == 404
        assert result.body == {
            "ok": False, "error": {"code": "browser_p01_receipt_unavailable"},
        }
        assert db_state(db)[1] == 1
    finally:
        db.db.close()


@pytest.mark.parametrize("extra", [
    {"outcome": "approved"}, {"decision_id": "client.decision"},
    {"browser_action": {"action": "click"}}, {"owner_id": "other"},
    {"tool_id": "process.execute"},
])
def test_broker_cannot_supply_approval_action_or_broader_fields(extra):
    db, _service, _request, fields, reader, _receipts = _harness()
    try:
        forged = {**fields, **extra}
        assert _call(reader, forged).status_code == 404
        assert db_state(db)[1] == 0
    finally:
        db.db.close()


def test_revoked_receipt_or_expiry_fails_closed_even_after_success():
    db, service, request, fields, reader, receipts = _harness()
    try:
        assert asyncio.run(service.resume_payload(request)).status_code == 200
        assert _call(reader, fields).status_code == 200
        assert asyncio.run(receipts.revoke(
            app_id=fields["app_id"],
            continuation_ref=fields["continuation_ref"],
            now=datetime.now(UTC),
        )) is True
        assert _call(reader, fields).status_code == 404
        assert db_state(db)[1] == 1
    finally:
        db.db.close()


def test_wire_is_private_default_uncomposed_and_does_not_expose_browser_data():
    db, _service, _request, fields, reader, _receipts = _harness()
    try:
        engine = Path(__file__).resolve().parents[1]
        worker = (engine / "worker_identity.py").read_text(encoding="utf-8")
        bundle = (engine / "app/engine_composition.py").read_text(encoding="utf-8")
        assert "if path == BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH:" in worker
        assert "services.browser_p01_broker_receipt_read is None" in worker
        assert "_authenticate_non_health_request(" in worker
        assert "browser_p01_broker_receipt_read=" not in worker
        assert "browser_p01_broker_receipt_read: AuthenticatedBrowserP01ReceiptReadEngineService | None = None" in bundle
        assert _call(reader, {**fields, "password": "must-not-leak"}).status_code == 404
        assert asyncio.run(reader.handle(
            method="GET", path=BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH,
            content_type="application/json", body=b"{}",
        )).status_code == 405
    finally:
        db.db.close()
