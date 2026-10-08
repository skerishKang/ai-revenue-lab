"""#3782 Engine real D1 original admission projection, Broker-only source route.

No user approval can be minted by this reader. Synthetic test continuation
resumes with canonical Engine fixture to prove consumed D1 + P01 correlation.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_browser_control_broker_receipt_read_3782 import _harness as receipt_harness

from app.browser_control_broker_original_read import (
    BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH,
    BROWSER_CONTROL_BROKER_ORIGINAL_READ_WIRED,
    AuthenticatedEngineBrowserOriginalRead,
)
from app.browser_control_p01_receipt import CloudflareD1BrowserControlP01ReceiptStore
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore


def harness():
    db, service, request, fields, _reader, receipts = receipt_harness()
    engine = service._continuation_store
    original = AuthenticatedEngineBrowserOriginalRead(
        engine_store=engine, receipts=receipts,
    )
    return db, service, request, fields, original


def read(service, data, *, method="POST", content_type="application/json"):
    return asyncio.run(service.handle(
        method=method, path=BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH,
        content_type=content_type,
        body=json.dumps(data).encode("utf-8"),
    ))


def test_only_current_consumed_p01_projects_exact_original_admission():
    db, executor, request, fields, service = harness()
    try:
        assert BROWSER_CONTROL_BROKER_ORIGINAL_READ_WIRED is False
        query = {"app_id": fields["app_id"], "continuation_ref": fields["continuation_ref"]}
        assert read(service, query).status_code == 404
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        projected = read(service, query)
        assert projected.status_code == 200, projected.body
        assert projected.body == {
            "ok": True,
            "original": fields,
            "browser_action_executed": False,
            "broker_command_dispatched": False,
        }
        assert read(service, query).body == projected.body
    finally:
        db.db.close()


@pytest.mark.parametrize("change", [
    {"app_id": "foreign-app"},
    {"continuation_ref": "cont_foreign_approval"},
    {"owner_id": "user.forged"},
    {"decision_id": "model.approved"},
    {"browser_action": {"action": "click"}},
    {"user_approval_evidence_ref": "fake"},
    {"broker_command_ref": "command.forged"},
])
def test_broker_query_cannot_select_other_owner_or_supply_approval(change):
    db, executor, request, fields, service = harness()
    try:
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        wrong = {
            "app_id": fields["app_id"],
            "continuation_ref": fields["continuation_ref"],
            **change,
        }
        assert read(service, wrong).status_code == 404
    finally:
        db.db.close()


def test_original_fingerprint_mismatch_refuses_even_after_resume():
    db, executor, request, fields, service = harness()
    try:
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        query = {"app_id": fields["app_id"], "continuation_ref": fields["continuation_ref"]}
        assert read(service, query).status_code == 200
        db.db.execute(
            "UPDATE padiem_engine_continuations "
            "SET execution_identity_json=json_set(execution_identity_json,"
            "'$.original_admission_binding.request_fingerprint','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb') "
            "WHERE app_id=? AND continuation_ref=?",
            (fields["app_id"], fields["continuation_ref"]),
        )
        db.db.commit()
        assert read(service, query).status_code == 404
    finally:
        db.db.close()


def test_reader_must_share_original_engine_d1_with_receipt_owner():
    db, _executor, _request, _fields, _reader = harness()
    try:
        class WrongBinding:
            def prepare(self, sql):
                return self

        other = CloudflareD1IdentityBoundContinuationStore(WrongBinding())
        with pytest.raises(ValueError):
            AuthenticatedEngineBrowserOriginalRead(
                engine_store=other, receipts=CloudflareD1BrowserControlP01ReceiptStore(db),
            )
    finally:
        db.db.close()


def test_method_content_type_and_worker_audience_all_fail_closed():
    db, executor, request, fields, service = harness()
    try:
        assert asyncio.run(executor.resume_payload(request)).status_code == 200
        query = {"app_id": fields["app_id"], "continuation_ref": fields["continuation_ref"]}
        assert read(service, query, method="GET").status_code == 405
        assert read(service, query, content_type="text/plain").status_code == 404
        assert read(service, {"app_id": fields["app_id"]}).status_code == 404
        worker = (Path(__file__).resolve().parents[1] / "worker_identity.py").read_text(
            encoding="utf-8",
        )
        body = worker.split("async def _fetch_browser_broker_original_read", 1)[1].split(
            "async def _fetch_browser_broker_receipt_read", 1,
        )[0]
        assert body.index("_authenticate_non_health_request(") < body.index(
            "authenticate_broker_p01_receipt_reader("
        ) < body.index("services.browser_p01_broker_original_read")
        assert "browser_p01_broker_original_read=" not in worker
    finally:
        db.db.close()
