"""#3782 one canonical Engine bundle: CP USER -> Owner D1 -> P01 -> Broker read.

This is a hermetic actual SQLite Engine+Owner store integration with existing
services, not deployment, not a genuine user click, not Broker/Windows E2E.
Product Worker leaves this entire bundle OFF.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.browser_control_broker_original_read import (
    BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH,
)
from app.browser_control_engine_p01_composition import (
    BROWSER_CONTROL_ENGINE_P01_PRODUCT_COMPOSITION_WIRED,
    SourceOnlyOriginalBrowserP01EngineServices,
    compose_source_only_original_browser_p01_services,
)
from app.browser_control_owner_p01_d1_read import IndependentOwnerP01D1Reader
from app.browser_control_owner_p01_resume import BROWSER_CONTROL_OWNER_P01_RESUME_PATH
from app.browser_control_owner_ticket_issue_service import BROWSER_P01_TICKET_ISSUE_PATH
from test_browser_control_first_party_session_authority_3782 import (
    SESSION,
    USER,
    _ports,
)
from test_browser_control_owner_p01_ticket_issuer_3782 import (
    _OwnerD1,
    _Statement,
)
from test_browser_control_p01_receipt_3782 import APP_ID, CONT_REF, setup


class _CombinedOwnerD1(_OwnerD1):
    """Test-only FIRST-PARTY owner D1: supports both existing read and writer."""

    def prepare(self, sql):
        assert sql.lstrip().upper().startswith(("SELECT ", "INSERT INTO "))
        return _Statement(self.db, sql)


def _harness():
    db, tool, receipts, request = setup(with_human_source=False)
    owner = _CombinedOwnerD1()
    reader = IndependentOwnerP01D1Reader(
        owner_p01_binding=owner, engine_continuation_binding=db,
    )
    tool._browser_control_human_p01_resolver = reader
    shadow, cp, sessions = _ports()
    bundle = compose_source_only_original_browser_p01_services(
        tool_service=tool, continuation_store=tool._continuation_store,
        receipt_store=receipts, owner_d1=owner,
        current_session_authority=sessions,
    )
    return db, owner, tool, request, bundle, reader, shadow, cp


def _call(service, path, payload):
    return asyncio.run(service.handle(
        method="POST", path=path, content_type="application/json",
        body=json.dumps(payload).encode("utf-8"),
    ))


def _ticket(bundle):
    return _call(bundle.ticket_issue, BROWSER_P01_TICKET_ISSUE_PATH, {
        "app_id": APP_ID, "continuation_ref": CONT_REF,
        "product_user_id": USER, "auth_session_ref": SESSION,
    })


def _resume(bundle):
    return _call(bundle.owner_resume, BROWSER_CONTROL_OWNER_P01_RESUME_PATH, {
        "app_id": APP_ID, "continuation_ref": CONT_REF,
    })


def _read(bundle):
    return _call(bundle.broker_original_read, BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH, {
        "app_id": APP_ID, "continuation_ref": CONT_REF,
    })


def _record_human_click_simulation(owner, tool, evidence):
    """ONLY a test fixture; models B54's separate INSERT after a signed click."""
    record = asyncio.run(tool._continuation_store.resolve(
        app_id=APP_ID, continuation_ref=CONT_REF,
    ))
    pause, original, identity = (
        record.pause, record.original_admission, record.execution_identity,
    )
    assert original is not None and identity is not None
    ticket = owner.db.execute(
        "SELECT * FROM padiem_browser_control_owner_p01_tickets",
    ).fetchone()
    assert ticket is not None
    decided = datetime.now(timezone.utc).isoformat()
    owner.db.execute(
        "INSERT INTO padiem_browser_control_owner_p01_decisions "
        "(app_id,continuation_ref,pause_id,owner_subject_id,run_id,"
        "invocation_sha256,original_request_fingerprint,"
        "original_admission_decision_id,decision_id,authority_ref,evidence_ref,"
        "decided_at,expires_at,revoked_at,outcome,authenticated_owner_session_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            APP_ID, CONT_REF, pause.pause_id, identity.subject_id,
            pause.run_id, pause.invocation_sha256,
            original.request_fingerprint, original.decision_id,
            "owner.actual.test.decision", "owner.actual.test.authority",
            evidence, decided, ticket["expires_at"],
            None, "approved", "owner.session.test.confirmation",
        ),
    )
    owner.db.commit()


def test_one_engine_source_bundle_covers_ticket_p01_resume_and_broker_original_read():
    db, owner, tool, _req, bundle, _reader, shadow, cp = _harness()
    try:
        assert BROWSER_CONTROL_ENGINE_P01_PRODUCT_COMPOSITION_WIRED is False
        assert type(bundle) is SourceOnlyOriginalBrowserP01EngineServices
        names = bundle.named_engine_service_fields()
        assert set(names) == {
            "browser_p01_ticket_issue", "browser_p01_owner_resume",
            "browser_p01_broker_receipt_read", "browser_p01_broker_original_read",
        }
        assert _read(bundle).status_code == 404
        assert _resume(bundle).status_code == 503
        issued = _ticket(bundle)
        assert issued.status_code == 200, issued.body
        assert issued.body["owner_approval_recorded"] is False
        assert issued.body["browser_action_executed"] is False
        assert shadow.calls == cp.calls == 1
        assert _resume(bundle).status_code == 503
        assert _read(bundle).status_code == 404
        _record_human_click_simulation(owner, tool, "owner.user.evidence.3782")
        resumed = _resume(bundle)
        assert resumed.status_code == 200, resumed.body
        assert resumed.body["tool"]["status"] == "approval_recorded"
        assert resumed.body["tool"]["browser_action_executed"] is False
        assert resumed.body["tool"]["broker_command_dispatched"] is False
        assert _resume(bundle).status_code != 200
        projected = _read(bundle)
        assert projected.status_code == 200, projected.body
        original = projected.body["original"]
        assert original["app_id"] == APP_ID
        assert original["continuation_ref"] == CONT_REF
        assert original["user_approval_evidence_ref"] == "owner.user.evidence.3782"
        assert len(original["original_request_fingerprint"]) == 64
        assert projected.body["browser_action_executed"] is False
        assert projected.body["broker_command_dispatched"] is False
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_decisions"
        ).fetchone()[0] == 1
        assert db.db.execute(
            "SELECT COUNT(*) FROM padiem_engine_browser_control_p01_receipts"
        ).fetchone()[0] == 1
        # Source-only; live Worker has no composition invocation.
        worker = (Path(__file__).resolve().parents[1] / "worker_identity.py").read_text(
            encoding="utf-8",
        )
        assert "compose_source_only_original_browser_p01_services(" not in worker
        assert "browser_p01_ticket_issue=" not in worker
    finally:
        owner.db.close()
        db.db.close()


def test_current_cp_revoked_prevents_ticket_even_in_exact_bundled_services():
    db, owner, _tool, _req, bundle, _reader, _shadow, cp = _harness()
    try:
        cp.snapshot = {**cp.snapshot, "state": "revoked"}
        assert _ticket(bundle).status_code == 503
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
        assert _resume(bundle).status_code == 503
        assert _read(bundle).status_code == 404
    finally:
        owner.db.close()
        db.db.close()


def test_revoked_or_mismatched_human_decision_does_not_complete_engine_or_broker():
    db, owner, tool, _req, bundle, _reader, _shadow, _cp = _harness()
    try:
        assert _ticket(bundle).status_code == 200
        _record_human_click_simulation(owner, tool, "owner.user.evidence.3782")
        owner.db.execute(
            "UPDATE padiem_browser_control_owner_p01_tickets SET revoked_at=?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        owner.db.commit()
        assert _resume(bundle).status_code == 503
        assert _read(bundle).status_code == 404
    finally:
        owner.db.close()
        db.db.close()


@pytest.mark.parametrize("broken", ["missing", "same_owner_engine", "wrong_engine", "wrong_receipt",
                                    "wrong_reader", "wrong_owner_reader", "wrong_session"])
def test_composition_refuses_split_or_synthetic_p01_authority(broken):
    db, owner, tool, _req, _bundle, reader, _shadow, _cp = _harness()
    try:
        from app.browser_control_p01_receipt import (
            CloudflareD1BrowserControlP01ReceiptStore,
        )
        from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
        from test_browser_control_first_party_session_authority_3782 import _ports

        _sh, _cl, sessions = _ports()
        values = {
            "tool_service": tool,
            "continuation_store": tool._continuation_store,
            "receipt_store": tool._browser_control_p01_receipts,
            "owner_d1": owner,
            "current_session_authority": sessions,
        }
        if broken == "missing":
            values["owner_d1"] = None
        elif broken == "same_owner_engine":
            values["owner_d1"] = db
        elif broken == "wrong_engine":
            values["continuation_store"] = CloudflareD1IdentityBoundContinuationStore(owner)
        elif broken == "wrong_receipt":
            values["receipt_store"] = CloudflareD1BrowserControlP01ReceiptStore(owner)
        elif broken == "wrong_reader":
            tool._browser_control_human_p01_resolver = object()
        elif broken == "wrong_owner_reader":
            reader._owner = object()
        elif broken == "wrong_session":
            values["current_session_authority"] = lambda **_kw: None
        with pytest.raises((TypeError, ValueError)):
            compose_source_only_original_browser_p01_services(**values)
    finally:
        owner.db.close()
        db.db.close()
