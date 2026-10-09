"""#3782 Engine ACTIVE original-admitted pause -> separate D1 owner ticket.

Real Engine D1 read, real independent owner SQLite D1 ticket INSERT;
canonical current user-session authority is TEST-ONLY, NOT production auth.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.browser_control_owner_p01_ticket_issuer import (
    TICKET_OWNER_ISSUER_WIRED,
    AuthenticatedEngineBrowserP01TicketIssuer,
    CurrentCanonicalHumanSession,
)
from test_browser_control_p01_receipt_3782 import APP_ID, CONT_REF, setup

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "browser_control_owner_p01_independent_d1.sql"


class _Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.params = db, sql, ()

    def bind(self, *values):
        self.params = values
        return self

    async def run(self):
        cur = self.db.execute(self.sql, self.params)
        self.db.commit()
        return {"success": True, "meta": {"changes": cur.rowcount}}

    async def first(self):
        row = self.db.execute(self.sql, self.params).fetchone()
        return dict(row) if row is not None else None


class _OwnerD1:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(CONTRACT.read_text(encoding="utf-8"))

    def prepare(self, sql):
        assert sql.startswith((
            "INSERT INTO padiem_browser_control_owner_p01_tickets",
            "SELECT r.app_id,r.continuation_ref",
        ))
        return _Statement(self.db, sql)


class _SessionAuthority:
    def __init__(self, *, product="usr.real.test", subject="owner.3782",
                 workspace="tenant.real.test", session="live.session.3782"):
        self.snapshot = CurrentCanonicalHumanSession(
            product_user_id=product, canonical_subject_id=subject,
            workspace_ref=workspace, auth_session_ref=session,
        )
        self.calls = 0

    async def resolve_active(self, *, product_user_id, auth_session_ref):
        self.calls += 1
        return self.snapshot


def _setup():
    engine, service, _receipts, _request = setup(with_human_source=False)
    owner = _OwnerD1()
    live = _SessionAuthority()
    issuer = AuthenticatedEngineBrowserP01TicketIssuer(
        engine_store=service._continuation_store,
        owner_binding=owner, session_authority=live,
    )
    return engine, owner, live, issuer


def _issue(issuer, **changes):
    payload = {
        "app_id": APP_ID, "continuation_ref": CONT_REF,
        "product_user_id": "usr.real.test",
        "auth_session_ref": "live.session.3782",
    }
    payload.update(changes)
    return asyncio.run(issuer.issue(**payload))


def test_first_party_authenticated_server_session_issues_from_real_engine_pause():
    engine, owner, live, issuer = _setup()
    try:
        assert TICKET_OWNER_ISSUER_WIRED is False
        ref = _issue(issuer)
        assert ref.startswith("ticket_")
        row = owner.db.execute(
            "SELECT * FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()
        record = asyncio.run(issuer._engine.resolve(
            app_id=APP_ID, continuation_ref=CONT_REF,
        ))
        original = record.original_admission
        assert original is not None
        assert row["ticket_ref"] == ref
        assert row["app_id"] == APP_ID
        assert row["continuation_ref"] == CONT_REF
        assert row["session_user_id"] == live.snapshot.product_user_id
        assert row["workspace_ref"] == live.snapshot.workspace_ref
        assert row["engine_owner_subject_id"] == live.snapshot.canonical_subject_id
        assert row["engine_run_id"] == record.pause.run_id
        assert row["invocation_sha256"] == record.pause.invocation_sha256
        assert row["original_request_fingerprint"] == original.request_fingerprint
        assert row["original_admission_decision_id"] == original.decision_id
        assert row["tool_id"] == row["approval_scope"] == "browser.control"
        assert live.calls == 1
        # No Engine continuation transition, tool action or decision issuance.
        state = engine.db.execute(
            "SELECT state FROM padiem_engine_continuations WHERE continuation_ref=?",
            (CONT_REF,),
        ).fetchone()[0]
        assert state == "active"
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_decisions"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_unique_ticket_per_engine_continuation_is_not_overwritten():
    engine, owner, _live, issuer = _setup()
    try:
        initial = _issue(issuer)
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer)
        assert owner.db.execute(
            "SELECT ticket_ref FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == initial
    finally:
        owner.db.close()
        engine.db.close()


@pytest.mark.parametrize("field,value", [
    ("canonical_subject_id", "other.subject"),
    ("product_user_id", "foreign.owner"),
    ("auth_session_ref", "stale.session"),
    ("workspace_ref", "bad workspace"),
])
def test_owner_session_mismatch_or_invalid_never_issues(field, value):
    engine, owner, live, issuer = _setup()
    try:
        live.snapshot = replace(live.snapshot, **{field: value})
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer)
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


@pytest.mark.parametrize("field,value", [
    ("app_id", "another.app"),
    ("continuation_ref", "cont_not-real"),
    ("product_user_id", "foreign.owner"),
    ("auth_session_ref", "foreign.session"),
])
def test_unknown_engine_request_or_foreign_user_is_not_a_ticket(field, value):
    engine, owner, _live, issuer = _setup()
    try:
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer, **{field: value})
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


@pytest.mark.parametrize("state", ["claimed", "cancelled", "consumed", "expired"])
def test_non_active_engine_continuation_never_issues(state):
    engine, owner, _live, issuer = _setup()
    try:
        engine.db.execute(
            "UPDATE padiem_engine_continuations SET state=?",
            (state,),
        )
        engine.db.commit()
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer)
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_independent_d1_binding_is_mandatory():
    engine, owner, live, issuer = _setup()
    try:
        with pytest.raises(ValueError, match="separate D1"):
            AuthenticatedEngineBrowserP01TicketIssuer(
                engine_store=issuer._engine,
                owner_binding=engine,
                session_authority=live,
            )
    finally:
        owner.db.close()
        engine.db.close()


def test_issued_from_real_engine_pause_can_be_verified_only_after_independent_human_row():
    """Real Engine D1 -> owner D1 ticket -> first-party decision -> Engine reader.

    A TEST-SEEDED owner click is used; this does not attest a real human.
    No browser, Broker command, Product route or Production user is executed.
    """
    from app.browser_control_owner_p01_d1_read import IndependentOwnerP01D1Reader
    from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision

    engine, owner, _live, issuer = _setup()
    try:
        ref = _issue(issuer)
        record = asyncio.run(issuer._engine.resolve(
            app_id=APP_ID, continuation_ref=CONT_REF,
        ))
        reader = IndependentOwnerP01D1Reader(
            owner_p01_binding=owner, engine_continuation_binding=engine,
        )
        stamp = datetime.now(timezone.utc)
        decision = VerifiedApprovalDecision(
            decision_id="decision.firstparty.human.fixture",
            pause_id=record.pause.pause_id, outcome=ApprovalOutcome.APPROVED,
            authority_ref="b54_session:usr.real.test",
            evidence_ref="b54_decision:decision.firstparty.human.fixture",
            decided_at=stamp,
        )
        assert asyncio.run(reader(record, decision)) is None
        ticket = owner.db.execute(
            "SELECT * FROM padiem_browser_control_owner_p01_tickets WHERE ticket_ref=?",
            (ref,),
        ).fetchone()
        owner.db.execute(
            "INSERT INTO padiem_browser_control_owner_p01_decisions "
            "(app_id,continuation_ref,pause_id,owner_subject_id,run_id,"
            "invocation_sha256,original_request_fingerprint,"
            "original_admission_decision_id,decision_id,authority_ref,evidence_ref,"
            "decided_at,expires_at,revoked_at,outcome,authenticated_owner_session_ref)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ticket["app_id"], ticket["continuation_ref"], ticket["pause_id"],
                ticket["engine_owner_subject_id"], ticket["engine_run_id"],
                ticket["invocation_sha256"], ticket["original_request_fingerprint"],
                ticket["original_admission_decision_id"], decision.decision_id,
                decision.authority_ref, decision.evidence_ref,
                decision.decided_at.isoformat(), ticket["expires_at"],
                None, "approved", "session.authenticated.fixture",
            ),
        )
        owner.db.commit()
        proof = asyncio.run(reader(record, decision))
        assert proof is not None
        assert proof.original_admission_decision_id == record.original_admission.decision_id
        assert proof.invocation_sha256 == record.pause.invocation_sha256
        assert proof.user_subject_id == "owner.3782"
        # Even after human evidence exists, revoking the original server-issued
        # ticket invalidates the proof in the SAME read.
        owner.db.execute(
            "UPDATE padiem_browser_control_owner_p01_tickets SET revoked_at=? "
            "WHERE ticket_ref=?", (datetime.now(timezone.utc).isoformat(), ref),
        )
        owner.db.commit()
        assert asyncio.run(reader(record, decision)) is None
        assert engine.db.execute(
            "SELECT state FROM padiem_engine_continuations WHERE continuation_ref=?",
            (CONT_REF,),
        ).fetchone()[0] == "active"
    finally:
        owner.db.close()
        engine.db.close()


def test_real_engine_process_execute_pause_never_becomes_browser_p01_ticket():
    engine, service, _receipt, _request = setup(
        with_human_source=False, wrong_tool=True,
    )
    owner = _OwnerD1()
    try:
        issuer = AuthenticatedEngineBrowserP01TicketIssuer(
            engine_store=service._continuation_store,
            owner_binding=owner, session_authority=_SessionAuthority(),
        )
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer)
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()


def test_unverified_or_missing_live_session_provider_does_not_issue():
    engine, owner, live, issuer = _setup()
    try:
        async def invalid_provider(*, product_user_id, auth_session_ref):
            return {"product_user_id": product_user_id, "approved": True}
        live.resolve_active = invalid_provider
        with pytest.raises(ValueError, match="issuance unavailable"):
            _issue(issuer)
        assert owner.db.execute(
            "SELECT COUNT(*) FROM padiem_browser_control_owner_p01_tickets"
        ).fetchone()[0] == 0
    finally:
        owner.db.close()
        engine.db.close()
