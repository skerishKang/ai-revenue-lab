"""#3782 Engine resumes ONLY independently owner-confirmed original P01."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision
from test_browser_control_owner_p01_d1_read_3782 import _OwnerD1, _seed_owner
from test_browser_control_p01_receipt_3782 import db_state, setup

from app.browser_control_owner_p01_d1_read import IndependentOwnerP01D1Reader
from app.browser_control_owner_p01_resume import (
    BROWSER_CONTROL_OWNER_P01_ENGINE_RESUME_WIRED,
    BROWSER_CONTROL_OWNER_P01_RESUME_PATH,
    IndependentlyApprovedBrowserControlEngineResume,
)


def _setup():
    engine, service, _receipts, request = setup(with_human_source=False)
    human = _OwnerD1()
    reader = IndependentOwnerP01D1Reader(
        owner_p01_binding=human, engine_continuation_binding=engine,
    )
    service._browser_control_human_p01_resolver = reader
    bridge = IndependentlyApprovedBrowserControlEngineResume(
        engine_service=service,
        engine_store=service._continuation_store,
        owner_reader=reader,
    )
    return engine, human, service, request, bridge, reader


def _decision(request):
    supplied = request["decision"]
    return VerifiedApprovalDecision(
        decision_id=supplied["decision_id"],
        pause_id=supplied["pause_id"],
        outcome=ApprovalOutcome(supplied["outcome"]),
        authority_ref=supplied["authority_ref"],
        evidence_ref=supplied["evidence_ref"],
        decided_at=datetime.fromisoformat(supplied["decided_at"]),
    )


def _resume(request, bridge):
    return asyncio.run(bridge.resume(
        app_id=request["app_id"], continuation_ref=request["continuation_ref"],
    ))


def _original(service, request):
    return asyncio.run(service._continuation_store.resolve(
        app_id=request["app_id"], continuation_ref=request["continuation_ref"],
    ))


def test_owner_db_derived_approved_decision_resumes_existing_engine_cas_once():
    engine, human, service, request, bridge, reader = _setup()
    try:
        assert BROWSER_CONTROL_OWNER_P01_ENGINE_RESUME_WIRED is False
        assert _resume(request, bridge).status_code == 503
        assert db_state(engine)[1] == 0
        assert len(human.reads) == 1
        record = _original(service, request)
        _seed_owner(human, record, _decision(request))
        proof = asyncio.run(reader.approved_original(record))
        assert proof is not None
        assert proof.decision == _decision(request)
        result = _resume(request, bridge)
        assert result.status_code == 200, result.body
        assert result.body["tool"]["status"] == "approval_recorded"
        assert result.body["tool"]["browser_action_executed"] is False
        assert result.body["tool"]["broker_command_dispatched"] is False
        assert db_state(engine)[0][0] == "consumed"
        assert db_state(engine)[1] == 1
        assert _resume(request, bridge).status_code != 200
        assert db_state(engine)[1] == 1
        assert all(x.lstrip().startswith("SELECT") for x in human.reads)
    finally:
        human.close()
        engine.db.close()


@pytest.mark.parametrize("mode", [
    "revoked_ticket", "revoked_decision", "foreign_owner",
    "wrong_invocation", "wrong_original_admission",
    "no_ticket", "no_owner_session",
    "future_decision",
])
def test_modified_or_revoked_owner_record_never_resumes(mode):
    engine, human, service, request, bridge, _reader = _setup()
    try:
        original = _original(service, request)
        _seed_owner(human, original, _decision(request))
        conn = human.db
        if mode == "revoked_ticket":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_tickets SET revoked_at=?",
                (datetime.now(UTC).isoformat(),),
            )
        elif mode == "revoked_decision":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_decisions SET revoked_at=?",
                (datetime.now(UTC).isoformat(),),
            )
        elif mode == "foreign_owner":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_decisions SET owner_subject_id='foreign'",
            )
        elif mode == "wrong_invocation":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_tickets SET invocation_sha256=?",
                ("f" * 64,),
            )
        elif mode == "wrong_original_admission":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_decisions "
                "SET original_admission_decision_id='foreign'",
            )
        elif mode == "no_ticket":
            conn.execute("DELETE FROM padiem_browser_control_owner_p01_tickets")
        elif mode == "no_owner_session":
            # Independent D1 prevents an approval with no authenticated user.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE padiem_browser_control_owner_p01_decisions "
                    "SET authenticated_owner_session_ref=NULL",
                )
            conn.rollback()
            assert db_state(engine)[1] == 0
            return
        elif mode == "future_decision":
            conn.execute(
                "UPDATE padiem_browser_control_owner_p01_decisions SET decided_at=?",
                ((datetime.now(UTC) + timedelta(seconds=5)).isoformat(),),
            )
        conn.commit()
        assert _resume(request, bridge).status_code == 503
        assert db_state(engine)[1] == 0
        assert db_state(engine)[0][0] == "active"
    finally:
        human.close()
        engine.db.close()


@pytest.mark.parametrize("bad", [
    {"app_id": "app.real.3782", "continuation_ref": "cont_real",
     "decision": {"outcome": "approved"}},
    {"app_id": "app.real.3782", "continuation_ref": "cont_real",
     "approval": True},
    {"app_id": "app.real.3782", "continuation_ref": "cont_real",
     "owner_subject_id": "foreign"},
    {"app_id": "app.real.3782", "continuation_ref": "cont_real",
     "browser_action": {"type": "click"}},
    {},
    [],
])
def test_private_owner_resume_wire_never_accepts_approval_claims(bad):
    engine, human, _service, _request, bridge, _reader = _setup()
    try:
        response = asyncio.run(bridge.handle(
            method="POST", path=BROWSER_CONTROL_OWNER_P01_RESUME_PATH,
            content_type="application/json", body=json.dumps(bad).encode(),
        ))
        assert response.status_code == 503
        assert db_state(engine)[1] == 0
        assert human.reads == []
    finally:
        human.close()
        engine.db.close()


def test_private_engine_authenticated_route_uses_original_only_and_product_off():
    from pathlib import Path

    engine, human, service, request, bridge, _reader = _setup()
    try:
        root = Path(__file__).resolve().parents[1]
        worker = (root / "worker_identity.py").read_text(encoding="utf-8")
        composition = (root / "app/engine_composition.py").read_text(encoding="utf-8")
        assert "if path == BROWSER_CONTROL_OWNER_P01_RESUME_PATH:" in worker
        assert "_authenticate_non_health_request(" in worker
        assert "services.browser_p01_owner_resume is None" in worker
        assert "browser_p01_owner_resume=" not in worker
        assert "browser_p01_owner_resume: IndependentlyApprovedBrowserControlEngineResume | None = None" in composition
        _seed_owner(human, _original(service, request), _decision(request))
        reply = asyncio.run(bridge.handle(
            method="POST", path=BROWSER_CONTROL_OWNER_P01_RESUME_PATH,
            content_type="application/json; charset=utf-8",
            body=json.dumps({
                "app_id": request["app_id"],
                "continuation_ref": request["continuation_ref"],
            }).encode(),
        ))
        assert reply.status_code == 200
        assert reply.body["tool"]["browser_action_executed"] is False
        assert reply.body["tool"]["broker_command_dispatched"] is False
        assert db_state(engine)[1] == 1
    finally:
        human.close()
        engine.db.close()


def test_wrong_original_or_arbitrary_decision_never_reaches_resume():
    engine, human, service, request, bridge, _reader = _setup()
    try:
        record = _original(service, request)
        _seed_owner(human, record, _decision(request))
        assert asyncio.run(bridge.resume(
            app_id=request["app_id"], continuation_ref="cont_foreign_3782",
        )).status_code == 503
        assert asyncio.run(bridge.resume(
            app_id="app_foreign", continuation_ref=request["continuation_ref"],
        )).status_code == 503
        assert asyncio.run(bridge.resume(
            app_id=request["app_id"], continuation_ref="bad<script>",
        )).status_code == 503
        assert db_state(engine)[1] == 0
        assert all(x.lstrip().startswith("SELECT") for x in human.reads)
        with pytest.raises(ValueError):
            IndependentlyApprovedBrowserControlEngineResume(
                engine_service=service,
                engine_store=service._continuation_store,
                owner_reader=IndependentOwnerP01D1Reader(
                    owner_p01_binding=_OwnerD1(), engine_continuation_binding=engine,
                ),
            )
    finally:
        human.close()
        engine.db.close()
