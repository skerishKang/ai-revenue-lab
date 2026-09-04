"""Continuation contract and reference store for the Engine orchestration service.

Extracted verbatim from ``app.orchestration_service`` as part of the #1792 R2B-1
structural decomposition. This module owns the continuation record shape, the
atomic continuation lifecycle protocol, and the process-local reference
implementation. Behavior, error taxonomy, and state names are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import Any, Protocol

from padiem_ai_core.agent_approval import ApprovalPause

from app.service import ServiceContractError


@dataclass(frozen=True, slots=True)
class ContinuationRecord:
    app_id: str
    pause: ApprovalPause
    continuation_ref: str
    plan_id: str | None
    idempotency_key: str | None = None
    request_fingerprint: str | None = None
    state: str = "active"
    claim_token: str | None = None
    cancel_reason: str | None = None
    cancel_event_fingerprint: str | None = None


class ContinuationStore(Protocol):
    """Atomic continuation lifecycle adapter.

    Durable implementations must make claim/commit/release/cancel CAS or
    transactionally atomic across Worker/process boundaries.
    """

    def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        plan_id: str | None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> str: ...
    def resolve(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord: ...
    def claim(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord: ...
    def commit(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None: ...
    def release(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None: ...
    def cancel(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord: ...

    def claim_cancel(
        self, *, app_id: str, continuation_ref: str, reason: str
    ) -> ContinuationRecord: ...
    def commit_cancel(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> ContinuationRecord: ...
    def release_cancel(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> ContinuationRecord: ...


class InMemoryContinuationStore:
    """Process-local reference implementation of the durable CAS contract.

    Production adapters must provide the same atomic transitions in durable
    storage; this implementation is intentionally not a production authority.
    """

    def __init__(self) -> None:
        self._records: dict[str, ContinuationRecord] = {}

    @staticmethod
    def _copy(record: ContinuationRecord, **changes: Any) -> ContinuationRecord:
        values = {
            "app_id": record.app_id,
            "pause": record.pause,
            "continuation_ref": record.continuation_ref,
            "plan_id": record.plan_id,
            "idempotency_key": record.idempotency_key,
            "request_fingerprint": record.request_fingerprint,
            "state": record.state,
            "claim_token": record.claim_token,
            "cancel_reason": record.cancel_reason,
            "cancel_event_fingerprint": record.cancel_event_fingerprint,
        }
        values.update(changes)
        return ContinuationRecord(**values)

    def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        plan_id: str | None,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> str:
        ref = f"cont_{secrets.token_urlsafe(32)}"
        self._records[ref] = ContinuationRecord(
            app_id=app_id,
            pause=pause,
            continuation_ref=ref,
            plan_id=plan_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        return ref

    def _get(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        if record.state == "cancelled":
            raise ServiceContractError("continuation_cancelled", "Continuation has been cancelled.", status_code=409)
        if record.state == "consumed":
            raise ServiceContractError("continuation_consumed", "Continuation has already been consumed.", status_code=409)
        if record.state == "expired":
            raise ServiceContractError("continuation_expired", "Continuation has expired.", status_code=409)
        if record.state == "claimed":
            raise ServiceContractError("continuation_claimed", "Continuation is already being resumed.", status_code=409)
        if record.state == "cancelling":
            raise ServiceContractError(
                "continuation_cancel_in_progress", "Continuation is already being cancelled.", status_code=409
            )
        if record.pause.expires_at <= datetime.now(timezone.utc):
            self._records[continuation_ref] = self._copy(record, state="expired", claim_token=None)
            raise ServiceContractError("continuation_expired", "Continuation has expired.", status_code=409)
        return record

    def resolve(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        if not isinstance(continuation_ref, str) or not continuation_ref.startswith("cont_"):
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        return self._get(app_id=app_id, continuation_ref=continuation_ref)

    def claim(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        claimed = self._copy(record, state="claimed", claim_token=f"claim_{secrets.token_urlsafe(24)}")
        self._records[continuation_ref] = claimed
        return claimed

    def _claimed(self, *, app_id: str, continuation_ref: str, claim_token: str) -> ContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        if record.state == "consumed":
            raise ServiceContractError("continuation_consumed", "Continuation has already been consumed.", status_code=409)
        if record.state != "claimed" or record.claim_token != claim_token:
            raise ServiceContractError("continuation_claim_failed", "Continuation claim is no longer valid.", status_code=409)
        return record

    def commit(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None:
        record = self._claimed(app_id=app_id, continuation_ref=continuation_ref, claim_token=claim_token)
        self._records[continuation_ref] = self._copy(record, state="consumed", claim_token=None)

    def release(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None:
        record = self._claimed(app_id=app_id, continuation_ref=continuation_ref, claim_token=claim_token)
        state = "expired" if record.pause.expires_at <= datetime.now(timezone.utc) else "active"
        self._records[continuation_ref] = self._copy(record, state=state, claim_token=None)

    def _cancel_claimed(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> ContinuationRecord:
        record = self._records.get(continuation_ref)
        if record is None or record.app_id != app_id:
            raise ServiceContractError("invalid_continuation", "Continuation reference is invalid.", status_code=409)
        if record.state == "consumed":
            raise ServiceContractError("continuation_consumed", "Continuation has already been consumed.", status_code=409)
        if record.state != "cancelling" or record.claim_token != claim_token:
            raise ServiceContractError(
                "continuation_cancel_claim_failed", "Continuation cancel claim is no longer valid.", status_code=409
            )
        return record

    def claim_cancel(self, *, app_id: str, continuation_ref: str, reason: str) -> ContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        claimed = self._copy(
            record,
            state="cancelling",
            claim_token=f"cancel_{secrets.token_urlsafe(24)}",
            cancel_reason=reason,
            cancel_event_fingerprint=None,
        )
        self._records[continuation_ref] = claimed
        return claimed

    def commit_cancel(self, *, app_id: str, continuation_ref: str, claim_token: str) -> ContinuationRecord:
        record = self._cancel_claimed(app_id=app_id, continuation_ref=continuation_ref, claim_token=claim_token)
        committed = self._copy(
            record,
            state="cancelled",
            claim_token=None,
            cancel_event_fingerprint=f"evt_{secrets.token_hex(8)}",
        )
        self._records[continuation_ref] = committed
        return committed

    def release_cancel(self, *, app_id: str, continuation_ref: str, claim_token: str) -> ContinuationRecord:
        record = self._cancel_claimed(app_id=app_id, continuation_ref=continuation_ref, claim_token=claim_token)
        state = "expired" if record.pause.expires_at <= datetime.now(timezone.utc) else "active"
        released = self._copy(
            record, state=state, claim_token=None, cancel_reason=None, cancel_event_fingerprint=None
        )
        self._records[continuation_ref] = released
        return released

    def cancel(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        record = self._get(app_id=app_id, continuation_ref=continuation_ref)
        cancelled = self._copy(record, state="cancelled", claim_token=None)
        self._records[continuation_ref] = cancelled
        return cancelled
