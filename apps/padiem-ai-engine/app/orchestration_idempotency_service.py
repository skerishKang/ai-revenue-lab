"""Identity-bound Engine service with canonical idempotency fingerprinting.

The canonical Worker consumes this service so durable replay identity covers the
same execution-relevant fields already protected by approval continuation
identity. Product callers still provide only ordinary Engine requests; they do
not control the resulting durable fingerprint.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from padiem_ai_core import ExecutionContext

from app.continuation_binding import IdentityBoundContinuationRecord
from app.continuation_identity import build_continuation_execution_identity
from app.idempotency_identity import (
    reset_canonical_idempotency_fingerprint,
    set_canonical_idempotency_fingerprint,
    wrap_idempotency_adapter,
)
from app.orchestration_identity_service import IdentityBoundOrchestrationEngineService
from app.orchestration_service import (
    _parse_agent_plan,
    _parse_continuation_ref,
    _parse_recovery_policy,
)
from app.service import build_execution_request


def _initial_execution_fingerprint(payload: Any) -> str | None:
    """Derive the canonical pre-execution identity for a valid wire request.

    Invalid requests are deliberately left to the existing service contract
    parser; returning ``None`` here must never turn validation failures into
    successful execution.
    """
    if not isinstance(payload, Mapping):
        return None
    app_id = payload.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        return None
    try:
        _, exec_req, ctx = build_execution_request(
            {
                key: payload[key]
                for key in (
                    "app_id",
                    "agent",
                    "messages",
                    "session_id",
                    "additional_system_context",
                    "trace_id",
                    "execution_context",
                )
                if key in payload
            }
        )
        if ctx is None:
            ctx = ExecutionContext(trace_id=exec_req.trace_id or "orch_trace")
        identity = build_continuation_execution_identity(
            app_id=app_id,
            request=exec_req,
            context=ctx,
            subject_id=payload.get("subject_id"),
            plan=_parse_agent_plan(payload.get("agent_plan")),
            recovery_policy=_parse_recovery_policy(payload.get("recovery_policy")),
            max_retries=int(payload.get("max_retries", 3)),
            require_evidence=bool(payload.get("require_evidence", False)),
            require_verification=bool(payload.get("require_verification", False)),
        )
    except Exception:
        return None
    return identity.fingerprint


class CanonicalIdempotencyOrchestrationEngineService(IdentityBoundOrchestrationEngineService):
    """Canonical identity service with durable replay bound to the same identity."""

    def __init__(self, *args: Any, idempotency_adapter: Any | None = None, **kwargs: Any) -> None:
        super().__init__(
            *args,
            idempotency_adapter=wrap_idempotency_adapter(idempotency_adapter),
            **kwargs,
        )

    async def orchestrate_payload(self, payload: Any):
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return await super().orchestrate_payload(payload)
        token = set_canonical_idempotency_fingerprint(fingerprint)
        try:
            return await super().orchestrate_payload(payload)
        finally:
            reset_canonical_idempotency_fingerprint(token)

    async def resume_payload(self, payload: Any):
        fingerprint: str | None = None
        if isinstance(payload, Mapping):
            app_id = payload.get("app_id")
            if isinstance(app_id, str) and app_id.strip() and self._continuation_store_is_explicit:
                try:
                    continuation_ref = _parse_continuation_ref(payload.get("continuation_ref"))
                    record = await self._continuation_call(
                        "resolve",
                        app_id=app_id,
                        continuation_ref=continuation_ref,
                    )
                    if isinstance(record, IdentityBoundContinuationRecord):
                        fingerprint = record.execution_identity.fingerprint
                except Exception:
                    fingerprint = None
        if fingerprint is None:
            return await super().resume_payload(payload)
        token = set_canonical_idempotency_fingerprint(fingerprint)
        try:
            return await super().resume_payload(payload)
        finally:
            reset_canonical_idempotency_fingerprint(token)
