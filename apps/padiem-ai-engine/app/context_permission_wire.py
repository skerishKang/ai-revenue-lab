"""Wire adapter for Core context permission projection through Engine execute.

This module is intentionally product-neutral. It converts a trusted first-party
server wire object into the accepted Core #1313 Context Permission + Knowledge
Boundary contract, without parsing product-specific locators, reading product
storage, or carrying private source bytes in diagnostics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from padiem_ai_core import ExecutionRequest
from padiem_ai_core.context_permission import (
    BoundaryDisposition,
    ContextCandidate,
    ContextEnvelope,
    ContextPermissionError,
    ContextPermissionProjection,
    KnowledgeBoundary,
    project_context_permission,
)

_ALLOWED_TOP = frozenset({"envelope", "boundary"})
_ALLOWED_ENVELOPE = frozenset({"request_id", "source_quality_gate_applied", "policy_hints", "candidates"})
_ALLOWED_CANDIDATE = frozenset({
    "id",
    "scope_id",
    "resource_ref",
    "provenance",
    "source_quality_selected",
    "user_asserted_permission",
})
_ALLOWED_BOUNDARY = frozenset({
    "allowed_scope_ids",
    "allowed_resource_refs",
    "denied_scope_ids",
    "denied_resource_refs",
    "boundary_available",
    "max_allowed_context",
    "policy_version",
})
_PRIVATE_BYTE_KEYS = frozenset({"text", "content", "body", "source_text", "private_context", "raw_context"})


class EngineContextPermissionWireError(ValueError):
    """Safe Engine-wire error for malformed or unsafe permission projection."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _object(value: Any, *, name: str, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EngineContextPermissionWireError("invalid_context_permission", f"{name} must be an object.")
    data = dict(value)
    unknown = set(data) - allowed
    if unknown:
        raise EngineContextPermissionWireError("invalid_context_permission", f"{name} contains unsupported fields.")
    if set(data) & _PRIVATE_BYTE_KEYS:
        raise EngineContextPermissionWireError("invalid_context_permission", f"{name} must not include private context bytes.")
    return data


def _sequence(value: Any, *, name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise EngineContextPermissionWireError("invalid_context_permission", f"{name} must be an array of strings.")
    return tuple(value)


def parse_context_permission_required(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise EngineContextPermissionWireError(
            "invalid_context_permission",
            "context_permission_required must be a boolean.",
        )
    return value


def _candidate(value: Any) -> ContextCandidate:
    data = _object(value, name="context_permission.envelope.candidate", allowed=_ALLOWED_CANDIDATE)
    if data.get("user_asserted_permission") is True:
        raise EngineContextPermissionWireError(
            "user_self_asserted_permission",
            "User-supplied context permission cannot be accepted as authority.",
            status_code=403,
        )
    try:
        return ContextCandidate(
            id=data["id"],
            scope_id=data["scope_id"],
            resource_ref=data["resource_ref"],
            evidence=None,
            provenance=_sequence(data.get("provenance"), name="candidate.provenance"),
            source_quality_selected=data.get("source_quality_selected", True),
            user_asserted_permission=False,
        )
    except KeyError as exc:
        raise EngineContextPermissionWireError(
            "invalid_context_permission",
            "context candidate is missing required fields.",
        ) from exc
    except ContextPermissionError as exc:
        raise EngineContextPermissionWireError("invalid_context_permission", str(exc)) from exc


def _envelope(value: Any, *, app_id: str, request_id: str) -> ContextEnvelope:
    data = _object(value, name="context_permission.envelope", allowed=_ALLOWED_ENVELOPE)
    candidates_raw = data.get("candidates")
    if isinstance(candidates_raw, (str, bytes)) or not isinstance(candidates_raw, Sequence):
        raise EngineContextPermissionWireError(
            "invalid_context_permission",
            "context_permission.envelope.candidates must be an array.",
        )
    try:
        return ContextEnvelope(
            app_id=app_id,
            request_id=data.get("request_id") or request_id,
            candidates=tuple(_candidate(item) for item in candidates_raw),
            source_quality_gate_applied=data.get("source_quality_gate_applied", True),
            policy_hints=_sequence(data.get("policy_hints"), name="context_permission.envelope.policy_hints"),
        )
    except ContextPermissionError as exc:
        raise EngineContextPermissionWireError("invalid_context_permission", str(exc)) from exc


def _boundary(value: Any) -> KnowledgeBoundary:
    data = _object(value, name="context_permission.boundary", allowed=_ALLOWED_BOUNDARY)
    if "allowed_scope_ids" not in data:
        raise EngineContextPermissionWireError(
            "boundary_unavailable",
            "Trusted context permission boundary is unavailable.",
            status_code=422,
        )
    try:
        return KnowledgeBoundary(
            allowed_scope_ids=_sequence(data.get("allowed_scope_ids"), name="boundary.allowed_scope_ids"),
            allowed_resource_refs=_sequence(data.get("allowed_resource_refs"), name="boundary.allowed_resource_refs"),
            denied_scope_ids=_sequence(data.get("denied_scope_ids"), name="boundary.denied_scope_ids"),
            denied_resource_refs=_sequence(data.get("denied_resource_refs"), name="boundary.denied_resource_refs"),
            boundary_available=data.get("boundary_available", True),
            require_trusted_boundary=True,
            max_allowed_context=data.get("max_allowed_context", 8),
            policy_version=data.get("policy_version", "context-permission:v1"),
        )
    except ContextPermissionError as exc:
        raise EngineContextPermissionWireError("invalid_context_permission", str(exc)) from exc


def parse_engine_context_permission(
    value: Any,
    *,
    app_id: str,
    request_id: str,
) -> ContextPermissionProjection | None:
    """Project trusted Engine wire data through the Core #1313 permission gate."""

    if value is None:
        return None
    data = _object(value, name="context_permission", allowed=_ALLOWED_TOP)
    if "envelope" not in data or "boundary" not in data:
        raise EngineContextPermissionWireError(
            "boundary_unavailable",
            "Trusted context permission boundary is unavailable.",
            status_code=422,
        )
    projection = project_context_permission(
        _envelope(data["envelope"], app_id=app_id, request_id=request_id),
        _boundary(data["boundary"]),
    )
    return projection


def request_with_allowed_context_refs(
    request: ExecutionRequest,
    projection: ContextPermissionProjection,
) -> ExecutionRequest:
    """Attach only allowed context references to model-visible request context."""

    if projection.disposition is not BoundaryDisposition.PERMITTED:
        raise EngineContextPermissionWireError(
            projection.disposition.value,
            "Context permission boundary rejected this request.",
            status_code=422,
        )
    allowed_refs = [item.resource_ref for item in projection.allowed_context]
    diagnostics = projection.diagnostics()
    block = "\n".join(
        [
            "[Padiem context permission]",
            f"boundary_disposition={diagnostics['boundary_disposition']}",
            f"policy_version={diagnostics['policy_version']}",
            "allowed_context_refs=" + ",".join(allowed_refs),
        ]
    )
    additional = request.additional_system_context
    if additional:
        additional = f"{additional}\n\n{block}"
    else:
        additional = block
    return ExecutionRequest(
        agent=request.agent,
        messages=request.messages,
        session_id=request.session_id,
        additional_system_context=additional,
        trace_id=request.trace_id,
    )
