"""Durable D1 adapter for identity-bound Engine approval continuations.

Only bounded pause metadata, lifecycle state, canonical execution hashes, and
optional bounded evidence of the trusted original run admission are persisted.
Raw user messages, Tool arguments/results, model output, credentials, payment
records, and hidden reasoning are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import inspect
import json
import secrets
from typing import Any

from padiem_ai_core.agent_approval import ApprovalPause, ApprovalRequirement

from app.continuation_binding import IdentityBoundContinuationRecord
from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission_resume import OriginalAdmissionBinding
from app.service import ServiceContractError

_TABLE_NAME = "padiem_engine_continuations"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _pause_json(pause: ApprovalPause) -> str:
    payload = {
        "pause_id": pause.pause_id,
        "run_id": pause.run_id,
        "agent_runtime_id": pause.agent_runtime_id,
        "tool_id": pause.tool_id,
        "invocation_sha256": pause.invocation_sha256,
        "requirement": pause.requirement.value,
        "step_index": pause.step_index,
        "created_at": pause.created_at.isoformat(),
        "expires_at": pause.expires_at.isoformat(),
        "trace_id": pause.trace_id,
        "plan_id": pause.plan_id,
        "approval_scope": list(pause.approval_scope),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _pause_from_json(value: Any) -> ApprovalPause:
    data = json.loads(str(value))
    if not isinstance(data, Mapping):
        raise ValueError("pause record is invalid")
    scope = data.get("approval_scope")
    if not isinstance(scope, list):
        raise ValueError("approval scope is invalid")
    return ApprovalPause(
        pause_id=data["pause_id"],
        run_id=data["run_id"],
        agent_runtime_id=data["agent_runtime_id"],
        tool_id=data["tool_id"],
        invocation_sha256=data["invocation_sha256"],
        requirement=ApprovalRequirement(data["requirement"]),
        step_index=data["step_index"],
        created_at=_parse_time(data["created_at"]),
        expires_at=_parse_time(data["expires_at"]),
        trace_id=data.get("trace_id"),
        plan_id=data.get("plan_id"),
        approval_scope=tuple(scope),
    )


def _original_admission_payload(
    original_admission: OriginalAdmissionBinding,
) -> dict[str, str | None]:
    if not isinstance(original_admission, OriginalAdmissionBinding):
        raise ValueError("original admission binding is invalid")
    return {
        "decision_id": original_admission.decision_id,
        "app_id": original_admission.app_id,
        "subject_id": original_admission.subject_id,
        "authority_ref": original_admission.authority_ref,
        "policy_revision": original_admission.policy_revision,
        "request_fingerprint": original_admission.request_fingerprint,
    }


def _identity_json(
    identity: ContinuationExecutionIdentity,
    original_admission: OriginalAdmissionBinding | None = None,
) -> str:
    payload: dict[str, Any] = {
        "request_fingerprint": identity.request_fingerprint,
        "plan_fingerprint": identity.plan_fingerprint,
        "subject_id": identity.subject_id,
        "recovery_policy_fingerprint": identity.recovery_policy_fingerprint,
        "max_retries": identity.max_retries,
        "require_evidence": identity.require_evidence,
        "require_verification": identity.require_verification,
    }
    if original_admission is not None:
        payload["original_admission_binding"] = _original_admission_payload(original_admission)
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _identity_mapping(value: Any) -> Mapping[str, Any]:
    data = json.loads(str(value))
    if not isinstance(data, Mapping):
        raise ValueError("continuation identity is invalid")
    return data


def _identity_from_json(value: Any) -> ContinuationExecutionIdentity:
    data = _identity_mapping(value)
    return ContinuationExecutionIdentity(
        request_fingerprint=data["request_fingerprint"],
        plan_fingerprint=data.get("plan_fingerprint"),
        subject_id=data.get("subject_id"),
        recovery_policy_fingerprint=data.get("recovery_policy_fingerprint"),
        max_retries=data["max_retries"],
        require_evidence=data["require_evidence"],
        require_verification=data["require_verification"],
    )


def _required_bounded_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} is invalid")
    return value


def _original_admission_from_identity_json(value: Any) -> OriginalAdmissionBinding | None:
    data = _identity_mapping(value)
    raw = data.get("original_admission_binding")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("original admission binding is invalid")
    subject_id = raw.get("subject_id")
    if subject_id is not None and (
        not isinstance(subject_id, str) or not subject_id.strip() or len(subject_id) > 512
    ):
        raise ValueError("original admission subject_id is invalid")
    request_fingerprint = _required_bounded_text(raw, "request_fingerprint")
    if len(request_fingerprint) != 64:
        raise ValueError("original admission request_fingerprint is invalid")
    try:
        int(request_fingerprint, 16)
    except ValueError as exc:
        raise ValueError("original admission request_fingerprint is invalid") from exc
    return OriginalAdmissionBinding(
        decision_id=_required_bounded_text(raw, "decision_id"),
        app_id=_required_bounded_text(raw, "app_id"),
        subject_id=subject_id,
        authority_ref=_required_bounded_text(raw, "authority_ref"),
        policy_revision=_required_bounded_text(raw, "policy_revision"),
        request_fingerprint=request_fingerprint.lower(),
    )


class CloudflareD1IdentityBoundContinuationStore:
    """Durable atomic continuation authority backed by a trusted D1-like binding."""

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("continuation binding must provide prepare(sql)")
        self._binding = binding

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    @staticmethod
    def _columns() -> str:
        return (
            "app_id,continuation_ref,pause_json,execution_identity_json,state,claim_token,"
            "cancel_reason,cancel_event_fingerprint,created_at,updated_at,expires_at"
        )

    def _record(self, row: Mapping[str, Any]) -> IdentityBoundContinuationRecord:
        try:
            pause = _pause_from_json(row["pause_json"])
            identity_json = row["execution_identity_json"]
            identity = _identity_from_json(identity_json)
            original_admission = _original_admission_from_identity_json(identity_json)
            return IdentityBoundContinuationRecord(
                app_id=str(row["app_id"]),
                pause=pause,
                continuation_ref=str(row["continuation_ref"]),
                plan_id=pause.plan_id,
                request_fingerprint=identity.request_fingerprint,
                state=str(row["state"]),
                claim_token=str(row["claim_token"]) if row.get("claim_token") is not None else None,
                cancel_reason=str(row["cancel_reason"]) if row.get("cancel_reason") is not None else None,
                cancel_event_fingerprint=(
                    str(row["cancel_event_fingerprint"])
                    if row.get("cancel_event_fingerprint") is not None
                    else None
                ),
                execution_identity=identity,
                original_admission=original_admission,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ServiceContractError(
                "continuation_store_unavailable",
                "Approval continuation storage returned an invalid record.",
                status_code=503,
            ) from None

    async def _raw(self, *, app_id: str, continuation_ref: str) -> Mapping[str, Any] | None:
        return await self._first(
            f"SELECT {self._columns()} FROM {_TABLE_NAME} "
            "WHERE app_id=? AND continuation_ref=? LIMIT 1",
            app_id,
            continuation_ref,
        )

    async def _state_error(self, *, app_id: str, continuation_ref: str) -> None:
        row = await self._raw(app_id=app_id, continuation_ref=continuation_ref)
        if row is None:
            raise ServiceContractError(
                "invalid_continuation", "Continuation reference is invalid.", status_code=409
            )
        state = row.get("state")
        expires_at = _parse_time(row.get("expires_at"))
        if state == "active" and expires_at <= _now():
            await self._run(
                f"UPDATE {_TABLE_NAME} SET state='expired',claim_token=NULL,updated_at=? "
                "WHERE app_id=? AND continuation_ref=? AND state='active'",
                _now_iso(),
                app_id,
                continuation_ref,
            )
            state = "expired"
        mapping = {
            "claimed": ("continuation_claimed", "Continuation is already being resumed."),
            "cancelling": ("continuation_cancel_in_progress", "Continuation is already being cancelled."),
            "cancelled": ("continuation_cancelled", "Continuation has been cancelled."),
            "consumed": ("continuation_consumed", "Continuation has already been consumed."),
            "expired": ("continuation_expired", "Continuation has expired."),
        }
        code, message = mapping.get(
            state,
            ("continuation_claim_failed", "Continuation state changed before the operation could commit."),
        )
        raise ServiceContractError(code, message, status_code=409)

    async def issue(
        self,
        *,
        app_id: str,
        pause: ApprovalPause,
        execution_identity: ContinuationExecutionIdentity,
        original_admission: OriginalAdmissionBinding | None = None,
    ) -> str:
        if not isinstance(pause, ApprovalPause) or not isinstance(
            execution_identity, ContinuationExecutionIdentity
        ):
            raise ServiceContractError(
                "invalid_continuation", "Approval continuation input is invalid.", status_code=500
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
        now = _now_iso()
        try:
            await self._run(
                f"INSERT INTO {_TABLE_NAME} "
                "(app_id,continuation_ref,pause_json,execution_identity_json,state,claim_token,"
                "cancel_reason,cancel_event_fingerprint,created_at,updated_at,expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                app_id,
                ref,
                _pause_json(pause),
                _identity_json(execution_identity, original_admission),
                "active",
                None,
                None,
                None,
                now,
                now,
                pause.expires_at.isoformat(),
            )
        except Exception:
            raise ServiceContractError(
                "continuation_store_unavailable",
                "Approval continuation storage is unavailable.",
                status_code=503,
            ) from None
        return ref

    async def resolve(
        self, *, app_id: str, continuation_ref: str
    ) -> IdentityBoundContinuationRecord:
        if not isinstance(continuation_ref, str) or not continuation_ref.startswith("cont_"):
            raise ServiceContractError(
                "invalid_continuation", "Continuation reference is invalid.", status_code=409
            )
        row = await self._raw(app_id=app_id, continuation_ref=continuation_ref)
        if row is None:
            raise ServiceContractError(
                "invalid_continuation", "Continuation reference is invalid.", status_code=409
            )
        record = self._record(row)
        if record.state != "active" or record.pause.expires_at <= _now():
            await self._state_error(app_id=app_id, continuation_ref=continuation_ref)
        return record

    async def claim(
        self, *, app_id: str, continuation_ref: str
    ) -> IdentityBoundContinuationRecord:
        token = f"claim_{secrets.token_urlsafe(24)}"
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state='claimed',claim_token=?,updated_at=? "
            "WHERE app_id=? AND continuation_ref=? AND state='active' AND expires_at>? "
            f"RETURNING {self._columns()}",
            token,
            _now_iso(),
            app_id,
            continuation_ref,
            _now_iso(),
        )
        if row is None:
            await self._state_error(app_id=app_id, continuation_ref=continuation_ref)
        assert row is not None
        return self._record(row)

    async def commit(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> None:
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state='consumed',claim_token=NULL,updated_at=? "
            "WHERE app_id=? AND continuation_ref=? AND state='claimed' AND claim_token=? "
            f"RETURNING {self._columns()}",
            _now_iso(),
            app_id,
            continuation_ref,
            claim_token,
        )
        if row is None:
            raise ServiceContractError(
                "continuation_claim_failed", "Continuation claim is no longer valid.", status_code=409
            )

    async def release(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> None:
        now = _now_iso()
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state=CASE WHEN expires_at<=? THEN 'expired' ELSE 'active' END,"
            "claim_token=NULL,updated_at=? WHERE app_id=? AND continuation_ref=? "
            "AND state='claimed' AND claim_token=? "
            f"RETURNING {self._columns()}",
            now,
            now,
            app_id,
            continuation_ref,
            claim_token,
        )
        if row is None:
            raise ServiceContractError(
                "continuation_claim_failed", "Continuation claim is no longer valid.", status_code=409
            )

    async def claim_cancel(
        self, *, app_id: str, continuation_ref: str, reason: str
    ) -> IdentityBoundContinuationRecord:
        token = f"cancel_{secrets.token_urlsafe(24)}"
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state='cancelling',claim_token=?,cancel_reason=?,updated_at=? "
            "WHERE app_id=? AND continuation_ref=? AND state='active' AND expires_at>? "
            f"RETURNING {self._columns()}",
            token,
            reason,
            _now_iso(),
            app_id,
            continuation_ref,
            _now_iso(),
        )
        if row is None:
            await self._state_error(app_id=app_id, continuation_ref=continuation_ref)
        assert row is not None
        return self._record(row)

    async def commit_cancel(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> IdentityBoundContinuationRecord:
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state='cancelled',claim_token=NULL,updated_at=? "
            "WHERE app_id=? AND continuation_ref=? AND state='cancelling' AND claim_token=? "
            f"RETURNING {self._columns()}",
            _now_iso(),
            app_id,
            continuation_ref,
            claim_token,
        )
        if row is None:
            raise ServiceContractError(
                "continuation_cancel_claim_failed",
                "Continuation cancel claim is no longer valid.",
                status_code=409,
            )
        return self._record(row)

    async def release_cancel(
        self, *, app_id: str, continuation_ref: str, claim_token: str
    ) -> IdentityBoundContinuationRecord:
        now = _now_iso()
        row = await self._first(
            f"UPDATE {_TABLE_NAME} SET state=CASE WHEN expires_at<=? THEN 'expired' ELSE 'active' END,"
            "claim_token=NULL,cancel_reason=NULL,cancel_event_fingerprint=NULL,updated_at=? "
            "WHERE app_id=? AND continuation_ref=? AND state='cancelling' AND claim_token=? "
            f"RETURNING {self._columns()}",
            now,
            now,
            app_id,
            continuation_ref,
            claim_token,
        )
        if row is None:
            raise ServiceContractError(
                "continuation_cancel_claim_failed",
                "Continuation cancel claim is no longer valid.",
                status_code=409,
            )
        return self._record(row)

    async def cancel(
        self, *, app_id: str, continuation_ref: str
    ) -> IdentityBoundContinuationRecord:
        claimed = await self.claim_cancel(
            app_id=app_id, continuation_ref=continuation_ref, reason="user_cancelled"
        )
        if claimed.claim_token is None:
            raise ServiceContractError(
                "continuation_cancel_claim_failed",
                "Continuation cancel claim is invalid.",
                status_code=503,
            )
        return await self.commit_cancel(
            app_id=app_id,
            continuation_ref=continuation_ref,
            claim_token=claimed.claim_token,
        )
