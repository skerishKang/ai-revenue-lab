from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from padiem_ai_core import (
    B14RouteMetadata,
    ErrorClass,
    ExecutionResult,
    ExecutionRuntimeError,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)

from app.ai.base import AIProvider
from app.ai.mock import MockProvider
from app.ai.padiem_core import PadiemCoreProvider
from app.config import Settings
from app.factory import create_provider


class StructuredAnswer(BaseModel):
    title: str = Field(min_length=1)
    items: list[str]


class FakeRuntime:
    def __init__(self, *, result: ExecutionResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def execution_result(answer: str) -> ExecutionResult:
    route = B14RouteMetadata(
        selected_provider="openrouter",
        selected_model="openrouter/free",
        actual_response_model="provider/free-model",
    )
    metadata = RunMetadata(
        trace_id="trace-test",
        app_id="living-learning",
        agent_id="living-learning-structured",
        status=RunStatus.COMPLETED,
        provider="openrouter",
        model="provider/free-model",
        duration_ms=37,
        usage=UsageMetadata(input_tokens=11, output_tokens=7, total_tokens=18),
    )
    return ExecutionResult(answer=answer, route=route, metadata=metadata)


def runtime_error(
    *,
    code: str,
    error_class: ErrorClass,
    retryable: bool = False,
    safe_message: str = "safe",
) -> ExecutionRuntimeError:
    status = RunStatus.TIMEOUT if error_class is ErrorClass.PROVIDER_TIMEOUT else RunStatus.FAILED
    return ExecutionRuntimeError(
        code,
        safe_message,
        retryable=retryable,
        metadata=RunMetadata(
            trace_id="trace-error",
            app_id="living-learning",
            agent_id="living-learning-structured",
            status=status,
            error_class=error_class,
        ),
    )


def call(provider: PadiemCoreProvider):
    return provider.generate_structured(
        task_name="lesson_content",
        system_prompt="Create a concise Korean lesson.",
        user_payload={"topic": "Python", "level": "beginner"},
        response_schema=StructuredAnswer,
        request_id="attempt_group_0",
    )


def test_structured_success_uses_core_once_and_maps_observed_metadata() -> None:
    runtime = FakeRuntime(
        result=execution_result('{"title":"반복문","items":["for","while"]}')
    )
    provider = PadiemCoreProvider(runtime=runtime)

    result = call(provider)

    assert result.success is True
    assert result.payload == {"title": "반복문", "items": ["for", "while"]}
    assert result.provider == "openrouter"
    assert result.model == "provider/free-model"
    assert result.cost_class == "free"
    assert result.latency_ms == 37.0
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert len(runtime.requests) == 1


def test_request_policy_keeps_living_learning_as_retry_authority() -> None:
    runtime = FakeRuntime(
        result=execution_result('{"title":"함수","items":["def"]}')
    )
    provider = PadiemCoreProvider(runtime=runtime, model="b14/auto")

    call(provider)

    request = runtime.requests[0]
    agent = request.agent
    assert agent.task_type == "korean"
    assert agent.optimize_for == "korean"
    assert agent.required_capabilities == ("free",)
    assert agent.allowed_tools == ()
    assert agent.model_policy["model"] == "b14/auto"
    assert agent.model_policy["allow_external_fallback"] is False
    assert agent.model_policy["max_attempts"] == 1
    assert request.trace_id is None

    user_message = json.loads(request.messages[0]["content"])
    assert user_message == {
        "task_name": "lesson_content",
        "input": {"level": "beginner", "topic": "Python"},
    }
    assert "JSON Schema:" in request.additional_system_context
    assert "Markdown fences" in request.additional_system_context


def test_markdown_fenced_json_is_not_repaired() -> None:
    runtime = FakeRuntime(
        result=execution_result('```json\n{"title":"x","items":[]}\n```')
    )
    provider = PadiemCoreProvider(runtime=runtime)

    result = call(provider)

    assert result.success is False
    assert result.error_category == "schema_mismatch"
    assert result.error_message == "schema_mismatch"
    assert len(runtime.requests) == 1


def test_schema_validation_failure_is_schema_mismatch() -> None:
    runtime = FakeRuntime(result=execution_result('{"items":["missing-title"]}'))
    provider = PadiemCoreProvider(runtime=runtime)

    result = call(provider)

    assert result.success is False
    assert result.error_category == "schema_mismatch"
    assert result.provider == "openrouter"
    assert result.model == "provider/free-model"
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (
            runtime_error(
                code="upstream_timeout",
                error_class=ErrorClass.PROVIDER_TIMEOUT,
                retryable=True,
            ),
            "timeout",
        ),
        (
            runtime_error(
                code="upstream_rate_limited",
                error_class=ErrorClass.PROVIDER_RATE_LIMIT,
                retryable=True,
            ),
            "rate_limit",
        ),
        (
            runtime_error(
                code="upstream_auth_error",
                error_class=ErrorClass.AUTH_ERROR,
            ),
            "authentication_error",
        ),
        (
            runtime_error(
                code="upstream_request_error",
                error_class=ErrorClass.INPUT_ERROR,
            ),
            "invalid_request",
        ),
        (
            runtime_error(
                code="native_tools_unsupported",
                error_class=ErrorClass.POLICY_BLOCKED,
            ),
            "provider_refusal",
        ),
        (
            runtime_error(
                code="upstream_unavailable",
                error_class=ErrorClass.INTERNAL_ERROR,
                retryable=True,
            ),
            "transient_provider_error",
        ),
        (
            runtime_error(
                code="execution_failed",
                error_class=ErrorClass.INTERNAL_ERROR,
                retryable=False,
            ),
            "core_execution_error",
        ),
    ],
)
def test_core_errors_map_to_stable_product_categories(error, category) -> None:
    runtime = FakeRuntime(error=error)
    provider = PadiemCoreProvider(runtime=runtime)

    result = call(provider)

    assert result.success is False
    assert result.error_category == category
    assert result.error_message == category
    assert "safe" not in result.error_message
    assert len(runtime.requests) == 1


def test_unexpected_private_exception_is_redacted() -> None:
    runtime = FakeRuntime(error=RuntimeError("PRIVATE_PROVIDER_SECRET"))
    provider = PadiemCoreProvider(runtime=runtime)

    result = call(provider)

    assert result.success is False
    assert result.error_category == "core_execution_error"
    assert "PRIVATE_PROVIDER_SECRET" not in json.dumps(result.model_dump())


def test_invalid_product_input_fails_before_core_call() -> None:
    runtime = FakeRuntime(result=execution_result('{"title":"x","items":[]}'))
    provider = PadiemCoreProvider(runtime=runtime)

    result = provider.generate_structured(
        task_name="lesson_content",
        system_prompt=" ",
        user_payload={},
        response_schema=StructuredAnswer,
        request_id="anything",
    )

    assert result.success is False
    assert result.error_category == "invalid_request"
    assert runtime.requests == []


def test_mock_remains_default_provider() -> None:
    settings = Settings(database_url=":memory:")

    provider = create_provider(settings)

    assert isinstance(provider, MockProvider)
    assert isinstance(provider, AIProvider)
    assert provider.provider_type == "mock"


def test_core_factory_is_explicit_and_fails_closed_without_b14_base_url() -> None:
    settings = Settings(
        database_url=":memory:",
        provider_type="padiem_core",
        padiem_core_b14_base_url="",
    )

    with pytest.raises(ValueError, match="LL_PADIEM_CORE_B14_BASE_URL"):
        create_provider(settings)


def test_core_factory_constructs_without_making_network_call() -> None:
    settings = Settings(
        database_url=":memory:",
        provider_type="padiem_core",
        padiem_core_b14_base_url="https://example.invalid",
        padiem_core_model="b14/auto",
        padiem_core_timeout_seconds=12,
    )

    provider = create_provider(settings)

    assert isinstance(provider, PadiemCoreProvider)
    assert isinstance(provider, AIProvider)
    assert provider.provider_type == "padiem_core"
    assert provider.model == "b14/auto"
