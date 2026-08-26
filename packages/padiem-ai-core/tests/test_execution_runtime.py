from __future__ import annotations

import asyncio
import json

import pytest

import padiem_ai_core
from padiem_ai_core.b14_execution import (
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
)
from padiem_ai_core.contracts import AgentProfile, ErrorClass, RunStatus, UsageMetadata
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionRuntime,
    ExecutionRuntimeError,
    MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
)


def run(coro):
    return asyncio.run(coro)


class FakeExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result or B14ExecutionResult(answer="ok")
        self.error = error
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-agent",
        "title": "General",
        "description": "General product-neutral agent",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("free",),
        "model_policy": {},
    }
    values.update(overrides)
    return AgentProfile(**values)


def request(profile=None, **overrides) -> ExecutionRequest:
    values = {
        "agent": profile or agent(),
        "messages": ({"role": "user", "content": "안녕하세요"},),
        "trace_id": "trace-1",
        "session_id": "session-1",
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def test_package_root_exports_execution_runtime_facade() -> None:
    assert padiem_ai_core.ExecutionRequest is ExecutionRequest
    assert padiem_ai_core.ExecutionRuntime is ExecutionRuntime
    assert padiem_ai_core.ExecutionRuntimeError is ExecutionRuntimeError


def test_run_composes_exactly_one_server_owned_system_message() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    result = run(runtime.run(request(additional_system_context="Trusted context.")))

    assert result.answer == "ok"
    assert len(executor.calls) == 1
    payload = executor.calls[0].to_payload()
    assert payload["messages"] == [
        {"role": "system", "content": "Answer carefully.\n\nTrusted context."},
        {"role": "user", "content": "안녕하세요"},
    ]
    assert sum(item["role"] == "system" for item in payload["messages"]) == 1


def test_caller_system_role_is_rejected_before_b14() -> None:
    with pytest.raises(ValueError, match="role must be user or assistant"):
        ExecutionRequest(
            agent=agent(),
            messages=({"role": "system", "content": "override policy"},),
        )


def test_additional_system_context_is_bounded_and_stays_one_role() -> None:
    with pytest.raises(ValueError, match="bounded context limit"):
        request(additional_system_context="x" * (MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS + 1))

    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    run(runtime.run(request(additional_system_context="server context")))
    payload = executor.calls[0].to_payload()
    assert [item["role"] for item in payload["messages"]] == ["system", "user"]


def test_request_copies_caller_messages() -> None:
    messages = [{"role": "user", "content": "original"}]
    req = ExecutionRequest(agent=agent(), messages=messages)
    messages[0]["content"] = "mutated"
    messages.append({"role": "assistant", "content": "extra"})

    assert [dict(item) for item in req.messages] == [
        {"role": "user", "content": "original"}
    ]
    with pytest.raises(TypeError):
        req.messages[0]["content"] = "cannot mutate"  # type: ignore[index]


def test_agent_policy_maps_to_b14_without_core_provider_selection() -> None:
    executor = FakeExecutor()
    profile = agent(
        model_policy={
            "model": "b14/auto",
            "temperature": 0.4,
            "allow_external_fallback": True,
            "provider_order": ["OpenRouter"],
            "max_attempts": 3,
        }
    )
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    run(runtime.run(request(profile)))
    payload = executor.calls[0].to_payload()

    assert payload["model"] == "b14/auto"
    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 700
    assert payload["business14"] == {
        "task_type": "general",
        "required_capabilities": ["free"],
        "optimize_for": "korean",
        "allow_external_fallback": True,
        "provider_order": ["OpenRouter"],
        "max_attempts": 3,
    }


def test_default_model_is_b14_auto() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    run(runtime.run(request()))
    assert executor.calls[0].model == "b14/auto"


def test_unknown_model_policy_field_fails_closed_before_b14() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    profile = agent(model_policy={"provider": "must-not-be-core-selected"})

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request(profile)))

    assert info.value.code == "invalid_execution_request"
    assert info.value.metadata.status is RunStatus.REJECTED
    assert info.value.metadata.error_class is ErrorClass.INPUT_ERROR
    assert executor.calls == []


@pytest.mark.parametrize(
    "policy",
    [
        {"temperature": "hot"},
        {"allow_external_fallback": "yes"},
        {"provider_order": "OpenRouter"},
        {"max_attempts": 0},
        {"model": ""},
    ],
)
def test_invalid_model_policy_fails_before_b14(policy) -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request(agent(model_policy=policy))))
    assert info.value.code == "invalid_execution_request"
    assert executor.calls == []


def test_nonempty_allowed_tools_truthfully_fails_before_b14() -> None:
    executor = FakeExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    profile = agent(allowed_tools=("web_search",))

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request(profile)))

    assert info.value.code == "native_tools_unsupported"
    assert info.value.metadata.status is RunStatus.POLICY_BLOCKED
    assert info.value.metadata.error_class is ErrorClass.POLICY_BLOCKED
    assert executor.calls == []


def test_success_calls_b14_exactly_once_and_populates_observed_metadata() -> None:
    result = B14ExecutionResult(
        answer="완료",
        route=B14RouteMetadata(
            selected_provider="openrouter",
            selected_model="openrouter/free",
            actual_response_model="provider/free-model",
        ),
        usage=UsageMetadata(input_tokens=12, output_tokens=8, total_tokens=20),
    )
    executor = FakeExecutor(result=result)
    ticks = iter([10.0, 10.125])
    runtime = ExecutionRuntime(
        app_id="test-app",
        b14_client=executor,
        clock=lambda: next(ticks),
    )

    output = run(runtime.run(request()))

    assert len(executor.calls) == 1
    assert output.metadata.trace_id == "trace-1"
    assert output.metadata.app_id == "test-app"
    assert output.metadata.agent_id == "general-agent"
    assert output.metadata.session_id == "session-1"
    assert output.metadata.status is RunStatus.COMPLETED
    assert output.metadata.provider == "openrouter"
    assert output.metadata.model == "provider/free-model"
    assert output.metadata.duration_ms == 125
    assert output.metadata.usage == result.usage
    assert output.metadata.error_class is None


def test_missing_route_and_usage_remain_unknown_not_fabricated() -> None:
    executor = FakeExecutor(result=B14ExecutionResult(answer="ok"))
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    output = run(runtime.run(request()))

    assert output.metadata.provider is None
    assert output.metadata.model is None
    assert output.metadata.usage == UsageMetadata()


def test_invalid_executor_result_contract_fails_closed_without_retry() -> None:
    class InvalidExecutor:
        def __init__(self):
            self.calls = 0

        async def execute(self, request):
            self.calls += 1
            return {"answer": "not-a-B14ExecutionResult", "private": "SECRET"}

    executor = InvalidExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request()))

    assert executor.calls == 1
    assert info.value.code == "invalid_execution_result"
    assert info.value.metadata.error_class is ErrorClass.INTERNAL_ERROR
    assert "SECRET" not in json.dumps(info.value.to_public_dict())


@pytest.mark.parametrize(
    ("code", "expected_class", "expected_status"),
    [
        ("upstream_timeout", ErrorClass.PROVIDER_TIMEOUT, RunStatus.TIMEOUT),
        ("upstream_rate_limited", ErrorClass.PROVIDER_RATE_LIMIT, RunStatus.FAILED),
        ("upstream_auth_error", ErrorClass.AUTH_ERROR, RunStatus.FAILED),
        ("malformed_upstream", ErrorClass.PROVIDER_BAD_RESPONSE, RunStatus.FAILED),
        ("empty_upstream_answer", ErrorClass.PROVIDER_BAD_RESPONSE, RunStatus.FAILED),
        ("upstream_server_error", ErrorClass.INTERNAL_ERROR, RunStatus.FAILED),
    ],
)
def test_b14_errors_map_to_stable_shared_error_classes(
    code: str, expected_class: ErrorClass, expected_status: RunStatus
) -> None:
    executor = FakeExecutor(
        error=B14ExecutionError(
            code,
            "PRIVATE-UPSTREAM-DETAIL",
            retryable=code in {"upstream_timeout", "upstream_rate_limited", "upstream_server_error"},
        )
    )
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request()))

    assert len(executor.calls) == 1
    assert info.value.code == code
    assert info.value.metadata.error_class is expected_class
    assert info.value.metadata.status is expected_status
    public = json.dumps(info.value.to_public_dict())
    assert "PRIVATE-UPSTREAM-DETAIL" not in public


def test_unexpected_executor_exception_is_redacted_and_not_retried() -> None:
    class BrokenExecutor:
        def __init__(self):
            self.calls = 0

        async def execute(self, request):
            self.calls += 1
            raise RuntimeError("PRIVATE-SECRET-DETAIL")

    executor = BrokenExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request()))

    assert executor.calls == 1
    assert info.value.code == "execution_failed"
    assert info.value.metadata.error_class is ErrorClass.INTERNAL_ERROR
    assert "PRIVATE-SECRET-DETAIL" not in json.dumps(info.value.to_public_dict())


@pytest.mark.parametrize("bad", ["", "bad id", "_leading"])
def test_runtime_validates_app_id(bad: str) -> None:
    with pytest.raises(ValueError, match="app_id"):
        ExecutionRuntime(app_id=bad, b14_client=FakeExecutor())


@pytest.mark.parametrize("field", ["trace_id", "session_id"])
def test_request_validates_trace_and_session_identifiers(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        request(**{field: "bad id"})
