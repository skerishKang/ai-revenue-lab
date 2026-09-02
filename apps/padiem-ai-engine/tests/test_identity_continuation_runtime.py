from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from padiem_ai_core import ApprovalOutcome, ApprovalPause, ApprovalRequirement, VerifiedApprovalDecision

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.continuation_binding import (
    IdentityBoundContinuationRecord,
    InMemoryIdentityBoundContinuationStore,
)
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.continuation_identity import ContinuationExecutionIdentity
from app.orchestration_service import ApprovalDecisionSubmission, ContinuationRecord
from app.service import ServiceContractError


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc) - timedelta(seconds=1)
    return ApprovalPause(
        pause_id="pause_1",
        run_id="run_1",
        agent_runtime_id="agent_runtime_1",
        tool_id="tool_demo",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="trace_1",
        plan_id="plan_1",
        approval_scope=("tool:demo",),
    )


def _identity() -> ContinuationExecutionIdentity:
    return ContinuationExecutionIdentity(
        request_fingerprint="b" * 64,
        plan_fingerprint="c" * 64,
        subject_id="subject_1",
        recovery_policy_fingerprint="d" * 64,
        max_retries=1,
        require_evidence=True,
        require_verification=False,
    )


def test_authenticated_first_party_verifier_constructs_core_verified_decision():
    pause = _pause()
    submission = ApprovalDecisionSubmission(
        decision_id="decision_1",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="b62_session_subject_1",
        evidence_ref="b62_decision_evidence_1",
        decided_at=datetime.now(timezone.utc),
    )
    verified = AuthenticatedFirstPartyApprovalDecisionVerifier().verify(
        submission, pause=pause, app_id="b62"
    )
    assert isinstance(verified, VerifiedApprovalDecision)
    assert verified.pause_id == pause.pause_id
    assert verified.outcome is ApprovalOutcome.APPROVED


def test_authenticated_first_party_verifier_rejects_wrong_pause_or_future_decision():
    pause = _pause()
    verifier = AuthenticatedFirstPartyApprovalDecisionVerifier()
    wrong = ApprovalDecisionSubmission(
        decision_id="decision_1",
        pause_id="pause_other",
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="b62_session_subject_1",
        evidence_ref="b62_decision_evidence_1",
        decided_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ServiceContractError) as raised:
        verifier.verify(wrong, pause=pause, app_id="b62")
    assert raised.value.code == "approval_decision_mismatch"

    future = ApprovalDecisionSubmission(
        decision_id="decision_2",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="b62_session_subject_1",
        evidence_ref="b62_decision_evidence_2",
        decided_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    with pytest.raises(ServiceContractError) as raised:
        verifier.verify(future, pause=pause, app_id="b62")
    assert raised.value.code == "invalid_approval_decision"


def test_identity_bound_reference_store_preserves_generic_atomic_cancel_contract():
    store = InMemoryIdentityBoundContinuationStore()
    ref = store.issue(app_id="b62", pause=_pause(), execution_identity=_identity())
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert isinstance(record, IdentityBoundContinuationRecord)
    assert isinstance(record, ContinuationRecord)

    cancel_claim = store.claim_cancel(
        app_id="b62", continuation_ref=ref, reason="user_cancelled"
    )
    assert cancel_claim.state == "cancelling"
    assert cancel_claim.claim_token is not None
    cancelled = store.commit_cancel(
        app_id="b62",
        continuation_ref=ref,
        claim_token=cancel_claim.claim_token,
    )
    assert cancelled.state == "cancelled"
    with pytest.raises(ServiceContractError) as raised:
        store.resolve(app_id="b62", continuation_ref=ref)
    assert raised.value.code == "continuation_cancelled"


class FakeStatement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self.db = db
        self.sql = " ".join(sql.split())
        self.params = ()

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        if self.sql.startswith("INSERT INTO padiem_engine_continuations"):
            (
                app_id,
                ref,
                pause_json,
                identity_json,
                state,
                claim_token,
                cancel_reason,
                cancel_fp,
                created_at,
                updated_at,
                expires_at,
            ) = self.params
            self.db.records[(app_id, ref)] = {
                "app_id": app_id,
                "continuation_ref": ref,
                "pause_json": pause_json,
                "execution_identity_json": identity_json,
                "state": state,
                "claim_token": claim_token,
                "cancel_reason": cancel_reason,
                "cancel_event_fingerprint": cancel_fp,
                "created_at": created_at,
                "updated_at": updated_at,
                "expires_at": expires_at,
            }
            return {"success": True}
        if "SET state='expired'" in self.sql:
            updated_at, app_id, ref = self.params
            row = self.db.records.get((app_id, ref))
            if row and row["state"] == "active":
                row["state"] = "expired"
                row["claim_token"] = None
                row["updated_at"] = updated_at
            return {"success": True}
        raise AssertionError(f"unexpected run SQL: {self.sql}")

    async def first(self):
        if self.sql.startswith("SELECT"):
            app_id, ref = self.params
            row = self.db.records.get((app_id, ref))
            return dict(row) if row else None
        if not self.sql.startswith("UPDATE padiem_engine_continuations"):
            raise AssertionError(f"unexpected first SQL: {self.sql}")

        if "SET state='claimed'" in self.sql:
            token, updated_at, app_id, ref, now = self.params
            row = self.db.records.get((app_id, ref))
            if row and row["state"] == "active" and row["expires_at"] > now:
                row["state"] = "claimed"
                row["claim_token"] = token
                row["updated_at"] = updated_at
                return dict(row)
            return None
        if "SET state='consumed'" in self.sql:
            updated_at, app_id, ref, token = self.params
            row = self.db.records.get((app_id, ref))
            if row and row["state"] == "claimed" and row["claim_token"] == token:
                row["state"] = "consumed"
                row["claim_token"] = None
                row["updated_at"] = updated_at
                return dict(row)
            return None
        if "SET state='cancelling'" in self.sql:
            token, reason, updated_at, app_id, ref, now = self.params
            row = self.db.records.get((app_id, ref))
            if row and row["state"] == "active" and row["expires_at"] > now:
                row["state"] = "cancelling"
                row["claim_token"] = token
                row["cancel_reason"] = reason
                row["updated_at"] = updated_at
                return dict(row)
            return None
        if "SET state='cancelled'" in self.sql:
            updated_at, app_id, ref, token = self.params
            row = self.db.records.get((app_id, ref))
            if row and row["state"] == "cancelling" and row["claim_token"] == token:
                row["state"] = "cancelled"
                row["claim_token"] = None
                row["updated_at"] = updated_at
                return dict(row)
            return None
        if "SET state=CASE WHEN expires_at<=?" in self.sql:
            now, updated_at, app_id, ref, token = self.params
            row = self.db.records.get((app_id, ref))
            expected = "cancelling" if "cancel_reason=NULL" in self.sql else "claimed"
            if row and row["state"] == expected and row["claim_token"] == token:
                row["state"] = "expired" if row["expires_at"] <= now else "active"
                row["claim_token"] = None
                row["updated_at"] = updated_at
                if expected == "cancelling":
                    row["cancel_reason"] = None
                    row["cancel_event_fingerprint"] = None
                return dict(row)
            return None
        raise AssertionError(f"unexpected update SQL: {self.sql}")


class FakeD1:
    def __init__(self) -> None:
        self.records = {}

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)


def test_d1_identity_bound_store_issue_claim_release_commit_and_cancel():
    async def scenario():
        db = FakeD1()
        store = CloudflareD1IdentityBoundContinuationStore(db)
        ref = await store.issue(app_id="b62", pause=_pause(), execution_identity=_identity())
        resolved = await store.resolve(app_id="b62", continuation_ref=ref)
        assert resolved.execution_identity == _identity()
        assert resolved.pause.approval_scope == ("tool:demo",)

        claimed = await store.claim(app_id="b62", continuation_ref=ref)
        assert claimed.state == "claimed"
        await store.release(
            app_id="b62", continuation_ref=ref, claim_token=claimed.claim_token
        )
        assert (await store.resolve(app_id="b62", continuation_ref=ref)).state == "active"

        cancel_claim = await store.claim_cancel(
            app_id="b62", continuation_ref=ref, reason="user_cancelled"
        )
        cancelled = await store.commit_cancel(
            app_id="b62",
            continuation_ref=ref,
            claim_token=cancel_claim.claim_token,
        )
        assert cancelled.state == "cancelled"
        with pytest.raises(ServiceContractError) as raised:
            await store.resolve(app_id="b62", continuation_ref=ref)
        assert raised.value.code == "continuation_cancelled"

    asyncio.run(scenario())


def test_active_worker_wires_explicit_durable_continuation_without_production_binding_mutation():
    root = Path(__file__).resolve().parents[1]
    worker_source = (root / "worker_identity.py").read_text(encoding="utf-8")
    adapter_source = (root / "app" / "continuation_d1.py").read_text(encoding="utf-8")
    wrangler_source = (root / "wrangler.toml").read_text(encoding="utf-8")

    assert 'ENGINE_CONTINUATION_BINDING_NAME = "ENGINE_CONTINUATION"' in worker_source
    assert "CloudflareD1IdentityBoundContinuationStore" in worker_source
    assert "AuthenticatedFirstPartyApprovalDecisionVerifier" in worker_source
    assert "continuation_store=continuation_store" in worker_source
    assert "approval_decision_verifier=" in worker_source
    assert "InMemory" not in worker_source
    assert "CREATE TABLE" not in adapter_source.upper()
    assert "ENGINE_CONTINUATION" not in wrangler_source
