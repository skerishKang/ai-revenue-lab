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
    # Liveness separated from feature readiness (#1237)
    assert health.body["status"] == "ok"
    assert health.body["service"] == "padiem-ai-engine"
    assert health.body["core_available"] is True
    assert health.body["b14_service_bound"] is True
    # Backward-compat booleans derived from bounded capabilities
    assert health.body["completed_run"] is True
    assert health.body["streaming_run"] is True
    # Explicit bounded posture – health must carry capabilities
    assert "capabilities" in health.body
    assert health.body["capabilities"]["completed_run"] == "available"
    assert health.body["capabilities"]["provider_streaming_run"] == "available"
    assert health_post.status_code == 405
    assert execute_get.status_code == 405
    assert missing.status_code == 404
    assert runtime.calls == []
    assert factory.app_ids == []


# --- #1237 regression: A-I -----------------------------------------------


@pytest.mark.asyncio
async def test_health_succeeds_without_caller_credential() -> None:
    service = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    health = await service.handle(method="GET", path=HEALTH_PATH, content_type=None, body=b"")
    assert health.status_code == 200
    assert health.body["status"] == "ok"


@pytest.mark.asyncio
async def test_liveness_remains_ok_when_b14_absent() -> None:
    service = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=False)
    health = await service.handle(method="GET", path=HEALTH_PATH)
    assert health.status_code == 200
    assert health.body["status"] == "ok"
    assert health.body["b14_service_bound"] is False
    assert health.body["core_available"] is True


@pytest.mark.asyncio
async def test_b14_binding_state_is_truthful() -> None:
    svc_bound = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    svc_unbound = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=False)
    h_bound = await svc_bound.handle(method="GET", path=HEALTH_PATH)
    h_unbound = await svc_unbound.handle(method="GET", path=HEALTH_PATH)
    assert h_bound.body["b14_service_bound"] is True
    assert h_unbound.body["b14_service_bound"] is False


def test_implemented_but_blocked_orchestration_not_available():
    # Orchestration stream is not routed at Worker boundary → must not be AVAILABLE
    from app.contract_manifest import current_engine_contract_manifest

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("orchestration_stream").value != "available"
    assert manifest.feature_state("orchestration_stream").value in ("deferred", "unavailable")


def test_deferred_idempotency_not_reported_available():
    from app.contract_manifest import current_engine_contract_manifest

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("idempotency_replay").value != "available"
    assert manifest.feature_state("execution_idempotency_replay_completed").value != "available"


def test_unrouted_orchestration_stream_not_available():
    from app.contract_manifest import current_engine_contract_manifest

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("orchestration_stream").value in ("deferred", "unavailable")
    svc = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    health = svc.health()
    assert health.body["capabilities"]["orchestration_stream"] in ("deferred", "unavailable")
    assert health.body["capabilities"]["idempotency_replay"] in ("deferred", "unavailable")


@pytest.mark.asyncio
async def test_manifest_and_health_cannot_disagree():
    from app.contract_manifest import current_engine_contract_manifest

    manifest = current_engine_contract_manifest()
    svc = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    health = await svc.handle(method="GET", path=HEALTH_PATH)
    caps = health.body["capabilities"]
    for fid in ("completed_run", "provider_streaming_run", "orchestration_run", "orchestration_resume", "orchestration_cancel", "orchestration_stream", "idempotency_replay", "service_identity_wire_enforcement"):
        assert caps[fid] == manifest.feature_state(fid).value


def test_no_secret_projection_in_health():
    svc = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    health = svc.health()
    serialized = json.dumps(health.body).lower()
    for forbidden in ("api_key", "authorization", "credential_sha256", "credential", "account_id", "secret"):
        assert forbidden not in serialized


def test_service_identity_posture_includes_all_authenticated_non_health_routes():
    svc = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    health = svc.health()
    # Service identity must mention all non-health routes
    identity = str(health.body.get("service_identity", ""))
    # Must mention orchestration
    assert "orchestration" in identity.lower() or "all_non_health" in identity.lower()
    # Endpoints declared in manifest must include orchestration paths
    from app.contract_manifest import current_engine_contract_manifest

    manifest = current_engine_contract_manifest()
    paths = {e.path for e in manifest.endpoints}
    assert "/internal/v1/execute" in paths
    assert "/internal/v1/health" in paths
    assert "/internal/v1/orchestrate" in paths


def test_health_manifest_failure_fallback_does_not_advertise_available():
    # Simulate manifest/posture source failure — health must stay liveness ok but fail closed on readiness
    import app.contract_manifest as cm
    from unittest.mock import patch

    svc = EngineService(runtime_factory=lambda app_id: FakeRuntime(value=result()), b14_service_bound=True)
    with patch.object(cm, "engine_capability_posture", side_effect=RuntimeError("INTERNAL_POSTURE_FAILURE")):
        with patch.object(cm, "current_engine_contract_manifest", side_effect=RuntimeError("INTERNAL_MANIFEST_FAILURE")):
            health = svc.health()
            serialized = json.dumps(health.body).lower()
            assert health.status_code == 200
            assert health.body["status"] == "ok"
            # Liveness preserved, but no feature may be advertised as available
            caps = health.body.get("capabilities", {})
            for fid in ("completed_run", "provider_streaming_run", "orchestration_run", "orchestration_resume", "orchestration_cancel", "service_identity_wire_enforcement"):
                assert caps.get(fid) != "available", f"{fid} must not be available on fallback"
                assert caps.get(fid) in ("deferred", "unavailable")
            # Backward-compat booleans must also be false (not hiding deferred)
            assert health.body.get("completed_run") is False
            assert health.body.get("streaming_run") is False
            # Must not leak exception text or secrets
            assert "internal_posture_failure" not in serialized
            assert "internal_manifest_failure" not in serialized
            assert "api_key" not in serialized
            assert "credential" not in serialized
