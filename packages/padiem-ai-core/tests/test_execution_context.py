import pytest

from padiem_ai_core.execution_context import (
    ExecutionContext,
    IdempotencyAdapter,
    request_fingerprint,
)


def test_execution_context_normalizes_bounded_metadata():
    context = ExecutionContext(
        trace_id="trace_123",
        idempotency_key="idem_123",
        timeout_seconds=12,
    )

    assert context.trace_id == "trace_123"
    assert context.idempotency_key == "idem_123"
    assert context.timeout_seconds == 12.0
    assert context.to_public_dict() == {
        "trace_id": "trace_123",
        "timeout_seconds": 12.0,
        "idempotency_present": True,
    }


def test_execution_context_rejects_unbounded_values():
    with pytest.raises(ValueError):
        ExecutionContext(trace_id="bad trace")
    with pytest.raises(ValueError):
        ExecutionContext(trace_id="trace", idempotency_key="bad key")
    with pytest.raises(ValueError):
        ExecutionContext(trace_id="trace", timeout_seconds=0.5)
    with pytest.raises(ValueError):
        ExecutionContext(trace_id="trace", timeout_seconds=61)


def test_fingerprint_is_deterministic_across_mapping_order():
    left = {"messages": [{"role": "user", "content": "hello"}], "model": "b14/auto"}
    right = {"model": "b14/auto", "messages": [{"content": "hello", "role": "user"}]}

    assert request_fingerprint(left) == request_fingerprint(right)


def test_fingerprint_changes_when_execution_request_changes():
    base = {"model": "b14/auto", "messages": [{"role": "user", "content": "hello"}]}
    changed = {"model": "b14/auto", "messages": [{"role": "user", "content": "goodbye"}]}

    assert request_fingerprint(base) != request_fingerprint(changed)


def test_fingerprint_rejects_non_json_like_values():
    with pytest.raises(TypeError):
        request_fingerprint({"opaque": object()})


def test_idempotency_adapter_is_a_runtime_protocol():
    assert hasattr(IdempotencyAdapter, "begin")
    assert hasattr(IdempotencyAdapter, "complete")
