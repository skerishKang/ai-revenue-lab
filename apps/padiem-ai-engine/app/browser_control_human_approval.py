"""#3782 independent human P01 evidence boundary, NOT an issuer.

An authenticated first-party *service* caller is not, by itself, a proof that
an actual user approved an exact browser command. A separate server-owned,
user-identity-authenticated P01 evidence resolver must produce this evidence,
bound to the original admitted Engine continuation, before a receipt is stored.

This contract is source-only, no resolver is composed in Production. Typed
objects by themselves are NOT an authentication or a bearer grant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision

from app.continuation_binding import IdentityBoundContinuationRecord

_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
BROWSER_CONTROL_HUMAN_P01_SOURCE_WIRED = False


@dataclass(frozen=True, slots=True)
class IndependentlyAuthenticatedBrowserControlP01:
    """Projection of current, independently user-authenticated P01 decision."""

    app_id: str
    continuation_ref: str
    user_subject_id: str
    run_id: str
    invocation_sha256: str
    original_request_fingerprint: str
    original_admission_decision_id: str
    decision: VerifiedApprovalDecision
    user_approval_evidence_ref: str

    def assert_matches(
        self, *,
        record: IdentityBoundContinuationRecord,
        decision: VerifiedApprovalDecision,
        now: datetime,
    ) -> None:
        if type(self) is not IndependentlyAuthenticatedBrowserControlP01:
            raise ValueError("canonical authenticated human P01 evidence required")
        if type(record) is not IdentityBoundContinuationRecord:
            raise ValueError("canonical identity-bound Engine continuation required")
        original = record.original_admission
        identity = record.execution_identity
        pause = record.pause
        if (
            original is None
            or type(self.decision) is not VerifiedApprovalDecision
            or type(decision) is not VerifiedApprovalDecision
            or self.decision != decision
            or decision.outcome is not ApprovalOutcome.APPROVED
            or pause.tool_id != "browser.control"
            or pause.approval_scope != ("browser.control",)
            or self.app_id != record.app_id
            or self.continuation_ref != record.continuation_ref
            or self.user_subject_id != original.subject_id
            or self.user_subject_id != identity.subject_id
            or self.run_id != pause.run_id
            or self.invocation_sha256 != pause.invocation_sha256
            or not isinstance(self.invocation_sha256, str)
            or _SHA.fullmatch(self.invocation_sha256) is None
            or self.original_request_fingerprint != original.request_fingerprint
            or self.original_request_fingerprint != identity.request_fingerprint
            or not isinstance(self.original_request_fingerprint, str)
            or _SHA.fullmatch(self.original_request_fingerprint) is None
            or self.original_admission_decision_id != original.decision_id
            or not isinstance(self.user_approval_evidence_ref, str)
            or _REF.fullmatch(self.user_approval_evidence_ref) is None
            or self.user_approval_evidence_ref != decision.evidence_ref
        ):
            raise ValueError("independent user P01 does not match admitted browser continuation")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("human P01 verification requires aware time")
        current = now.astimezone(timezone.utc)
        if (
            decision.decided_at > current
            or decision.decided_at < pause.created_at
            or current >= pause.expires_at
            or decision.decided_at > pause.expires_at
        ):
            raise ValueError("independent user P01 is stale or future-dated")
