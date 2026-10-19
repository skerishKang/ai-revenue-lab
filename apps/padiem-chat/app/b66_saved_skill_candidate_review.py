"""B66 #3186 — trusted operator review of a pending Saved Quote Skill candidate.

Authority boundary
------------------
This module exposes **no browser route**. The trusted host must project an active
operator grant (``TrustedB66ProvisioningGrant``) from server-side authority and a
server-resolved target account, exactly like the existing #3302 provisioning
contract. A customer request can never reach this code path, so a browser cannot
approve its own candidate, impersonate an operator, or set an owner id.

Approval outcome
----------------
On approval the candidate envelope is converted into an ``ApprovedSavedQuoteSkillArtifact``
and written through the **existing** #3301 store (``put_approved_skill``). No second
Saved Quote Skill store, renderer, or calculator is introduced. The server decides
``approvedBy`` / ``approvedAt`` / ``approvalRef``; the customer cannot supply them.

Integrity and version binding
-----------------------------
Before deciding, the stored candidate bytes are re-read and their digest is
recomputed. A candidate whose stored content changed since submission is refused,
so a decision can never activate content other than what was reviewed. Only a
``pending`` candidate may be decided, so a replayed or re-ordered decision cannot
create a second Skill row or revive a rejected candidate.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
    _aware,
)
from .b66_saved_quote_skill_store import (
    _EXPECTED_CALCULATION_AUTHORITY,
    _EXPECTED_RENDERER_CONTRACT,
    ApprovedSavedQuoteSkillArtifact,
    SavedQuoteSkillStore,
    canonicalize_approved_artifact,
)
from .b66_saved_skill_candidate_store import (
    CANDIDATE_STATUS_PENDING,
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISIONS,
    MAX_REJECTION_REASON_CHARS,
    SavedQuoteSkillCandidateStore,
    SavedQuoteSkillCandidateStoreError,
    candidate_content_digest,
    validate_candidate_row_id,
)

_APPROVER_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_FIRST_SKILL_VERSION = 1


class B66CandidateReviewError(RuntimeError):
    pass


class B66CandidateReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class B66CandidateReviewReceipt:
    receipt_ref: str
    action: B66CandidateReviewAction
    grant_ref: str
    operator_subject_id: str
    target_tenant_id: str
    target_workspace_id: str
    target_user_id: str
    candidate_id: str
    skill_fingerprint: str
    saved_skill_id: str
    skill_version: int | None
    occurred_at: datetime

    def safe_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "action": self.action.value,
            "grant_ref": self.grant_ref,
            "operator_subject_id": self.operator_subject_id,
            "target_tenant_id": self.target_tenant_id,
            "target_workspace_id": self.target_workspace_id,
            "target_user_id": self.target_user_id,
            "candidate_id": self.candidate_id,
            "skill_fingerprint": self.skill_fingerprint,
            "saved_skill_id": self.saved_skill_id,
            "skill_version": self.skill_version,
            "occurred_at": self.occurred_at.isoformat(),
        }


def _receipt_ref() -> str:
    return "b66crev_" + uuid.uuid4().hex


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _approver_ref(value: str, *, label: str) -> str:
    """The approval envelope is bounded by the canonical Skill contract.

    An operator identity that cannot be expressed as a bounded approval
    reference is refused rather than truncated or rewritten, because a rewritten
    approver would be a different (and unaudited) claim.
    """

    if not isinstance(value, str) or not _APPROVER_REF_RE.fullmatch(value.strip()):
        raise B66CandidateReviewError(f"{label} is not a bounded approval reference")
    return value.strip()


def _clean_rejection_reason(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise B66CandidateReviewError("rejection_reason is invalid")
    text = " ".join(value.split())
    if len(text) > MAX_REJECTION_REASON_CHARS:
        raise B66CandidateReviewError("rejection_reason is invalid")
    return text


def _approved_envelope(
    *,
    envelope: dict[str, Any],
    operator_subject_id: str,
    approved_at: str,
    approval_ref: str,
) -> dict[str, Any]:
    """Build the approved Skill envelope from the reviewed candidate.

    Only server-decided approval evidence is added, and the candidate-only
    fields are dropped so the result satisfies the canonical Skill key set owned
    by ``quote-skill.js``. Renderer and calculation authorities are the existing
    server-side expectations, never new values chosen here.
    """

    payload = json.loads(envelope["candidate_json"]) if isinstance(envelope["candidate_json"], str) else None
    if not isinstance(payload, dict):
        raise B66CandidateReviewError("candidate envelope is invalid")
    if payload.get("skillFingerprint") != envelope["skill_fingerprint"]:
        raise B66CandidateReviewError("candidate fingerprint changed")
    payload.pop("status", None)
    payload.pop("candidateId", None)
    # The candidate-only declared fingerprint is not part of the canonical Skill
    # key set; the approved envelope carries it as ``fingerprint`` + approval.
    payload.pop("skillFingerprint", None)
    payload["id"] = envelope["skill_id"]
    payload["name"] = envelope["skill_name"]
    payload["fingerprint"] = envelope["skill_fingerprint"]
    payload["rendererContract"] = _EXPECTED_RENDERER_CONTRACT
    payload["calculationAuthority"] = _EXPECTED_CALCULATION_AUTHORITY
    payload["approval"] = {
        "schemaVersion": 1,
        "status": "approved",
        "skillFingerprint": envelope["skill_fingerprint"],
        "approvedBy": operator_subject_id,
        "approvedAt": approved_at,
        "approvalRef": approval_ref,
    }
    payload.setdefault("createdAt", approved_at)
    payload["updatedAt"] = approved_at
    return payload


class B66SavedQuoteSkillCandidateReviewer:
    """Bounded trusted-host review over the #3186 candidate store."""

    def __init__(
        self,
        candidate_store: SavedQuoteSkillCandidateStore,
        saved_skill_store: SavedQuoteSkillStore,
    ):
        if candidate_store is None:
            raise ValueError("candidate store is required")
        if saved_skill_store is None:
            raise ValueError("Saved Quote Skill store is required")
        self._candidates = candidate_store
        self._skills = saved_skill_store

    @staticmethod
    def _authorize(
        *,
        grant: TrustedB66ProvisioningGrant,
        now: datetime,
    ) -> datetime:
        if not isinstance(grant, TrustedB66ProvisioningGrant):
            raise B66CandidateReviewError("trusted operator grant is required")
        checked = _aware("now", now)
        if not grant.is_active(now=checked) or not grant.allows(
            B66ProvisioningAction.REVIEW_CANDIDATE
        ):
            raise B66CandidateReviewError("operator is not authorized")
        return checked

    async def review(
        self,
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        candidate_id: str,
        action: str,
        now: datetime,
        rejection_reason: str | None = None,
    ) -> B66CandidateReviewReceipt:
        checked = self._authorize(grant=grant, now=now)
        if not isinstance(target, ResolvedB66ProvisioningTarget):
            raise B66CandidateReviewError("server-resolved target is required")
        if action not in DECISIONS:
            raise B66CandidateReviewError("review action is invalid")
        try:
            row_id = validate_candidate_row_id(candidate_id)
        except SavedQuoteSkillCandidateStoreError as exc:
            raise B66CandidateReviewError("candidate id is invalid") from exc

        operator_id = _approver_ref(grant.operator_subject.subject_id, label="operator subject")
        grant_ref = _approver_ref(grant.grant_ref, label="grant reference")

        # Ownership is enforced by the store: a target that does not own the
        # candidate simply resolves to nothing, so cross-account review is a 404.
        try:
            envelope = await self._candidates.read_candidate_envelope(
                user_id=target.user_id,
                workspace_id=target.workspace_id,
                candidate_id=row_id,
            )
        except SavedQuoteSkillCandidateStoreError as exc:
            raise B66CandidateReviewError("candidate id is invalid") from exc
        if envelope is None:
            raise B66CandidateReviewError("candidate_not_found")
        if envelope["status"] != CANDIDATE_STATUS_PENDING:
            # Already decided (or withdrawn): never re-activate, never overwrite.
            raise B66CandidateReviewError("candidate_not_pending")

        stored_json = envelope["candidate_json"]
        if not isinstance(stored_json, str):
            raise B66CandidateReviewError("candidate envelope is invalid")
        if candidate_content_digest(stored_json) != envelope["candidate_digest"]:
            # The stored bytes no longer match what was submitted and digested.
            raise B66CandidateReviewError("candidate_integrity_mismatch")

        fingerprint = envelope["skill_fingerprint"]
        if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
            raise B66CandidateReviewError("candidate fingerprint is invalid")

        decided_at = _stamp(checked)

        if action == DECISION_REJECT:
            recorded = await self._candidates.record_decision(
                user_id=target.user_id,
                workspace_id=target.workspace_id,
                candidate_id=row_id,
                decision=DECISION_REJECT,
                decided_by=operator_id,
                decision_ref=grant_ref,
                decided_at=decided_at,
                rejection_reason=_clean_rejection_reason(rejection_reason),
            )
            if not recorded or recorded.get("status") != "rejected":
                raise B66CandidateReviewError("candidate_decision_conflict")
            return B66CandidateReviewReceipt(
                receipt_ref=_receipt_ref(),
                action=B66CandidateReviewAction.REJECT,
                grant_ref=grant_ref,
                operator_subject_id=operator_id,
                target_tenant_id=target.tenant_id,
                target_workspace_id=target.workspace_id,
                target_user_id=target.user_id,
                candidate_id=row_id,
                skill_fingerprint=fingerprint,
                saved_skill_id="",
                skill_version=None,
                occurred_at=checked,
            )

        payload = _approved_envelope(
            envelope=envelope,
            operator_subject_id=operator_id,
            approved_at=decided_at,
            approval_ref=grant_ref,
        )
        try:
            artifact: ApprovedSavedQuoteSkillArtifact = canonicalize_approved_artifact(
                skill_id=envelope["skill_id"],
                skill_name=envelope["skill_name"],
                fingerprint=fingerprint,
                version=_FIRST_SKILL_VERSION,
                serialized_json=json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:
            raise B66CandidateReviewError("approved artifact is invalid") from exc

        stored = await self._skills.put_approved_skill(
            user_id=target.user_id,
            workspace_id=target.workspace_id,
            artifact=artifact,
        )
        saved_skill_id = stored.get("saved_skill_id") if isinstance(stored, dict) else None
        if not isinstance(saved_skill_id, str) or not saved_skill_id:
            raise B66CandidateReviewError("durable assignment did not return a saved skill id")

        recorded = await self._candidates.record_decision(
            user_id=target.user_id,
            workspace_id=target.workspace_id,
            candidate_id=row_id,
            decision=DECISION_APPROVE,
            decided_by=operator_id,
            decision_ref=grant_ref,
            decided_at=decided_at,
            saved_skill_id=saved_skill_id,
            skill_version=_FIRST_SKILL_VERSION,
        )
        if (
            not recorded
            or recorded.get("status") != "approved"
            or recorded.get("saved_skill_id") != saved_skill_id
        ):
            raise B66CandidateReviewError("candidate_decision_conflict")

        return B66CandidateReviewReceipt(
            receipt_ref=_receipt_ref(),
            action=B66CandidateReviewAction.APPROVE,
            grant_ref=grant_ref,
            operator_subject_id=operator_id,
            target_tenant_id=target.tenant_id,
            target_workspace_id=target.workspace_id,
            target_user_id=target.user_id,
            candidate_id=row_id,
            skill_fingerprint=fingerprint,
            saved_skill_id=saved_skill_id,
            skill_version=_FIRST_SKILL_VERSION,
            occurred_at=checked,
        )


__all__ = [
    "B66CandidateReviewAction",
    "B66CandidateReviewError",
    "B66CandidateReviewReceipt",
    "B66SavedQuoteSkillCandidateReviewer",
]
