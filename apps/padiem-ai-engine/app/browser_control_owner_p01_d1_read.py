"""#3782 read-only independently authenticated owner P01 -> Engine.

The owner-confirmation D1 MUST be owned by a DIFFERENT authenticated
first-party user-approval service than Engine's continuation/receipt D1.
This reader exposes NO insertion, approval endpoint, or decision issuer.
A same-binding Engine service-identity decision is NOT human consent.
This is source-only: no owner writer, Service Binding or production route.
"""
from __future__ import annotations

import inspect
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.agent_approval import ApprovalOutcome, VerifiedApprovalDecision

from app.browser_control_human_approval import (
    IndependentlyAuthenticatedBrowserControlP01,
)
from app.continuation_binding import IdentityBoundContinuationRecord

# Belongs only in a separately provisioned HUMAN-approval-owner D1, never
# Engine's continuation DB; the schema is documented outside migrations.
_OWNER_TABLE = "padiem_browser_control_owner_p01_decisions"
BROWSER_CONTROL_OWNER_P01_D1_READER_WIRED = False


class IndependentOwnerP01D1Reader:
    """Actual D1 read (not a typed stub), with exact original-run identity.

    The owner D1 writer must independently prove the logged-in human owner,
    record exactly one approved decision and be the sole owner of revocation.
    The Engine sees only a service-authenticated READ on a different binding.
    """

    def __init__(self, *, owner_p01_binding: Any, engine_continuation_binding: Any):
        if (
            owner_p01_binding is None
            or owner_p01_binding is engine_continuation_binding
            or not callable(getattr(owner_p01_binding, "prepare", None))
            or engine_continuation_binding is None
        ):
            raise ValueError("human P01 read requires independent owner D1 binding")
        self._owner = owner_p01_binding

    async def __call__(
        self,
        record: IdentityBoundContinuationRecord,
        decision: VerifiedApprovalDecision,
    ) -> IndependentlyAuthenticatedBrowserControlP01 | None:
        if (
            type(record) is not IdentityBoundContinuationRecord
            or type(decision) is not VerifiedApprovalDecision
            or decision.outcome is not ApprovalOutcome.APPROVED
        ):
            return None
        original = record.original_admission
        identity = record.execution_identity
        pause = record.pause
        if (
            original is None
            or identity is None
            or not identity.subject_id
            or original.subject_id != identity.subject_id
            or original.app_id != record.app_id
            or original.request_fingerprint != identity.request_fingerprint
            or pause.tool_id != "browser.control"
            or pause.approval_scope != ("browser.control",)
            or pause.pause_id != decision.pause_id
        ):
            return None
        now = datetime.now(timezone.utc)
        if (
            now >= pause.expires_at
            or decision.decided_at > now
            or decision.decided_at < pause.created_at
            or decision.decided_at > pause.expires_at
        ):
            return None
        # This is the ENTIRE read authority. Caller-supplied decision fields
        # never authorize a row unless the independent user-owned D1 ALSO
        # confirms the same human, original admission, pause and exact action.
        sql = (
            "SELECT app_id,continuation_ref,pause_id,owner_subject_id,run_id,"
            "invocation_sha256,original_request_fingerprint,"
            "original_admission_decision_id,decision_id,authority_ref,"
            "evidence_ref,decided_at,expires_at,revoked_at,outcome "
            f"FROM {_OWNER_TABLE} "
            "WHERE app_id=? AND continuation_ref=? AND pause_id=? "
            "AND owner_subject_id=? AND run_id=? AND invocation_sha256=? "
            "AND original_request_fingerprint=? AND original_admission_decision_id=? "
            "AND decision_id=? AND authority_ref=? AND evidence_ref=? "
            "AND decided_at=? AND outcome='approved' AND revoked_at IS NULL "
            "AND expires_at>? LIMIT 1"
        )
        params = (
            record.app_id, record.continuation_ref, pause.pause_id,
            identity.subject_id, pause.run_id, pause.invocation_sha256,
            original.request_fingerprint, original.decision_id,
            decision.decision_id, decision.authority_ref, decision.evidence_ref,
            decision.decided_at.isoformat(), now.isoformat(),
        )
        try:
            candidate = self._owner.prepare(sql).bind(*params).first()
            if inspect.isawaitable(candidate):
                candidate = await candidate
        except Exception:  # noqa: BLE001 - owner service errors must not become approval
            return None
        if not isinstance(candidate, Mapping):
            return None
        # Re-assert the entire projection returned by the separate owner.
        names = (
            "app_id", "continuation_ref", "pause_id", "owner_subject_id",
            "run_id", "invocation_sha256", "original_request_fingerprint",
            "original_admission_decision_id", "decision_id", "authority_ref",
            "evidence_ref", "decided_at",
        )
        if any(candidate.get(k) != v for k, v in zip(names, params[:-1], strict=True)):
            return None
        if candidate.get("outcome") != "approved" or candidate.get("revoked_at") is not None:
            return None
        try:
            expiration = datetime.fromisoformat(candidate["expires_at"])
            if expiration.tzinfo is None or expiration.utcoffset() is None:
                return None
            if expiration > pause.expires_at or expiration <= now:
                return None
            proof = IndependentlyAuthenticatedBrowserControlP01(
                app_id=record.app_id,
                continuation_ref=record.continuation_ref,
                user_subject_id=identity.subject_id,
                run_id=pause.run_id,
                invocation_sha256=pause.invocation_sha256,
                original_request_fingerprint=original.request_fingerprint,
                original_admission_decision_id=original.decision_id,
                decision=decision,
                user_approval_evidence_ref=decision.evidence_ref,
            )
            proof.assert_matches(record=record, decision=decision, now=now)
            return proof
        except (KeyError, TypeError, ValueError):
            return None
