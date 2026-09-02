"""Trusted first-party approval-decision verification at the Engine boundary.

The Engine wire is already protected by service identity before orchestration
handlers run. This verifier therefore accepts only a decision submission that
has arrived through that authenticated first-party transport and converts it to
Core's VerifiedApprovalDecision contract. It does not authenticate browser
input, mint ToolAuthorizationContext, or widen Tool/Agent authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    VerifiedApprovalDecision,
)

from app.service import ServiceContractError


class AuthenticatedFirstPartyApprovalDecisionVerifier:
    """Convert authenticated first-party decision evidence into Core evidence.

    Instantiate this only in a Worker composition root whose non-health routes
    have already passed the Engine service-identity gate.
    """

    def verify(
        self,
        submission: Any,
        *,
        pause: ApprovalPause,
        app_id: str,
    ) -> VerifiedApprovalDecision:
        if not isinstance(pause, ApprovalPause):
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval pause is invalid.",
                status_code=409,
            )
        if not isinstance(app_id, str) or not app_id:
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval application identity is invalid.",
                status_code=409,
            )
        if getattr(submission, "pause_id", None) != pause.pause_id:
            raise ServiceContractError(
                "approval_decision_mismatch",
                "Approval decision does not match the paused continuation.",
                status_code=409,
            )
        decided_at = getattr(submission, "decided_at", None)
        if not isinstance(decided_at, datetime) or decided_at.tzinfo is None or decided_at.utcoffset() is None:
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval decision timestamp is invalid.",
                status_code=400,
            )
        now = datetime.now(timezone.utc)
        if decided_at > now:
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval decision cannot be from the future.",
                status_code=409,
            )
        if decided_at < pause.created_at or decided_at > pause.expires_at:
            raise ServiceContractError(
                "approval_decision_expired",
                "Approval decision is outside the continuation window.",
                status_code=409,
            )
        outcome_raw = getattr(submission, "outcome", None)
        try:
            outcome = ApprovalOutcome(outcome_raw)
        except (TypeError, ValueError):
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval decision outcome is invalid.",
                status_code=400,
            ) from None
        try:
            return VerifiedApprovalDecision(
                decision_id=getattr(submission, "decision_id"),
                pause_id=pause.pause_id,
                outcome=outcome,
                authority_ref=getattr(submission, "authority_ref"),
                evidence_ref=getattr(submission, "evidence_ref"),
                decided_at=decided_at,
            )
        except (TypeError, ValueError):
            raise ServiceContractError(
                "invalid_approval_decision",
                "Approval decision evidence is invalid.",
                status_code=400,
            ) from None
