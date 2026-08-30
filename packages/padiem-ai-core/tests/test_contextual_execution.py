from __future__ import annotations

import pytest

from padiem_ai_core.contextual_execution import prepare_execution
from padiem_ai_core.execution_context import ExecutionContext


def test_prepare_execution_is_deterministic_and_excludes_auth_material() -> None:
    context = ExecutionContext(trace_id="trace-123", idempotency_key="idem-123", timeout_seconds=10)
    payload_a = {
        "app_id": "b62",
        "agent": {"id": "agent-1", "model": "b14/auto"},
        "messages": [{"role": "user", "content": "hello"}],
        "authorization": "secret-a",
        "execution_context": {"trace_id": "ignored"},
    }
    payload_b = {
        "messages": [{"content": "hello", "role": "user"}],
        "agent": {"model": "b14/auto", "id": "agent-1"},
        "app_id": "b62",
        "authorization": "secret-b",
        "execution_context": {"idempotency_key": "other"},
    }

    prepared_a = prepare_execution(context=context, app_id="b62", payload=payload_a)
    prepared_b = prepare_execution(context=context, app_id="b62", payload=payload_b)

    assert prepared_a.request_fingerprint == prepared_b.request_fingerprint
    assert prepared_a.context == context
    assert prepared_a.to_public_dict()["idempotency_present"] is True


def test_prepare_execution_rejects_invalid_context_or_payload() -> None:
    with pytest.raises(ValueError, match="context"):
        prepare_execution(context=object(), app_id="b62", payload={})
    with pytest.raises(ValueError, match="payload"):
        prepare_execution(
            context=ExecutionContext(trace_id="trace-123"),
            app_id="b62",
            payload=[],
        )
