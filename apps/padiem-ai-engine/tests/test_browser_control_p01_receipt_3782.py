"""#3782: Engine D1 browser.control approved receipt — source-only.

Synthetic Core pause/decision test fixtures do NOT mint a real P01 decision.
The receipt writer/reader is not configured in any product Worker route.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.browser_control_approval_binding import (
    BROWSER_P01_AGENT_ID,
    BROWSER_P01_APP_ID,
    BROWSER_P01_CANONICAL_TOOL_ID,
    build_inert_browser_control_approval_binding,
)
from app.browser_control_human_approval import (
    IndependentlyAuthenticatedBrowserControlP01,
)
from app.browser_control_p01_receipt import (
    ENGINE_BROWSER_CONTROL_P01_RECEIPT_PRODUCER_WIRED,
    ENGINE_BROWSER_CONTROL_P01_RECEIPT_READER_WIRED,
    CloudflareD1BrowserControlP01ReceiptStore,
    EngineApprovedBrowserControlP01Receipt,
)
from app.browser_control_pause_identity import TrustedBrowserControlPauseIdentity
from app.continuation_d1 import (
    CloudflareD1IdentityBoundContinuationStore,
    _identity_json,
    _pause_json,
)
from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission_resume import OriginalAdmissionBinding
from app.tool_execution_service import (
    ToolExecutionEngineService,
    _PendingToolContinuation,
)
from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

NOW = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)
APP_ID = "padiem.browser.test"
CONT_REF = "cont_3782canonical"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class _Statement:
    def __init__(self, db: sqlite3.Connection, sql: str):
        self._db = db
        self._sql = sql
        self._params: tuple[Any, ...] = ()

    def bind(self, *args):
        self._params = args
        return self

    async def first(self):
        cursor = self._db.execute(self._sql, self._params)
        row = cursor.fetchone()
        # D1 UPDATE...RETURNING is committed as one statement. The local
        # SQLite fake must not leave an open transaction before D1.batch().
        if self._sql.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE ")):
            self._db.commit()
        return dict(row) if row else None

    async def run(self):
        cursor = self._db.execute(self._sql, self._params)
        self._db.commit()
        return {"meta": {"changes": cursor.rowcount}}


class _D1:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript((MIGRATIONS / "0002_engine_continuations.sql").read_text(encoding="utf-8"))
        self.db.executescript((MIGRATIONS / "0009_browser_control_p01_receipts.sql").read_text(encoding="utf-8"))

    def prepare(self, sql):
        return _Statement(self.db, sql)

    async def batch(self, statements):
        """Test-only SQLite D1 batch: one transaction, rollback on any error."""
        try:
            self.db.execute("BEGIN")
            outcomes = []
            for statement in statements:
                result = self.db.execute(statement._sql, statement._params)
                outcomes.append({"meta": {"changes": result.rowcount}})
            self.db.commit()
            return outcomes
        except Exception:
            self.db.rollback()
            raise


@pytest.fixture
def db():
    instance = _D1()
    try:
        yield instance
    finally:
        instance.db.close()


def pause(**changes):
    p = ApprovalPause(
        pause_id="pause.browser.3782", run_id="run.browser.3782",
        agent_runtime_id="agent.browser.3782", tool_id="browser.control",
        invocation_sha256="a" * 64, requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1, created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=2), approval_scope=("browser.control",),
    )
    return replace(p, **changes) if changes else p


def decision(p=None, **changes):
    p = p or pause()
    d = VerifiedApprovalDecision(
        decision_id="decision.browser.3782", pause_id=p.pause_id,
        outcome=ApprovalOutcome.APPROVED, authority_ref="p01.real.authority.test",
        evidence_ref="evidence.browser.3782", decided_at=NOW - timedelta(seconds=5),
    )
    return replace(d, **changes) if changes else d


def seed(db, p=None, *, state="consumed", app_id=APP_ID, continuation_ref=CONT_REF):
    p = p or pause()
    db.db.execute(
        "INSERT INTO padiem_engine_continuations "
        "(app_id,continuation_ref,pause_json,execution_identity_json,state,"
        "claim_token,cancel_reason,cancel_event_fingerprint,created_at,updated_at,expires_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (app_id, continuation_ref, _pause_json(p), "{}",
         state, None, None, None,
         (NOW - timedelta(minutes=1)).isoformat(),
         NOW.isoformat(), p.expires_at.isoformat()),
    )
    db.db.commit()


def approved(p=None, d=None, *, app_id=APP_ID, continuation_ref=CONT_REF):
    p = p or pause()
    return EngineApprovedBrowserControlP01Receipt.from_verified_engine_decision(
        app_id=app_id, continuation_ref=continuation_ref,
        pause=p, decision=d or decision(p), now=NOW,
    )


def run(awaitable):
    return asyncio.run(awaitable)


def test_consumed_canonical_engine_receipt_is_durable_and_revocable(db):
    p = pause()
    seed(db, p)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    receipt = approved(p)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    run(store.store_completed(receipt, now=NOW))
    restarted = CloudflareD1BrowserControlP01ReceiptStore(db)
    assert run(restarted.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == receipt
    assert run(restarted.revoke(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is True
    assert run(restarted.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    assert run(restarted.revoke(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is False


@pytest.mark.parametrize("state", ["active", "claimed", "cancelled", "expired", "cancelling"])
def test_no_receipt_for_unconsumed_engine_continuation(db, state):
    seed(db, state=state)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="no matching consumed"):
        run(store.store_completed(approved(), now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


@pytest.mark.parametrize("change", [
    {"tool_id": "process.execute"},
    {"approval_scope": ("process.execute",)},
    {"approval_scope": ("browser.control", "process.execute")},
    {"run_id": "run.other"},
])
def test_wrong_tool_scope_or_run_cannot_store(db, change):
    canonical = pause()
    seed(db, canonical)
    submitted = pause(**change)
    if change.get("tool_id") or change.get("approval_scope"):
        with pytest.raises(ValueError, match="not approved"):
            approved(submitted)
    else:
        with pytest.raises(ValueError, match="no matching consumed"):
            run(CloudflareD1BrowserControlP01ReceiptStore(db).store_completed(
                approved(submitted), now=NOW,
            ))


@pytest.mark.parametrize("decision_change", [
    {"outcome": ApprovalOutcome.DENIED},
    {"pause_id": "pause.other"},
    {"decided_at": NOW + timedelta(seconds=1)},
    {"decided_at": NOW - timedelta(days=1)},
])
def test_denied_mismatched_or_invalid_decision_not_receipted(decision_change):
    with pytest.raises((ValueError, AgentApprovalError)):
        approved(d=decision(**decision_change))


def test_pause_not_expired_at_issue_or_cannot_be_receipted():
    p = pause(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        approved(p)


def test_duplicate_or_replayed_approved_decision_never_changes_row(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    original = approved()
    run(store.store_completed(original, now=NOW))
    with pytest.raises(ValueError, match="duplicate"):
        run(store.store_completed(original, now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == original


def test_other_owner_app_or_missing_continuation_never_receipted(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    for receipt in (approved(app_id="another.app"), approved(continuation_ref="cont_missing")):
        with pytest.raises(ValueError, match="no matching consumed"):
            run(store.store_completed(receipt, now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_expired_and_cancelled_receipts_never_visible(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    assert run(store.resolve_active(
        app_id=APP_ID, continuation_ref=CONT_REF, now=NOW + timedelta(minutes=3),
    )) is None
    db.db.execute(
        "UPDATE padiem_engine_continuations SET state='cancelled' "
        "WHERE app_id=? AND continuation_ref=?", (APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_receipt_invalidated_when_canonical_pause_rebound(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    db.db.execute(
        "UPDATE padiem_engine_continuations SET pause_json=? "
        "WHERE app_id=? AND continuation_ref=?",
        (_pause_json(pause(invocation_sha256="b" * 64)), APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_receipt_shape_is_opaque_and_product_routes_remain_unwired(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    columns = [r[1] for r in db.db.execute(
        "PRAGMA table_info(padiem_engine_browser_control_p01_receipts)"
    ).fetchall()]
    assert not any(x in columns for x in (
        "arguments", "approval_payload", "access_token", "cookie",
        "action", "origin_url", "user_message",
    ))
    assert ENGINE_BROWSER_CONTROL_P01_RECEIPT_PRODUCER_WIRED is False
    assert ENGINE_BROWSER_CONTROL_P01_RECEIPT_READER_WIRED is False


@pytest.mark.parametrize("mutation", [
    {"approval_scope": ("process.execute",)},
    {"approval_scope": ("browser.control", "process.execute")},
    {"expires_at": NOW + timedelta(minutes=1)},
    {"tool_id": "process.execute"},
    {"run_id": "run.changed"},
])
def test_canonical_pause_changes_hide_previously_saved_receipt(db, mutation):
    original = pause()
    seed(db, original)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(original), now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW))
    db.db.execute(
        "UPDATE padiem_engine_continuations SET pause_json=? "
        "WHERE app_id=? AND continuation_ref=?",
        (_pause_json(replace(original, **mutation)), APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_approval_receipt_cannot_be_written_before_engine_continuation_exists(db):
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="no matching consumed"):
        run(store.store_completed(approved(), now=NOW))
    count = db.db.execute(
        "SELECT COUNT(*) FROM padiem_engine_browser_control_p01_receipts"
    ).fetchone()[0]
    assert count == 0


def test_engine_receipt_migration_is_idempotent_in_synthetic_sqlite(db):
    sql = (MIGRATIONS / "0009_browser_control_p01_receipts.sql").read_text(encoding="utf-8")
    db.db.executescript(sql)
    db.db.executescript(sql)
    assert len([
        col for col in db.db.execute(
            "PRAGMA table_info(padiem_engine_browser_control_p01_receipts)"
        )
        if col[1] == "invocation_sha256"
    ]) == 1


def _claim(db, *, state="claimed", token="claim_browser.3782", p=None, ref=CONT_REF):
    seed(db, p, state=state, continuation_ref=ref)
    db.db.execute(
        "UPDATE padiem_engine_continuations SET claim_token=? "
        "WHERE app_id=? AND continuation_ref=?",
        (token, APP_ID, ref),
    )
    db.db.commit()


def _status(db, ref=CONT_REF):
    row = db.db.execute(
        "SELECT state, claim_token FROM padiem_engine_continuations "
        "WHERE app_id=? AND continuation_ref=?", (APP_ID, ref),
    ).fetchone()
    return tuple(row) if row else None


def _atomic_commit(store, *, token="claim_browser.3782", p=None, d=None, ref=CONT_REF):
    p = p or pause()
    return run(store.commit_claimed_browser_approval(
        app_id=APP_ID, continuation_ref=ref, claim_token=token,
        pause=p, decision=d or decision(p), now=NOW,
    ))


def test_claim_and_receipt_are_one_atomic_d1_transaction(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    receipt = _atomic_commit(store)
    assert _status(db) == ("consumed", None)
    assert receipt == approved()
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == receipt
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store)
    assert _status(db) == ("consumed", None)


@pytest.mark.parametrize("bad_state", ["active", "consumed", "cancelled", "expired", "cancelling"])
def test_no_claim_cannot_atomically_commit_receipt(db, bad_state):
    _claim(db, state=bad_state, token=None)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store)
    assert _status(db) == (bad_state, None)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_wrong_claim_token_has_zero_consumption_and_zero_receipt(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store, token="claim_other.3782")
    assert _status(db) == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    assert _atomic_commit(store) == approved()


@pytest.mark.parametrize("pause_change", [
    {"run_id": "run.other"},
    {"invocation_sha256": "b" * 64},
    {"approval_scope": ("process.execute",)},
    {"expires_at": NOW + timedelta(minutes=1)},
])
def test_pause_drift_rolls_back_claimed_state(db, pause_change):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    try:
        _atomic_commit(store, p=pause(**pause_change))
    except (ValueError, AgentApprovalError):
        pass
    else:
        pytest.fail("pause drift was accepted")
    assert _status(db) == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_duplicate_decision_causes_transaction_rollback_on_second_claim(db):
    _claim(db)
    _claim(db, ref="cont_secondary.3782")
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    _atomic_commit(store)
    with pytest.raises(ValueError, match="commit failed"):
        _atomic_commit(store, ref="cont_secondary.3782")
    assert _status(db, "cont_secondary.3782") == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(
        app_id=APP_ID, continuation_ref="cont_secondary.3782", now=NOW,
    )) is None


def test_no_d1_batch_never_downgrades_to_multi_transaction_write(db):
    _claim(db)
    original_batch = db.batch
    db.batch = None
    try:
        with pytest.raises(TypeError, match="batch is required"):
            _atomic_commit(CloudflareD1BrowserControlP01ReceiptStore(db))
    finally:
        db.batch = original_batch
    assert _status(db) == ("claimed", "claim_browser.3782")


def test_wrong_decision_or_tool_cannot_commit_browser_receipt(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises((ValueError, AgentApprovalError)):
        _atomic_commit(store, d=decision(outcome=ApprovalOutcome.DENIED))
    assert _status(db) == ("claimed", "claim_browser.3782")
    with pytest.raises((ValueError, AgentApprovalError)):
        _atomic_commit(store, p=pause(tool_id="process.execute"))
    assert _status(db) == ("claimed", "claim_browser.3782")


AGENT = "agent.browser.test.3782"
CANONICAL_TOOL = "tool:browser:control@1"


def _fixture_human_p01(record, decision):
    """TEST-ONLY stand-in: real product human-identity source is NOT present."""
    original = record.original_admission
    assert original is not None
    return IndependentlyAuthenticatedBrowserControlP01(
        app_id=record.app_id,
        continuation_ref=record.continuation_ref,
        user_subject_id=record.execution_identity.subject_id,
        run_id=record.pause.run_id,
        invocation_sha256=record.pause.invocation_sha256,
        original_request_fingerprint=original.request_fingerprint,
        original_admission_decision_id=original.decision_id,
        decision=decision,
        user_approval_evidence_ref=decision.evidence_ref,
    )


def setup(*, with_receipts=True, wrong_tool=False, mismatch_digest=False, with_human_source=True):
    db = _D1()
    moment = datetime.now(timezone.utc)
    invocation = ToolInvocation(
        tool_id="browser.control",
        arguments={"browser_session_ref": "browser.3782", "origin_scope": "https://example.org"},
    )
    canonical_digest = tool_invocation_digest(invocation)
    p = replace(
        pause(),
        agent_runtime_id=AGENT,
        tool_id="process.execute" if wrong_tool else "browser.control",
        approval_scope=("process.execute",) if wrong_tool else ("browser.control",),
        invocation_sha256="f" * 64 if mismatch_digest else canonical_digest,
        created_at=moment - timedelta(seconds=5),
        expires_at=moment + timedelta(minutes=4),
    )
    # Populate the canonical D1 identity required by its real record decoder.
    identity = ContinuationExecutionIdentity(
        request_fingerprint="a" * 64, plan_fingerprint=None,
        subject_id="owner.3782", recovery_policy_fingerprint=None,
        max_retries=0, require_evidence=True, require_verification=True,
    )
    db.db.execute(
        "INSERT INTO padiem_engine_continuations "
        "(app_id,continuation_ref,pause_json,execution_identity_json,state,"
        "claim_token,cancel_reason,cancel_event_fingerprint,created_at,updated_at,expires_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (APP_ID, CONT_REF, _pause_json(p),
         _identity_json(identity, OriginalAdmissionBinding(
             decision_id="decision.original.fixture",
             app_id=APP_ID,
             subject_id=identity.subject_id,
             authority_ref="authority.original.fixture",
             policy_revision="policy.v1",
             request_fingerprint=identity.request_fingerprint,
         )), "active", None, None, None,
         moment.isoformat(), moment.isoformat(), p.expires_at.isoformat()),
    )
    db.db.commit()
    continuation = CloudflareD1IdentityBoundContinuationStore(db)
    receipts = CloudflareD1BrowserControlP01ReceiptStore(db)

    def resolve_binding(app_id):
        if app_id != APP_ID:
            return None
        return SimpleNamespace(
            app_id=APP_ID,
            resolve_authority=lambda agent_id: SimpleNamespace(agent_id=agent_id),
            resolve_tool=lambda tool_id: SimpleNamespace(
                runtime_tool_id="process.execute" if wrong_tool else "browser.control",
            ),
        )
    service = ToolExecutionEngineService(
        tool_binding_resolver=resolve_binding,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=continuation,
        browser_control_p01_receipts=receipts if with_receipts else None,
        browser_control_human_p01_resolver=(
            _fixture_human_p01 if with_receipts and with_human_source else None
        ),
    )
    service._pending[p.pause_id] = _PendingToolContinuation(
        app_id=APP_ID, canonical_agent_id=AGENT,
        canonical_tool_id=CANONICAL_TOOL, invocation=invocation,
    )
    decision = {
        "decision_id": "dec.browser.3782",
        "pause_id": p.pause_id,
        "outcome": "approved",
        "authority_ref": "p01.trusted.fixture",
        "evidence_ref": "evidence.test.3782",
        "decided_at": moment.isoformat(),
    }
    request = {"app_id": APP_ID, "continuation_ref": CONT_REF, "decision": decision}
    return db, service, receipts, request


def db_state(db):
    row = db.db.execute(
        "SELECT state,claim_token FROM padiem_engine_continuations "
        "WHERE app_id=? AND continuation_ref=?", (APP_ID, CONT_REF),
    ).fetchone()
    count = db.db.execute("SELECT COUNT(*) FROM padiem_engine_browser_control_p01_receipts").fetchone()[0]
    return tuple(row), count


def test_first_party_verified_p01_resume_atomically_records_without_browser_handler():
    db, service, receipts, request = setup()
    try:
        first = run(service.resume_payload(request))
        assert first.status_code == 200, first.body
        assert first.body["tool"]["status"] == "approval_recorded"
        assert first.body["tool"]["browser_action_executed"] is False
        assert first.body["tool"]["broker_command_dispatched"] is False
        assert db_state(db) == (("consumed", None), 1)
        saved = run(receipts.resolve_active(
            app_id=APP_ID, continuation_ref=CONT_REF, now=datetime.now(timezone.utc),
        ))
        assert saved is not None
        assert saved.invocation_sha256 == tool_invocation_digest(
            ToolInvocation(tool_id="browser.control", arguments={
                "browser_session_ref": "browser.3782", "origin_scope": "https://example.org",
            })
        )
        again = run(service.resume_payload(request))
        assert again.status_code != 200
        assert db_state(db) == (("consumed", None), 1)
    finally:
        db.db.close()


def test_unwired_product_default_fails_closed_without_claim_or_receipt():
    db, service, _receipts, request = setup(with_receipts=False)
    try:
        result = run(service.resume_payload(request))
        assert result.status_code == 503
        assert result.body["error"]["code"] == "browser_control_p01_receipt_unavailable"
        assert db_state(db) == (("active", None), 0)
    finally:
        db.db.close()


@pytest.mark.parametrize("mutation", ["denied", "wrong_pause", "wrong_app", "digest_drift", "wrong_tool"])
def test_wrong_first_party_decision_or_canonical_identity_cannot_store(mutation):
    db, service, _receipts, request = setup(
        wrong_tool=mutation == "wrong_tool",
        mismatch_digest=mutation == "digest_drift",
    )
    try:
        if mutation == "denied":
            request["decision"]["outcome"] = "denied"
        elif mutation == "wrong_pause":
            request["decision"]["pause_id"] = "pause.other"
        elif mutation == "wrong_app":
            request["app_id"] = "another.owner.app"
        result = run(service.resume_payload(request))
        assert result.status_code != 200
        assert db_state(db)[1] == 0
    finally:
        db.db.close()


def test_non_matching_or_untrusted_d1_adapter_cannot_be_injected():
    db, _service, receipts, _request = setup()
    other = _D1()
    try:
        other_store = CloudflareD1IdentityBoundContinuationStore(other)
        with pytest.raises(ValueError, match="SAME trusted Engine D1"):
            ToolExecutionEngineService(
                continuation_store=other_store, browser_control_p01_receipts=receipts,
            )
    finally:
        db.db.close()
        other.db.close()


def test_browser_receipt_atomic_failure_releases_claim_and_never_issues_receipt():
    db, service, _receipts, request = setup()
    # Simulate transient D1 batch write failure after the Engine claim.
    original = db.batch
    async def failed_batch(statements):
        raise RuntimeError("synthetic D1 write outage")
    db.batch = failed_batch
    try:
        result = run(service.resume_payload(request))
        assert result.status_code == 503
        assert db_state(db)[1] == 0
        assert db_state(db)[0][0] in ("active", "expired")
    finally:
        db.batch = original
        db.db.close()


# #3782: real Engine Core ToolRuntime P01 pause -> trusted run admission
# -> D1 continuation issue -> first-party decision -> atomic P01 receipt.
# The fake admission in this test is TEST ONLY and cannot authorize Production.
_BROWSER_ARGS = {
    "browser_session_ref": "browser.3782",
    "run_ref": "run.3782",
    "workspace_ref": "workspace.3782",
    "owner_ref": "owner.3782",
    "device_id": "device.3782",
    "origin_scope": "https://example.org",
    "allowed_action_classes": ["click", "focus"],
    "ttl_seconds": 60,
    "max_actions": 1,
}


def _trusted_browser_identity(*, app_id=BROWSER_P01_APP_ID, subject="owner.3782"):
    identity = ContinuationExecutionIdentity(
        request_fingerprint="d" * 64,
        plan_fingerprint=None,
        subject_id=subject,
        recovery_policy_fingerprint=None,
        max_retries=0,
        require_evidence=True,
        require_verification=True,
    )
    admission = OriginalAdmissionBinding(
        decision_id="decision.real.owner.fixture",
        app_id=app_id,
        subject_id=subject,
        authority_ref="authority.real.owner.fixture",
        policy_revision="policy.v1",
        request_fingerprint=identity.request_fingerprint,
    )
    return TrustedBrowserControlPauseIdentity(
        execution_identity=identity,
        original_admission=admission,
    )


def _make_browser_d1_issue_service(db, *, provider_enabled=True, supplied=None):
    binding = build_inert_browser_control_approval_binding()
    continuation = CloudflareD1IdentityBoundContinuationStore(db)
    receipts = CloudflareD1BrowserControlP01ReceiptStore(db)
    def owner_provider(app_id, authority, invocation):
        assert app_id == BROWSER_P01_APP_ID
        assert authority.canonical_agent_id == BROWSER_P01_AGENT_ID
        assert invocation.tool_id == "browser.control"
        return _trusted_browser_identity() if supplied is None else supplied
    service = ToolExecutionEngineService(
        tool_binding_resolver=lambda app_id: (
            binding if app_id == BROWSER_P01_APP_ID else None
        ),
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=continuation,
        browser_control_p01_receipts=receipts,
        browser_control_original_admission=owner_provider if provider_enabled else None,
        browser_control_human_p01_resolver=_fixture_human_p01,
    )
    request = {
        "app_id": BROWSER_P01_APP_ID,
        "agent_id": BROWSER_P01_AGENT_ID,
        "tool_id": BROWSER_P01_CANONICAL_TOOL_ID,
        "arguments": dict(_BROWSER_ARGS),
    }
    return service, continuation, receipts, request


def test_real_core_pause_issues_identity_bound_d1_and_atomic_receipt(db):
    service, continuation, receipts, request = _make_browser_d1_issue_service(db)
    paused = run(service.execute_payload(request))
    assert paused.status_code == 202, paused.body
    ref = paused.body["tool"]["continuation_ref"]
    stored = run(continuation.resolve(app_id=BROWSER_P01_APP_ID, continuation_ref=ref))
    assert stored.pause.tool_id == "browser.control"
    assert stored.execution_identity == _trusted_browser_identity().execution_identity
    assert stored.original_admission == _trusted_browser_identity().original_admission
    assert stored.pause.invocation_sha256 == tool_invocation_digest(
        ToolInvocation(tool_id="browser.control", arguments=_BROWSER_ARGS)
    )
    assert stored.state == "active"
    assert run(receipts.resolve_active(
        app_id=BROWSER_P01_APP_ID, continuation_ref=ref, now=datetime.now(timezone.utc),
    )) is None
    result = run(service.resume_payload({
        "app_id": BROWSER_P01_APP_ID,
        "continuation_ref": ref,
        "decision": {
            "decision_id": "decision.browser.test",
            "pause_id": stored.pause.pause_id,
            "outcome": "approved",
            "authority_ref": "authority.test.firstparty",
            "evidence_ref": "evidence.browser.test",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }))
    assert result.status_code == 200, result.body
    assert result.body["tool"]["status"] == "approval_recorded"
    assert result.body["tool"]["browser_action_executed"] is False
    assert result.body["tool"]["broker_command_dispatched"] is False
    active = run(receipts.resolve_active(
        app_id=BROWSER_P01_APP_ID, continuation_ref=ref, now=datetime.now(timezone.utc),
    ))
    assert active is not None
    assert active.invocation_sha256 == stored.pause.invocation_sha256
    rows = db.db.execute(
        "SELECT state,claim_token FROM padiem_engine_continuations WHERE "
        "app_id=? AND continuation_ref=?", (BROWSER_P01_APP_ID, ref),
    ).fetchone()
    assert tuple(rows) == ("consumed", None)


@pytest.mark.parametrize("failure", [
    "no_provider", "wrong_app", "wrong_subject", "wrong_fingerprint",
    "missing_subject", "wrong_type",
])
def test_d1_browser_pause_refuses_untrusted_identity_without_row(db, failure):
    trusted = _trusted_browser_identity()
    replacement = trusted
    if failure == "wrong_app":
        replacement = replace(trusted, original_admission=replace(
            trusted.original_admission, app_id="other.app",
        ))
    elif failure == "wrong_subject":
        replacement = replace(trusted, original_admission=replace(
            trusted.original_admission, subject_id="another.subject",
        ))
    elif failure == "wrong_fingerprint":
        replacement = replace(trusted, original_admission=replace(
            trusted.original_admission, request_fingerprint="e" * 64,
        ))
    elif failure == "missing_subject":
        replacement = replace(trusted, execution_identity=replace(
            trusted.execution_identity, subject_id=None,
        ))
    elif failure == "wrong_type":
        replacement = {"approval": "approved"}
    service, _cont, _receipts, request = _make_browser_d1_issue_service(
        db, provider_enabled=failure != "no_provider", supplied=replacement,
    )
    response = run(service.execute_payload(request))
    assert response.status_code == 503, response.body
    assert service._pending == {}
    assert db.db.execute(
        "SELECT COUNT(*) FROM padiem_engine_continuations"
    ).fetchone()[0] == 0
    assert db.db.execute(
        "SELECT COUNT(*) FROM padiem_engine_browser_control_p01_receipts"
    ).fetchone()[0] == 0


def test_original_admission_provider_cannot_be_set_without_receipt_store(db):
    original = _trusted_browser_identity()
    with pytest.raises(ValueError, match="same trusted D1 receipt"):
        ToolExecutionEngineService(
            continuation_store=CloudflareD1IdentityBoundContinuationStore(db),
            browser_control_original_admission=lambda app, auth, inv: original,
        )


def test_generic_service_authenticated_approval_cannot_record_human_p01(db):
    service, continuation, receipts, request = _make_browser_d1_issue_service(db)
    # The real first-party submission converter alone cannot establish consent.
    service._browser_control_human_p01_resolver = None
    paused = run(service.execute_payload(request))
    assert paused.status_code == 202, paused.body
    ref = paused.body["tool"]["continuation_ref"]
    before = run(continuation.resolve(app_id=BROWSER_P01_APP_ID, continuation_ref=ref))
    result = run(service.resume_payload({
        "app_id": BROWSER_P01_APP_ID,
        "continuation_ref": ref,
        "decision": {
            "decision_id": "decision.browser.test", "pause_id": before.pause.pause_id,
            "outcome": "approved", "authority_ref": "service.identity.only",
            "evidence_ref": "unverified.user.approval",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }))
    assert result.status_code == 503, result.body
    assert result.body["error"]["code"] == "browser_control_human_p01_unavailable"
    assert run(continuation.resolve(app_id=BROWSER_P01_APP_ID, continuation_ref=ref)).state == "active"
    assert run(receipts.resolve_active(
        app_id=BROWSER_P01_APP_ID, continuation_ref=ref, now=datetime.now(timezone.utc),
    )) is None


@pytest.mark.parametrize("mutated", [
    "missing", "dict", "different_app", "other_user", "other_run",
    "other_invocation", "other_original_request", "other_original_admission",
    "other_decision", "other_evidence", "exception",
])
def test_independent_user_approval_mismatch_rejects_without_consuming(db, mutated):
    service, continuation, receipts, request = _make_browser_d1_issue_service(db)
    paused = run(service.execute_payload(request))
    assert paused.status_code == 202
    ref = paused.body["tool"]["continuation_ref"]
    stored = run(continuation.resolve(app_id=BROWSER_P01_APP_ID, continuation_ref=ref))
    if mutated == "missing":
        service._browser_control_human_p01_resolver = None
    elif mutated == "exception":
        def unavailable(record, decision):
            raise RuntimeError("trusted approval service down")
        service._browser_control_human_p01_resolver = unavailable
    else:
        def malformed(record, decision):
            valid = _fixture_human_p01(record, decision)
            edits = {
                "different_app": {"app_id": "some.other.app"},
                "other_user": {"user_subject_id": "wrong.owner"},
                "other_run": {"run_id": "wrong.run"},
                "other_invocation": {"invocation_sha256": "f" * 64},
                "other_original_request": {"original_request_fingerprint": "f" * 64},
                "other_original_admission": {"original_admission_decision_id": "wrong.decision"},
                "other_decision": {"decision": replace(decision, decision_id="wrong.decision")},
                "other_evidence": {"user_approval_evidence_ref": "evidence.other"},
            }
            if mutated == "dict":
                return {"decision": "approved"}
            return replace(valid, **edits[mutated])
        service._browser_control_human_p01_resolver = malformed
    result = run(service.resume_payload({
        "app_id": BROWSER_P01_APP_ID,
        "continuation_ref": ref,
        "decision": {
            "decision_id": "decision.browser.test", "pause_id": stored.pause.pause_id,
            "outcome": "approved", "authority_ref": "test.service.identity",
            "evidence_ref": "evidence.browser.test",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }))
    assert result.status_code == 503, result.body
    assert result.body["error"]["code"] == "browser_control_human_p01_unavailable"
    assert run(continuation.resolve(app_id=BROWSER_P01_APP_ID, continuation_ref=ref)).state == "active"
    assert run(receipts.resolve_active(
        app_id=BROWSER_P01_APP_ID, continuation_ref=ref, now=datetime.now(timezone.utc),
    )) is None
