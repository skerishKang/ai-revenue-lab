"""Identity-bound approval continuation storage contract.

This module separates continuation lifecycle authority from wire handling. A
continuation record is not valid for resume unless it carries the canonical
execution identity that was present when the pause was issued.

Production implementations must persist the lifecycle state and execution
identity atomically in one durable authority. The in-memory implementation here
is a network-free reference used to prove semantics only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import secrets
from typing import Protocol

from padiem_ai_core import ApprovalPause

from app.continuation_identity import ContinuationExecutionIdentity
from app.service import ServiceContractError


@dataclass(frozen=True, slots=True)
class IdentityBoundContinuationRecord:
    app_id: str
    pause: ApprovalPause
    continuation_ref: str
    execution_identity: ContinuationExecutionIdentity
    state: str = "active"
    claim_token: str | None = None


class IdentityBoundContinuationStore(Protocol):
    """Durable CAS/transaction contract for identity-bound continuations."""

    def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        execution_identity: ContinuationExecutionIdentity,
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
    ) -> str:
        if not isinstance(execution_identity, ContinuationExecutionIdentity):
            raise ServiceContractError(
                "invalid_continuation_identity",
                "Continuation execution identity is invalid.",
                status_code=500,
            )
        ref = f"cont_{secrets.token_urlsafe(32)}"
        self._records[ref] = IdentityBoundContinuationRecord(
            app_id=app_id,
            pause=pause,
            continuation_ref=ref,
            execution_identity=execution_identity,
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
        if record.state != "claimed" or record.claim_token != claim_token:
            raise ServiceContractError(
                "continuation_claim_failed",
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
        )
        state = "expired" if record.pause.expires_at <= datetime.now(timezone.utc) else "active"
        self._records[continuation_ref] = replace(
            record,
            state=state,
            claim_token=None,
        )

    def cancel(
        self,
        *,
        app_id: str,
        continuation_ref: str,
    ) -> IdentityBoundContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        cancelled = replace(record, state="cancelled", claim_token=None)
        self._records[continuation_ref] = cancelled
        return cancelled


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
