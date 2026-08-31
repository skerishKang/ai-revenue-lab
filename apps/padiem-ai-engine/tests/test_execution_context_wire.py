from __future__ import annotations

import pytest

from app.execution_context_wire import (
    execution_context_to_wire,
    merge_context_into_request,
    parse_execution_context,
)
from padiem_ai_core import ExecutionContext


def test_parse_optional_context_and_round_trip_projection() -> None:
    context = parse_execution_context(
        {
            "trace_id": "trace-123",
            "idempotency_key": "idem-123",
            "timeout_seconds": 12,
        }
    )
    assert context == ExecutionContext(
        trace_id="trace-123",
        idempotency_key="idem-123",
        timeout_seconds=12,
    )
    assert execution_context_to_wire(context) == {
        "trace_id": "trace-123",
        "idempotency_key": "idem-123",
        "timeout_seconds": 12.0,
    }


def test_context_is_optional_for_backward_compatibility() -> None:
    assert parse_execution_context(None) is None
    assert execution_context_to_wire(None) is None
    assert merge_context_into_request({"app_id": "b62"}, None) == {"app_id": "b62"}


def test_unknown_context_fields_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        parse_execution_context(
            {
                "trace_id": "trace-123",
                "timeout_seconds": 10,
                "provider": "openai",
            }
        )


def test_missing_trace_id_fails_closed() -> None:
    with pytest.raises(ValueError, match="trace_id is required"):
        parse_execution_context({"timeout_seconds": 10})


def test_merge_does_not_mutate_payload() -> None:
    payload = {"app_id": "b62", "messages": []}
    context = ExecutionContext(trace_id="trace-123")
    merged = merge_context_into_request(payload, context)
    assert "execution_context" not in payload
    assert merged["execution_context"] == {
        "trace_id": "trace-123",
        "timeout_seconds": 20.0,
    }
