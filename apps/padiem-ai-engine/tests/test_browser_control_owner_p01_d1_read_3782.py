"""#3782 independently authenticated HUMAN P01 OWNER database read only.

The OWNER first-party login/click writer is not implemented in this module.
Only a separately managed owner database record can satisfy Engine, never a
caller-provided decision or a service identity token by itself.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.browser_control_owner_p01_d1_read import (
    BROWSER_CONTROL_OWNER_P01_D1_READER_WIRED,
    IndependentOwnerP01D1Reader,
)
from app.continuation_binding import IdentityBoundContinuationRecord
from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission_resume import OriginalAdmissionBinding
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "browser_control_owner_p01_independent_d1.sql"
OWNER = "owner.real.3782"


class _Statement:
    def __init__(self, db, sql):
        self._db, self._sql, self._params = db, sql, ()

    def bind(self, *params):
        self._params = params
        return self

    async def first(self):
        row = self._db.execute(self._sql, self._params).fetchone()
        return dict(row) if row is not None else None


class _OwnerD1:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(CONTRACT.read_text(encoding="utf-8"))
        self.reads = []

    def prepare(self, sql):
        assert sql.lstrip().upper().startswith("SELECT "), "reader never writes"
        self.reads.append(sql)
        return _Statement(self.db, sql)

    def close(self):
        self.db.close()


def _fixtures():
    now = datetime.now(timezone.utc)
    p = ApprovalPause(
        pause_id="pause.owner.approved.3782",
        run_id="torun.owner.3782",
        agent_runtime_id="agent.owner.3782",
        tool_id="browser.control",
        invocation_sha256="b" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now - timedelta(seconds=30),
        expires_at=now + timedelta(minutes=4),
        approval_scope=("browser.control",),
    )
    orig = OriginalAdmissionBinding(
        decision_id="admission.real.3782",
        app_id="app.real.3782",
        subject_id=OWNER,
        authority_ref="owner.admission.real",
        policy_revision="owner.policy.v1",
        request_fingerprint="c" * 64,
    )
    identity = ContinuationExecutionIdentity(
        request_fingerprint=orig.request_fingerprint,
        plan_fingerprint=None, subject_id=OWNER,
        recovery_policy_fingerprint=None, max_retries=0,
        require_evidence=True, require_verification=True,
    )
    record = IdentityBoundContinuationRecord(
        app_id=orig.app_id,
        pause=p,
        continuation_ref="cont.owner.3782",
        plan_id=None,
        execution_identity=identity,
        original_admission=orig,
    )
    decision = VerifiedApprovalDecision(
        decision_id="human_decision.real.3782",
        pause_id=p.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="auth.owner.current",
        evidence_ref="evidence.owner.3782",
        decided_at=now - timedelta(seconds=3),
    )
    return record, decision


def _seed_owner(db, record, decision):
    original = record.original_admission
    assert original is not None
    p = record.pause
    # Separate first-party ticket source must exist for EVERY owner-approved
    # record, even inside this hermetic Engine resolver test. A bare record
    # inserted without issuer evidence can never pass the joined read.
    db.db.execute(
        "INSERT INTO padiem_browser_control_owner_p01_tickets "
        "(ticket_ref,session_user_id,workspace_ref,engine_owner_subject_id,"
        "app_id,continuation_ref,pause_id,engine_run_id,tool_id,approval_scope,"
        "invocation_sha256,original_request_fingerprint,"
        "original_admission_decision_id,expires_at,revoked_at,"
        "server_issued_at,server_issuer_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ticket.owner.3782", "user.authenticated.3782", "workspace.3782",
            record.execution_identity.subject_id, record.app_id,
            record.continuation_ref, p.pause_id, p.run_id,
            "browser.control", "browser.control", p.invocation_sha256,
            original.request_fingerprint, original.decision_id,
            p.expires_at.isoformat(), None, p.created_at.isoformat(),
            "engine.issuer.3782",
        ),
    )
    db.db.execute(
        "INSERT INTO padiem_browser_control_owner_p01_decisions "
        "(app_id,continuation_ref,pause_id,owner_subject_id,run_id,"
        "invocation_sha256,original_request_fingerprint,"
        "original_admission_decision_id,decision_id,authority_ref,evidence_ref,"
        "decided_at,expires_at,revoked_at,outcome,authenticated_owner_session_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record.app_id, record.continuation_ref, p.pause_id,
            record.execution_identity.subject_id, p.run_id, p.invocation_sha256,
            original.request_fingerprint, original.decision_id, decision.decision_id,
            decision.authority_ref, decision.evidence_ref,
            decision.decided_at.isoformat(), p.expires_at.isoformat(),
            None, "approved", "session.authenticated.first-party.3782",
        ),
    )
    db.db.commit()


def _read(db, record, decision):
    # Different D1 binding: no Engine service can write its own 'human' proof.
    engine_db = object()
    return asyncio.run(IndependentOwnerP01D1Reader(
        owner_p01_binding=db, engine_continuation_binding=engine_db
    )(record, decision))


def test_owner_d1_binding_must_be_independent_and_default_product_off():
    d = _OwnerD1()
    try:
        assert BROWSER_CONTROL_OWNER_P01_D1_READER_WIRED is False
        with pytest.raises(ValueError, match="independent"):
            IndependentOwnerP01D1Reader(
                owner_p01_binding=d, engine_continuation_binding=d
            )
        with pytest.raises(ValueError):
            IndependentOwnerP01D1Reader(
                owner_p01_binding=None, engine_continuation_binding=object()
            )
    finally:
        d.close()


def test_only_exact_independent_owner_row_is_accepted():
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        assert _read(db, record, decision) is None
        assert len(db.reads) == 1
        _seed_owner(db, record, decision)
        proof = _read(db, record, decision)
        assert proof is not None
        assert proof.decision == decision
        assert proof.user_subject_id == OWNER
        assert proof.invocation_sha256 == record.pause.invocation_sha256
        assert proof.original_admission_decision_id == record.original_admission.decision_id
        assert all(query.startswith("SELECT") for query in db.reads)
    finally:
        db.close()


@pytest.mark.parametrize("field,value", [
    ("owner_subject_id", "foreign.owner.3782"),
    ("app_id", "other.app.3782"),
    ("continuation_ref", "other.continuation"),
    ("pause_id", "other.pause"),
    ("run_id", "other.run"),
    ("invocation_sha256", "f" * 64),
    ("original_request_fingerprint", "f" * 64),
    ("original_admission_decision_id", "other.admission"),
    ("decision_id", "other.decision"),
    ("authority_ref", "other.authority"),
    ("evidence_ref", "other.evidence"),
    ("outcome", "denied"),  # CHECK prevents this insert/update at DB level.
    ("revoked_at", "2026-10-08T12:00:00+00:00"),
])
def test_mismatched_or_revoked_human_owner_row_never_grants(field, value):
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        _seed_owner(db, record, decision)
        if field == "outcome":
            with pytest.raises(sqlite3.IntegrityError):
                db.db.execute(
                    "UPDATE padiem_browser_control_owner_p01_decisions SET outcome=?",
                    (value,),
                )
            db.db.rollback()
            return
        db.db.execute(
            f"UPDATE padiem_browser_control_owner_p01_decisions SET {field}=?",
            (value,),
        )
        db.db.commit()
        assert _read(db, record, decision) is None
    finally:
        db.close()


def test_denied_or_foreign_pause_never_even_queries_user_owner_db():
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        _seed_owner(db, record, decision)
        assert _read(db, record, replace(decision, outcome=ApprovalOutcome.DENIED)) is None
        assert _read(db, replace(record, pause=replace(record.pause, tool_id="process.execute")), decision) is None
        assert _read(db, replace(record, pause=replace(record.pause, approval_scope=("process.execute",))), decision) is None
        assert db.reads == []
    finally:
        db.close()


def test_expiry_malformed_timestamp_or_missing_human_session_fails_closed():
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        _seed_owner(db, record, decision)
        db.db.execute("UPDATE padiem_browser_control_owner_p01_decisions SET expires_at=?", (
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        ))
        db.db.commit()
        assert _read(db, record, decision) is None
        db.db.execute("UPDATE padiem_browser_control_owner_p01_decisions SET expires_at=?", ("not-a-timestamp",))
        db.db.commit()
        assert _read(db, record, decision) is None
        with pytest.raises(sqlite3.IntegrityError):
            db.db.execute(
                "UPDATE padiem_browser_control_owner_p01_decisions "
                "SET authenticated_owner_session_ref=''"
            )
    finally:
        db.close()


def test_independent_owner_d1_read_is_consumed_by_actual_engine_resume_without_execution():
    """Real Engine verifier and SAME Engine D1 atomic CAS, independent human D1 read.

    The owner event is TEST-SEEDED, not a live user's first-party action.
    This must NOT be described as real product browser P01 activation.
    """
    from test_browser_control_p01_receipt_3782 import db_state, setup

    engine_db, service, _receipts, request = setup(with_human_source=False)
    human_db = _OwnerD1()
    try:
        engine_store = service._continuation_store
        record = asyncio.run(engine_store.resolve(
            app_id=request["app_id"],
            continuation_ref=request["continuation_ref"],
        ))
        submission = request["decision"]
        decision = VerifiedApprovalDecision(
            decision_id=submission["decision_id"],
            pause_id=submission["pause_id"],
            outcome=ApprovalOutcome(submission["outcome"]),
            authority_ref=submission["authority_ref"],
            evidence_ref=submission["evidence_ref"],
            decided_at=datetime.fromisoformat(submission["decided_at"]),
        )
        service._browser_control_human_p01_resolver = IndependentOwnerP01D1Reader(
            owner_p01_binding=human_db,
            engine_continuation_binding=engine_db,
        )

        missing = asyncio.run(service.resume_payload(request))
        assert missing.status_code == 503
        assert missing.body["error"]["code"] == "browser_control_human_p01_unavailable"
        assert db_state(engine_db)[1] == 0

        _seed_owner(human_db, record, decision)
        accepted = asyncio.run(service.resume_payload(request))
        assert accepted.status_code == 200
        assert accepted.body["tool"]["status"] == "approval_recorded"
        assert accepted.body["tool"]["browser_action_executed"] is False
        assert accepted.body["tool"]["broker_command_dispatched"] is False
        assert db_state(engine_db)[0][0] == "consumed"
        assert db_state(engine_db)[1] == 1
        assert len(human_db.reads) == 2

        again = asyncio.run(service.resume_payload(request))
        assert again.status_code != 200
        assert db_state(engine_db)[1] == 1
    finally:
        human_db.close()
        engine_db.db.close()


@pytest.mark.parametrize("column,replacement", [
    ("revoked_at", datetime.now(timezone.utc).isoformat()),
    ("engine_owner_subject_id", "other.owner"),
    ("engine_run_id", "torun.other"),
    ("invocation_sha256", "f" * 64),
    ("original_request_fingerprint", "f" * 64),
    ("original_admission_decision_id", "different.admission"),
    ("approval_scope", "process.execute"),
    ("server_issued_at", (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()),
])
def test_independent_ticket_revoked_or_changed_after_user_click_blocks_engine(
    column, replacement,
):
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        _seed_owner(db, record, decision)
        assert _read(db, record, decision) is not None
        if column == "approval_scope":
            with pytest.raises(sqlite3.IntegrityError):
                db.db.execute(
                    "UPDATE padiem_browser_control_owner_p01_tickets SET approval_scope=?",
                    (replacement,),
                )
            db.db.rollback()
            return
        db.db.execute(
            f"UPDATE padiem_browser_control_owner_p01_tickets SET {column}=?",
            (replacement,),
        )
        db.db.commit()
        assert _read(db, record, decision) is None
    finally:
        db.close()


def test_owner_approved_row_without_authentic_ticket_does_not_authorize_engine():
    db = _OwnerD1()
    try:
        record, decision = _fixtures()
        _seed_owner(db, record, decision)
        db.db.execute("DELETE FROM padiem_browser_control_owner_p01_tickets")
        db.db.commit()
        assert _read(db, record, decision) is None
    finally:
        db.close()
