"""Wire adapter for the product-neutral Padiem execution context.

The internal Engine v1 surface remains backward compatible: callers may omit
``execution_context`` entirely. When present, the object is validated by the
shared Core contract and only non-authorizing execution metadata crosses the
service boundary.
"""

from __future__ import annotations

from typing import Any, Mapping

from padiem_ai_core import ExecutionContext


_ALLOWED_KEYS = frozenset({"trace_id", "idempotency_key", "timeout_seconds"})


def parse_execution_context(value: Any) -> ExecutionContext | None:
    """Parse an optional wire execution context into the shared Core contract."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("execution_context must be an object")

    data = dict(value)
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise ValueError("execution_context contains unsupported fields")

    trace_id = data.get("trace_id")
    if trace_id is None:
        raise ValueError("execution_context.trace_id is required")

    return ExecutionContext(
        trace_id=trace_id,
        idempotency_key=data.get("idempotency_key"),
        timeout_seconds=data.get("timeout_seconds", 20.0),
    )


def execution_context_to_wire(context: ExecutionContext | None) -> dict[str, Any] | None:
    """Return the bounded wire projection for an execution context."""
    if context is None:
        return None
    data: dict[str, Any] = {
        "trace_id": context.trace_id,
        "timeout_seconds": context.timeout_seconds,
    }
    if context.idempotency_key is not None:
        data["idempotency_key"] = context.idempotency_key
    return data


def merge_context_into_request(
    payload: Mapping[str, Any],
    context: ExecutionContext | None,
) -> dict[str, Any]:
    """Add a normalized context to a request without mutating the caller object."""
    result = dict(payload)
    if context is None:
        result.pop("execution_context", None)
    else:
        result["execution_context"] = execution_context_to_wire(context)
    return result
