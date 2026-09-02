"""Identity-bound approval continuation storage contract.

This module separates continuation lifecycle authority from wire handling. A
continuation record is not valid for resume unless it carries the canonical
execution identity that was present when the pause was issued.

Production implementations must persist the lifecycle state and execution
identity atomically in one durable authority. Admission-aware callers may also
persist bounded evidence of the trusted run admission that authorized the paused
execution. The in-memory implementation here is a network-free reference used to
prove semantics only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import secrets
from typing import Any, Protocol

from padiem_ai_core import ApprovalPause

from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission_resume import OriginalAdmissionBinding
from app.orchestration_service import ContinuationRecord
from app.service import ServiceContractError


@dataclass(frozen=True, slots=True)
class IdentityBoundContinuationRecord(ContinuationRecord):
    """Legacy-compatible continuation record plus canonical execution identity.

    Subclassing ``ContinuationRecord`` is intentional: the shared cancellation
    route may inspect only the generic lifecycle fields, while resume additionally
    requires ``execution_identity``. ``original_admission`` is optional for
    backward compatibility until the admission-aware Worker composition is
    activated; once present it is trusted server evidence, never browser input.
    """

    execution_identity: ContinuationExecutionIdentity | None = None
    original_admission: OriginalAdmissionBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution_identity, ContinuationExecutionIdentity):
            raise ValueError("execution_identity must be ContinuationExecutionIdentity")
        if self.original_admission is not None and not isinstance(
            self.original_admission, OriginalAdmissionBinding
        ):
            raise ValueError("original_admission must be OriginalAdmissionBinding or None")


class IdentityBoundContinuationStore(Protocol):
    """Durable CAS/transaction contract for identity-bound continuations."""

    def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        execution_identity: ContinuationExecutionIdentity,
        original_admission: OriginalAdmissionBinding | None = None,
    ) -> str: ...

    def resolve(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord: ...

    def claim(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord: ...

    def commit(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None: ...

    def release(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None: ...

    def claim_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        reason: str,
    ) -> IdentityBoundContinuationRecord: ...

    def commit_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> IdentityBoundContinuationRecord: ...

    def release_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> IdentityBoundContinuationRecord: ...

    def cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord: ...


class InMemoryIdentityBoundContinuationStore:
    """Process-local reference; never a production continuation authority."""

    def __init__(self) -> None:
        self._records: dict[str, IdentityBoundContinuationRecord] = {}

    def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        execution_identity: ContinuationExecutionIdentity,
        original_admission: OriginalAdmissionBinding | None = None,
    ) -> str:
        if not isinstance(execution_identity, ContinuationExecutionIdentity):
            raise ServiceContractError(
                "invalid_continuation_identity",
                "Continuation execution identity is invalid.",
                status_code=500,
            )
        if original_admission is not None and not isinstance(
            original_admission, OriginalAdmissionBinding
        ):
            raise ServiceContractError(
                "invalid_continuation_admission",
                "Continuation original admission binding is invalid.",
                status_code=500,
            )
        ref = f"cont_{secrets.token_urlsafe(32)}"
        self._records[ref] = IdentityBoundContinuationRecord(
            app_id=app_id,
            pause=pause,
            continuation_ref=ref,
            plan_id=pause.plan_id,
            request_fingerprint=execution_identity.request_fingerprint,
            execution_identity=execution_identity,
            original_admission=original_admission,
        )
        return ref

    def _get(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError(
                "invalid_continuation",
                "Continuation reference is invalid.",
                status_code=409,
            )
        if record.state == "cancelled":
            raise ServiceContractError(
                "continuation_cancelled",
                "Continuation has been cancelled.",
                status_code=409,
            )
        if record.state == "consumed":
            raise ServiceContractError(
                "continuation_consumed",
                "Continuation has already been consumed.",
                status_code=409,
            )
        if record.state == "expired":
            raise ServiceContractError(
                "continuation_expired",
                "Continuation has expired.",
                status_code=409,
            )
        if record.state == "claimed":
            raise ServiceContractError(
                "continuation_claimed",
                "Continuation is already being resumed.",
                status_code=409,
            )
        if record.state == "cancelling":
            raise ServiceContractError(
                "continuation_cancel_in_progress",
                "Continuation is already being cancelled.",
                status_code=409,
            )
        if record.pause.expires_at <= datetime.now(timezone.utc):
            self._records[continuation_ref] = replace(
                record,
                state="expired",
                claim_token=None,
            )
            raise ServiceContractError(
                "continuation_expired",
                "Continuation has expired.",
                status_code=409,
            )
        return record

    def resolve(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord:
        if not isinstance(continuation_ref, str) or not continuation_ref.startswith("cont_"):
            raise ServiceContractError(
                "invalid_continuation",
                "Continuation reference is invalid.",
                status_code=409,
            )
        return self._get(app_id=app_id, continuation_ref=continuation_ref)

    def claim(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        claimed = replace(
            record,
            state="claimed",
            claim_token=f"claim_{secrets.token_urlsafe(24)}",
        )
        self._records[continuation_ref] = claimed
        return claimed

    def _claimed(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
        state: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError(
                "invalid_continuation",
                "Continuation reference is invalid.",
                status_code=409,
            )
        if record.state == "consumed":
            raise ServiceContractError(
                "continuation_consumed",
                "Continuation has already been consumed.",
                status_code=409,
            )
        if record.state != state or record.claim_token != claim_token:
            code = "continuation_cancel_claim_failed" if state == "cancelling" else "continuation_claim_failed"
            raise ServiceContractError(
                code,
                "Continuation claim is no longer valid.",
                status_code=409,
            )
        return record

    def commit(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None:
        record = self._claimed(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
            state="claimed",
        )
        self._records[continuation_ref] = replace(
            record,
            state="consumed",
            claim_token=None,
        )

    def release(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> None:
        record = self._claimed(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
            state="claimed",
        )
        state = "expired" if record.pause.expires_at <= datetime.now(timezone.utc) else "active"
        self._records[continuation_ref] = replace(
            record,
            state=state,
            claim_token=None,
        )

    def claim_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        reason: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        claimed = replace(
            record,
            state="cancelling",
            claim_token=f"cancel_{secrets.token_urlsafe(24)}",
            cancel_reason=reason,
        )
        self._records[continuation_ref] = claimed
        return claimed

    def commit_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._claimed(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
            state="cancelling",
        )
        cancelled = replace(record, state="cancelled", claim_token=None)
        self._records[continuation_ref] = cancelled
        return cancelled

    def release_cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
        claim_token: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._claimed(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claim_token,
            state="cancelling",
        )
        state = "expired" if record.pause.expires_at <= datetime.now(timezone.utc) else "active"
        released = replace(
            record,
            state=state,
            claim_token=None,
            cancel_reason=None,
            cancel_event_fingerprint=None,
        )
        self._records[continuation_ref] = released
        return released

    def cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord:
        claimed = self.claim_cancel(
            app_id=app_id,
            continuation_ref=continuation_ref,
            reason="user_cancelled",
        )
        assert claimed.claim_token is not None
        return self.commit_cancel(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claimed.claim_token,
        )


def assert_continuation_identity(
    record: IdentityBoundContinuationRecord,
    candidate: ContinuationExecutionIdentity,
) -> None:
    """Fail closed before claim when resume semantics differ from the pause."""
    if not isinstance(record, IdentityBoundContinuationRecord):
        raise ServiceContractError(
            "continuation_store_unavailable",
            "Approval continuation storage returned an invalid record.",
            status_code=503,
        )
    if not isinstance(candidate, ContinuationExecutionIdentity):
        raise ServiceContractError(
            "continuation_identity_mismatch",
            "Resume execution identity does not match the server-issued continuation.",
            status_code=409,
        )
    if record.execution_identity != candidate:
        raise ServiceContractError(
            "continuation_identity_mismatch",
            "Resume execution identity does not match the server-issued continuation.",
            status_code=409,
        )
