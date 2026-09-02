"""Identity-bound Engine service with canonical idempotency fingerprinting.

The canonical Worker consumes this service so durable replay identity covers the
same material execution fields protected by approval continuation identity while
keeping observability identifiers outside replay equality.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from padiem_ai_core.execution_context import ExecutionContext

from app.idempotency_identity import (
    canonical_logical_execution_fingerprint,
    reset_canonical_idempotency_fingerprint,
    set_canonical_idempotency_fingerprint,
    wrap_idempotency_adapter,
)
from app.orchestration_identity_service import IdentityBoundOrchestrationEngineService
from app.orchestration_service import _parse_orchestration_options
from app.service import build_execution_request


def _initial_execution_fingerprint(payload: Any) -> str | None:
    """Derive material logical-execution identity for a valid wire request.

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
        (
            plan,
            recovery_policy,
            max_retries,
            subject_id,
            require_evidence,
            require_verification,
        ) = _parse_orchestration_options(payload)
        return canonical_logical_execution_fingerprint(
            app_id=app_id,
            request=exec_req,
            context=ctx,
            subject_id=subject_id,
            plan=plan,
            recovery_policy=recovery_policy,
            max_retries=max_retries,
            require_evidence=require_evidence,
            require_verification=require_verification,
        )
    except Exception:
        return None


class CanonicalIdempotencyOrchestrationEngineService(IdentityBoundOrchestrationEngineService):
    """Identity-bound service with durable replay keyed to material semantics."""

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
        # Resume still passes the parent service's exact continuation-identity
        # comparison before Core executes. The durable idempotency layer uses the
        # same material field classification but excludes trace/key metadata.
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return await super().resume_payload(payload)
        token = set_canonical_idempotency_fingerprint(fingerprint)
        try:
            return await super().resume_payload(payload)
        finally:
            reset_canonical_idempotency_fingerprint(token)
