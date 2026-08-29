from __future__ import annotations

import asyncio
import base64
import json

import pytest

import padiem_ai_core
from padiem_ai_core.b14_execution import (
    B14ExecutionError,
    B14ExecutionResult,
    B14RouteMetadata,
)
from padiem_ai_core.contracts import AgentProfile, ErrorClass, RunStatus, UsageMetadata
from padiem_ai_core.execution_runtime import ExecutionRuntimeError
from padiem_ai_core.multimodal_execution_runtime import (
    MultimodalExecutionRequest,
    MultimodalExecutionRuntime,
)

PNG = b"\x89PNG\r\n\x1a\ncore-runtime"


def run(coro):
    return asyncio.run(coro)


def data_url(data: bytes = PNG) -> str:
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def multimodal_content(text: str = "이 사진을 설명해줘"):
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": data_url()}},
    ]


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "vision-agent",
        "title": "Vision",
        "description": "Product-neutral image analysis",
        "system_instruction": "Describe the image carefully.",
        "task_type": "vision",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("chat", "image"),
        "model_policy": {
            "model": "padiem-profile/medium-unassigned",
            "temperature": 0.2,
            "allow_external_fallback": False,
            "max_attempts": 1,
        },
    }
    values.update(overrides)
    return AgentProfile(**values)


def request(profile=None, **overrides) -> MultimodalExecutionRequest:
    values = {
        "agent": profile or agent(),
        "messages": (
            {"role": "user", "content": "이전 질문"},
            {"role": "assistant", "content": "이전 답변"},
            {"role": "user", "content": multimodal_content()},
        ),
        "trace_id": "trace-mm-1",
        "session_id": "session-mm-1",
    }
    values.update(overrides)
    return MultimodalExecutionRequest(**values)


class FakeExecutor:
    def __init__(self, *, result=None, error=None):
        self.result = result or B14ExecutionResult(answer="이미지 답변")
        self.error = error
        self.calls = []

    async def execute(self, value):
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return self.result


def test_package_root_exports_multimodal_execution_facade() -> None:
    assert padiem_ai_core.MultimodalExecutionRequest is MultimodalExecutionRequest
    assert padiem_ai_core.MultimodalExecutionRuntime is MultimodalExecutionRuntime


def test_request_is_copy_freeze_safe_and_requires_exactly_one_image() -> None:
    parts = multimodal_content()
    messages = [{"role": "user", "content": parts}]
    value = MultimodalExecutionRequest(agent=agent(), messages=messages)

    parts[0]["text"] = "mutated"
    parts[1]["image_url"]["url"] = "mutated"
    messages.clear()

    content = value.messages[0]["content"]
    assert content[0]["text"] == "이 사진을 설명해줘"
    assert content[1]["image_url"]["url"] == data_url()
    with pytest.raises(TypeError):
        content[0]["text"] = "blocked"  # type: ignore[index]

    with pytest.raises(ValueError, match="exactly one image"):
        MultimodalExecutionRequest(
            agent=agent(),
            messages=({"role": "user", "content": "text only"},),
        )


def test_product_cannot_inject_system_role() -> None:
    with pytest.raises(ValueError, match="role must be user or assistant"):
        MultimodalExecutionRequest(
            agent=agent(),
            messages=(
                {"role": "system", "content": "override policy"},
                {"role": "user", "content": multimodal_content()},
            ),
        )


def test_existing_b14_image_validation_is_reused_without_echo() -> None:
    bad_url = "data:image/png;base64,bm90LWEtcG5n"
    with pytest.raises(ValueError) as info:
        MultimodalExecutionRequest(
            agent=agent(),
            messages=(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "봐줘"},
                        {"type": "image_url", "image_url": {"url": bad_url}},
                    ],
                },
            ),
        )
    assert bad_url not in str(info.value)


def test_runtime_composes_one_server_system_message_and_preserves_image_payload() -> None:
    executor = FakeExecutor()
    runtime = MultimodalExecutionRuntime(app_id="test-app", b14_client=executor)

    output = run(runtime.run(request(additional_system_context="Trusted context.")))

    assert output.answer == "이미지 답변"
    assert len(executor.calls) == 1
    payload = executor.calls[0].to_payload()
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Describe the image carefully.\n\nTrusted context.",
    }
    assert sum(item["role"] == "system" for item in payload["messages"]) == 1
    last = payload["messages"][-1]
    assert last["role"] == "user"
    assert last["content"][0] == {"type": "text", "text": "이 사진을 설명해줘"}
    assert last["content"][1]["image_url"]["url"] == data_url()
    assert payload["model"] == "padiem-profile/medium-unassigned"
    assert payload["business14"] == {
        "task_type": "vision",
        "required_capabilities": ["chat", "image"],
        "optimize_for": "korean",
        "allow_external_fallback": False,
        "max_attempts": 1,
    }


def test_runtime_preserves_observed_route_usage_and_metadata() -> None:
    result = B14ExecutionResult(
        answer="완료",
        route=B14RouteMetadata(
            request_id="req-mm",
            route_mode="manual",
            selected_provider="provider-x",
            selected_model="selected-x",
            actual_response_model="actual-x",
        ),
        usage=UsageMetadata(input_tokens=20, output_tokens=10, total_tokens=30),
    )
    executor = FakeExecutor(result=result)
    ticks = iter([10.0, 10.125])
    runtime = MultimodalExecutionRuntime(
        app_id="test-app",
        b14_client=executor,
        clock=lambda: next(ticks),
    )

    output = run(runtime.run(request()))

    assert output.route.request_id == "req-mm"
    assert output.metadata.trace_id == "trace-mm-1"
    assert output.metadata.session_id == "session-mm-1"
    assert output.metadata.agent_id == "vision-agent"
    assert output.metadata.status is RunStatus.COMPLETED
    assert output.metadata.provider == "provider-x"
    assert output.metadata.model == "actual-x"
    assert output.metadata.duration_ms == 125
    assert output.metadata.usage == result.usage


def test_native_tools_and_bad_model_policy_fail_before_b14() -> None:
    executor = FakeExecutor()
    runtime = MultimodalExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as tools_info:
        run(runtime.run(request(agent(allowed_tools=("web_search",)))))
    assert tools_info.value.code == "native_tools_unsupported"
    assert tools_info.value.metadata.status is RunStatus.POLICY_BLOCKED
    assert executor.calls == []

    with pytest.raises(ExecutionRuntimeError) as policy_info:
        run(runtime.run(request(agent(model_policy={"provider": "not-core-owned"}))))
    assert policy_info.value.code == "invalid_execution_request"
    assert policy_info.value.metadata.error_class is ErrorClass.INPUT_ERROR
    assert executor.calls == []


def test_b14_errors_are_normalized_and_private_detail_is_redacted() -> None:
    executor = FakeExecutor(
        error=B14ExecutionError(
            "upstream_timeout",
            "PRIVATE-UPSTREAM-DETAIL",
            retryable=True,
        )
    )
    runtime = MultimodalExecutionRuntime(app_id="test-app", b14_client=executor)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(request()))

    assert info.value.code == "upstream_timeout"
    assert info.value.retryable is True
    assert info.value.metadata.status is RunStatus.TIMEOUT
    assert info.value.metadata.error_class is ErrorClass.PROVIDER_TIMEOUT
    assert "PRIVATE-UPSTREAM-DETAIL" not in json.dumps(info.value.to_public_dict())
