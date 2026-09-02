"""Canonical logical-execution fingerprint binding for Engine idempotency.

Core remains the owner of idempotency lifecycle semantics. This module replaces
the legacy partial orchestration fingerprint with a material-execution identity
that follows the accepted continuation field classification while deliberately
excluding observability/replay identifiers such as ``trace_id`` and the
``idempotency_key`` itself.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
import inspect
from typing import Any

from padiem_ai_core.execution_context import request_fingerprint

from app.continuation_identity import (
    _agent_identity,
    agent_plan_identity_fingerprint,
    recovery_policy_identity_fingerprint,
)


_CANONICAL_IDEMPOTENCY_FINGERPRINT: ContextVar[str | None] = ContextVar(
    "padiem_engine_canonical_idempotency_fingerprint",
    default=None,
)


def canonical_logical_execution_fingerprint(
    *,
    app_id: str,
    request: Any,
    context: Any,
    subject_id: str | None,
    plan: Any | None,
    recovery_policy: Any | None,
    max_retries: int,
    require_evidence: bool,
    require_verification: bool,
) -> str:
    """Fingerprint execution semantics, not transport/observability identity.

    ``trace_id`` is intentionally excluded because retries may legitimately use a
    fresh trace while remaining the same logical execution. ``idempotency_key``
    is also excluded because it selects the durable replay record; including the
    key in the record fingerprint would add no execution meaning.

    Material fields mirror the continuation identity classification: full agent
    semantics, messages, session/system context, bounded execution budget,
    subject, plan, recovery policy, retry budget, and evidence/verification
    requirements.
    """

    return request_fingerprint(
        {
            "app_id": app_id,
            "agent": _agent_identity(request),
            "messages": [dict(message) for message in request.messages],
            "session_id": request.session_id,
            "additional_system_context": request.additional_system_context,
            "timeout_seconds": context.timeout_seconds,
            "subject_id": subject_id,
            "plan_fingerprint": agent_plan_identity_fingerprint(plan),
            "recovery_policy_fingerprint": recovery_policy_identity_fingerprint(
                recovery_policy
            ),
            "max_retries": max_retries,
            "require_evidence": require_evidence,
            "require_verification": require_verification,
        }
    )


def _validate_fingerprint(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("canonical idempotency fingerprint must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("canonical idempotency fingerprint must be a sha256 hex digest") from exc
    return value.lower()


def set_canonical_idempotency_fingerprint(value: str) -> Token[str | None]:
    return _CANONICAL_IDEMPOTENCY_FINGERPRINT.set(_validate_fingerprint(value))


def reset_canonical_idempotency_fingerprint(token: Token[str | None]) -> None:
    _CANONICAL_IDEMPOTENCY_FINGERPRINT.reset(token)


def current_canonical_idempotency_fingerprint() -> str | None:
    return _CANONICAL_IDEMPOTENCY_FINGERPRINT.get()


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class CanonicalFingerprintIdempotencyAdapter:
    """Delegate Core idempotency lifecycle calls using one canonical fingerprint.

    Optional adapter extensions such as ``abort``/``release`` are deliberately
    forwarded through ``__getattr__`` unchanged. Only fingerprint-bearing
    reserve/complete operations are normalized.
    """

    def __init__(self, delegate: Any) -> None:
        if delegate is None or not callable(getattr(delegate, "begin", None)):
            raise ValueError("delegate must provide begin()")
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    @staticmethod
    def _effective_fingerprint(fallback: str) -> str:
        canonical = current_canonical_idempotency_fingerprint()
        return canonical if canonical is not None else fallback

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> Any:
        return await _maybe_await(
            self._delegate.begin(
                app_id=app_id,
                idempotency_key=idempotency_key,
                request_fingerprint=self._effective_fingerprint(request_fingerprint),
            )
        )

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: Any,
    ) -> None:
        method = getattr(self._delegate, "complete", None)
        if not callable(method):
            method = getattr(self._delegate, "commit", None)
        if not callable(method):
            raise RuntimeError("idempotency delegate does not provide complete/commit")
        await _maybe_await(
            method(
                app_id=app_id,
                idempotency_key=idempotency_key,
                request_fingerprint=self._effective_fingerprint(request_fingerprint),
                result=result,
            )
        )

    async def commit(self, **kwargs: Any) -> None:
        await self.complete(**kwargs)


def wrap_idempotency_adapter(delegate: Any | None) -> Any | None:
    if delegate is None:
        return None
    if isinstance(delegate, CanonicalFingerprintIdempotencyAdapter):
        return delegate
    return CanonicalFingerprintIdempotencyAdapter(delegate)
