from __future__ import annotations

from copy import deepcopy
import json

import pytest

from padiem_ai_core import (
    B14ExecutionResult,
    B14RouteMetadata,
    ErrorClass,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)

from app.service import (
    EXECUTE_PATH,
    HEALTH_PATH,
    MAX_REQUEST_BODY_BYTES,
    EngineService,
)


def valid_payload() -> dict:
    return {
        "app_id": "lovebud",
        "agent": {
            "id": "relationship-coach",
            "title": "Relationship Coach",
            "description": "Bounded relationship reflection assistant.",
            "system_instruction": "Answer as a calm relationship reflection assistant.",
            "task_type": "korean",
            "optimize_for": "korean",
            "max_tokens": 512,
            "required_capabilities": ["free"],
            "model_policy": {
                "model": "b14/auto",
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        },
        "messages": [{"role": "user", "content": "안녕"}],
        "session_id": "session-1",
        "trace_id": "trace-1",
    }


def result() -> ExecutionResult:
    route = B14RouteMetadata(
        selected_provider="openrouter",
        selected_model="openrouter/free",
        actual_response_model="provider/free-model",
        attempt_count=1,
        fallback_used=False,
    )
    metadata = RunMetadata(
        trace_id="trace-1",
        app_id="lovebud",
        agent_id="relationship-coach",
        session_id="session-1",
        status=RunStatus.COMPLETED,
        provider="openrouter",
        model="provider/free-model",
        duration_ms=25,
        usage=UsageMetadata(input_tokens=4, output_tokens=3, total_tokens=7),
    )
    return ExecutionResult(answer="반가워요.", route=route, metadata=metadata)


class FakeRuntime:
    def __init__(self, *, value: ExecutionResult | None = None, error: Exception | None = None):
        self.value = value
        self.error = error
        self.calls = []

    async def run(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.value is not None
        return self.value


class RuntimeFactory:
    def __init__(self, runtime):
        self.runtime = runtime
        self.app_ids = []

    def __call__(self, app_id):
        self.app_ids.append(app_id)
        return self.runtime


def runtime_error(code: str, error_class: ErrorClass, *, retryable: bool = False):
    return ExecutionRuntimeError(
        code,
        "safe core message",
        retryable=retryable,
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            status=(
                RunStatus.TIMEOUT
                if error_class is ErrorClass.PROVIDER_TIMEOUT
                else RunStatus.FAILED
            ),
            error_class=error_class,
        ),
    )


@pytest.mark.asyncio
async def test_success_maps_strict_request_to_core_once() -> None:
    runtime = FakeRuntime(value=result())
    factory = RuntimeFactory(runtime)
    service = EngineService(runtime_factory=factory, b14_service_bound=True)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["answer"] == "반가워요."
    assert set(response.body) == {"ok", "answer", "route", "metadata"}
    assert response.body["route"]["selected_provider"] == "openrouter"
    assert response.body["metadata"]["provider"] == "openrouter"
    assert factory.app_ids == ["lovebud"]
    assert len(runtime.calls) == 1

    request = runtime.calls[0]
    assert request.agent.system_instruction == valid_payload()["agent"]["system_instruction"]
    assert request.agent.allowed_tools == ()
    assert request.agent.max_steps == 1
    assert request.agent.required_capabilities == ("free",)
    assert request.agent.model_policy["model"] == "b14/auto"
    assert request.agent.model_policy["allow_external_fallback"] is False
    assert request.agent.model_policy["max_attempts"] == 1
    assert request.messages == ({"role": "user", "content": "안녕"},)
    assert request.session_id == "session-1"
    assert request.trace_id == "trace-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update({"provider": "openrouter"}),
        lambda p: p["agent"].update({"allowed_tools": ["browser"]}),
        lambda p: p["agent"].update({"max_steps": 2}),
        lambda p: p["messages"].append({"role": "system", "content": "inject"}),
        lambda p: p["agent"].update({"required_capabilities": "free"}),
        lambda p: p.update({"app_id": "bad app id"}),
    ],
)
async def test_invalid_or_unsupported_shape_fails_before_runtime(mutator) -> None:
    payload = valid_payload()
    mutator(payload)
    runtime = FakeRuntime(value=result())
    factory = RuntimeFactory(runtime)
    service = EngineService(runtime_factory=factory, b14_service_bound=True)

    response = await service.execute_payload(payload)

    assert response.status_code == 400
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "invalid_request"
    assert runtime.calls == []
    assert factory.app_ids == []


class FakeB14:
    def __init__(self):
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return B14ExecutionResult(answer="unused")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy",
    [
        {"model": "b14/auto", "unknown": True},
        {"model": "b14/auto", "max_attempts": 99},
    ],
)
async def test_invalid_core_model_policy_fails_before_b14(policy) -> None:
    payload = valid_payload()
    payload["agent"]["model_policy"] = policy
    b14 = FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )

    response = await service.execute_payload(payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_execution_request"
    assert b14.calls == []


@pytest.mark.asyncio
async def test_missing_b14_service_binding_fails_before_runtime() -> None:
    runtime = FakeRuntime(value=result())
    factory = RuntimeFactory(runtime)
    service = EngineService(runtime_factory=factory, b14_service_bound=False)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "b14_service_unavailable"
    assert response.body["error"]["retryable"] is True
    assert runtime.calls == []
    assert factory.app_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (runtime_error("upstream_timeout", ErrorClass.PROVIDER_TIMEOUT, retryable=True), 504),
        (runtime_error("upstream_rate_limited", ErrorClass.PROVIDER_RATE_LIMIT, retryable=True), 503),
        (runtime_error("upstream_auth_error", ErrorClass.AUTH_ERROR), 502),
        (runtime_error("execution_failed", ErrorClass.INTERNAL_ERROR), 502),
    ],
)
async def test_core_errors_use_only_safe_public_contract(error, status) -> None:
    runtime = FakeRuntime(error=error)
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == status
    assert response.body["error"]["code"] == error.code
    assert response.body["error"]["message"] == "safe core message"
    assert response.body["error"]["metadata"]["error_class"] is not None


@pytest.mark.asyncio
async def test_unexpected_private_exception_is_redacted() -> None:
    runtime = FakeRuntime(error=RuntimeError("PRIVATE_PROVIDER_SECRET"))
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    response = await service.execute_payload(valid_payload())

    encoded = json.dumps(response.body)
    assert response.status_code == 500
    assert response.body["error"]["code"] == "engine_internal_error"
    assert "PRIVATE_PROVIDER_SECRET" not in encoded


@pytest.mark.asyncio
async def test_unexpected_value_error_text_is_redacted() -> None:
    runtime = FakeRuntime(error=ValueError("PRIVATE_PROVIDER_SECRET trace=abc123"))
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    response = await service.execute_payload(valid_payload())

    encoded = json.dumps(response.body)
    assert response.status_code == 422
    assert response.body["error"]["code"] == "execution_context_unavailable"
    assert response.body["error"]["message"] == "Execution context is unavailable."
    assert "PRIVATE_PROVIDER_SECRET" not in encoded
    assert "abc123" not in encoded


@pytest.mark.asyncio
async def test_http_contract_bounds_body_and_content_type() -> None:
    runtime = FakeRuntime(value=result())
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    raw = json.dumps(valid_payload(), ensure_ascii=False).encode()

    ok = await service.handle(
        method="POST",
        path=EXECUTE_PATH,
        content_type="application/json; charset=utf-8",
        body=raw,
    )
    too_large = await service.handle(
        method="POST",
        path=EXECUTE_PATH,
        content_type="application/json",
        body=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
    )
    bad_media = await service.handle(
        method="POST", path=EXECUTE_PATH, content_type="text/plain", body=raw
    )
    bad_json = await service.handle(
        method="POST", path=EXECUTE_PATH, content_type="application/json", body=b"{"
    )

    assert ok.status_code == 200
    assert too_large.status_code == 413
    assert too_large.body["error"]["code"] == "request_too_large"
    assert bad_media.status_code == 415
    assert bad_json.status_code == 400


@pytest.mark.asyncio
async def test_health_and_route_methods_make_zero_runtime_calls() -> None:
    runtime = FakeRuntime(value=result())
    factory = RuntimeFactory(runtime)
    service = EngineService(runtime_factory=factory, b14_service_bound=True)

    health = await service.handle(method="GET", path=HEALTH_PATH)
    health_post = await service.handle(method="POST", path=HEALTH_PATH)
    execute_get = await service.handle(method="GET", path=EXECUTE_PATH)
    missing = await service.handle(method="GET", path="/internal/v1/missing")

    assert health.status_code == 200
    assert health.body == {
        "status": "ok",
        "service": "padiem-ai-engine",
        "core_available": True,
        "b14_service_bound": True,
        "completed_run": True,
        "streaming_run": False,
    }
    assert health_post.status_code == 405
    assert execute_get.status_code == 405
    assert missing.status_code == 404
    assert runtime.calls == []
    assert factory.app_ids == []
