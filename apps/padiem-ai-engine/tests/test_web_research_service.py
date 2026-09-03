from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    Evidence,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeError,
    GroundedResearchRuntime,
    MockWebProvider,
    RunMetadata,
    RunStatus,
    WebRuntimeError,
)

from app.web_research_service import (
    MAX_RESEARCH_REQUEST_BODY_BYTES,
    RESEARCH_PATH,
    WebResearchEngineService,
)


APP_ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def agent_payload() -> dict[str, object]:
    return {
        "id": "reference-research-agent",
        "title": "Reference research agent",
        "description": "Network-free Engine research test agent.",
        "system_instruction": "Answer only from the grounded context.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 400,
    }


def request_payload(
    operation: str = "search",
    *,
    query: str = "current policy",
    url: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "app_id": "reference-product",
        "operation": operation,
        "query": query,
        "agent": agent_payload(),
        "trace_id": "research-trace",
    }
    if url is not None:
        payload["url"] = url
    return payload


class RecordingExecutionRuntime:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        if request.agent.id == "engine-research-planner":
            answer = '{"queries":["query one","query two"]}'
        else:
            assert request.additional_system_context is not None
            assert "웹 근거 사용 규칙" in request.additional_system_context
            answer = "grounded answer"
        return ExecutionResult(
            answer=answer,
            route=B14RouteMetadata(
                request_id="b14-request",
                selected_provider="fake-provider",
                selected_model="fake-model",
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "generated-trace",
                app_id="reference-product",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class TimeoutProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        raise WebRuntimeError("web_timeout", "web request timed out", 504)

    async def fetch(self, url: str) -> Evidence:
        raise WebRuntimeError("web_timeout", "web request timed out", 504)


class CancelledProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        raise asyncio.CancelledError()

    async def fetch(self, url: str) -> Evidence:
        raise asyncio.CancelledError()


class UnsafeEvidenceProvider:
    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        return [
            Evidence(
                id="unsafe-source",
                title="Current policy",
                snippet="Current policy details",
                retrieved_at="2026-09-03T00:00:00Z",
                provider="test",
                source_type="search",
                url="http://127.0.0.1/private",
            )
        ]

    async def fetch(self, url: str) -> Evidence:
        raise AssertionError("fetch is not used in this test")


class SecretBearingProvider:
    private_runtime_secret = "PRIVATE-RUNTIME-BYTES"

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        return [
            Evidence(
                id="public-source",
                title="Current policy",
                snippet="Current policy details",
                retrieved_at="2026-09-03T00:00:00Z",
                provider="test",
                source_type="search",
                url="https://example.com/policy",
            )
        ]

    async def fetch(self, url: str) -> Evidence:
        return Evidence(
            id="public-fetch",
            title="Public page",
            snippet="Public page details",
            retrieved_at="2026-09-03T00:00:00Z",
            provider="test",
            source_type="fetch",
            url=url,
        )


def service(
    *,
    execution_runtime: RecordingExecutionRuntime | None = None,
    provider=None,
    b14_service_bound: bool = True,
) -> tuple[WebResearchEngineService, RecordingExecutionRuntime]:
    execution = execution_runtime or RecordingExecutionRuntime()
    web_provider = provider or MockWebProvider()
    return (
        WebResearchEngineService(
            research_runtime_factory=lambda _app_id: GroundedResearchRuntime(web_provider),
            execution_runtime_factory=lambda _app_id: execution,
            b14_service_bound=b14_service_bound,
        ),
        execution,
    )


def test_search_projects_core_grounding_and_public_sources() -> None:
    svc, execution = service()
    result = run(svc.research_payload(request_payload("search")))

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["operation"] == "search"
    assert result.body["answer"] == "grounded answer"
    assert result.body["research"] is None
    assert "route" not in result.body
    assert "metadata" not in result.body
    assert len(result.body["sources"]) == 5
    assert result.body["sources"][0]["provider"] == "mock"
    assert len(execution.requests) == 1
    assert execution.requests[0].agent.id == "reference-research-agent"


def test_fetch_projects_core_url_safety_and_grounding() -> None:
    svc, execution = service()
    result = run(
        svc.research_payload(
            request_payload(
                "fetch",
                query="explain this page",
                url="https://example.com/public-page",
            )
        )
    )

    assert result.status_code == 200
    assert result.body["answer"] == "grounded answer"
    assert len(result.body["sources"]) == 1
    assert result.body["sources"][0]["source_type"] == "fetch"
    assert len(execution.requests) == 1


def test_unsafe_fetch_fails_before_model_synthesis() -> None:
    svc, execution = service()
    result = run(
        svc.research_payload(
            request_payload(
                "fetch",
                query="read admin",
                url="http://127.0.0.1/admin",
            )
        )
    )

    assert result.status_code == 422
    assert result.body["error"]["code"] == "invalid_tool_input"
    assert execution.requests == []


def test_deep_research_uses_engine_owned_planner_and_core_limits() -> None:
    svc, execution = service()
    result = run(svc.research_payload(request_payload("deep_research", query="research topic")))

    assert result.status_code == 200
    assert result.body["answer"] == "grounded answer"
    assert result.body["research"]["queries_planned"] == 2
    assert result.body["research"]["searches_completed"] == 2
    assert result.body["research"]["planner_fallback"] is False
    assert len(execution.requests) == 2
    assert execution.requests[0].agent.id == "engine-research-planner"
    assert execution.requests[0].agent.allowed_tools == ()
    assert execution.requests[0].agent.max_steps == 1
    assert execution.requests[1].agent.id == "reference-research-agent"


def test_product_additional_context_is_composed_by_core_not_returned() -> None:
    svc, execution = service()
    payload = request_payload("search")
    payload["additional_system_context"] = "TRUSTED PRODUCT CONTEXT"
    result = run(svc.research_payload(payload))

    assert result.status_code == 200
    combined = execution.requests[0].additional_system_context
    assert combined is not None
    assert combined.startswith("TRUSTED PRODUCT CONTEXT\n\n웹 근거 사용 규칙")
    assert "TRUSTED PRODUCT CONTEXT" not in json.dumps(result.body, ensure_ascii=False)


def test_web_provider_authority_fields_are_not_accepted_from_request() -> None:
    svc, execution = service()
    for field, value in (
        ("provider", "firecrawl"),
        ("firecrawl_api_key", "PRIVATE-KEY"),
        ("endpoint", "https://attacker.example"),
        ("max_page_fetches", 999),
    ):
        payload = request_payload("search")
        payload[field] = value
        result = run(svc.research_payload(payload))
        assert result.status_code == 400
        assert result.body["error"]["code"] == "invalid_research_request"
    assert execution.requests == []


def test_url_is_rejected_for_non_fetch_operation() -> None:
    svc, execution = service()
    result = run(
        svc.research_payload(
            request_payload(
                "search",
                url="https://example.com/should-not-be-accepted",
            )
        )
    )
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_request"
    assert execution.requests == []


def test_web_timeout_is_normalized_and_retryable() -> None:
    svc, execution = service(provider=TimeoutProvider())
    result = run(svc.research_payload(request_payload("search")))

    assert result.status_code == 504
    assert result.body["error"]["code"] == "web_timeout"
    assert result.body["error"]["retryable"] is True
    assert execution.requests == []


def test_cancellation_propagates_without_engine_normalization() -> None:
    svc, execution = service(provider=CancelledProvider())

    with pytest.raises(asyncio.CancelledError):
        run(svc.research_payload(request_payload("search")))
    assert execution.requests == []


def test_source_trust_rejection_stays_rejected_before_synthesis() -> None:
    svc, execution = service(provider=UnsafeEvidenceProvider())
    result = run(svc.research_payload(request_payload("search")))

    assert result.status_code == 404
    assert result.body["error"]["code"] == "no_evidence"
    assert execution.requests == []


def test_public_evidence_projection_excludes_provider_private_runtime_bytes() -> None:
    svc, execution = service(provider=SecretBearingProvider())
    result = run(svc.research_payload(request_payload("search")))

    assert result.status_code == 200
    assert len(execution.requests) == 1
    assert set(result.body["sources"][0]) == {
        "id",
        "title",
        "url",
        "snippet",
        "retrieved_at",
        "provider",
        "source_type",
    }
    serialized = json.dumps(result.body, ensure_ascii=False)
    assert SecretBearingProvider.private_runtime_secret not in serialized
    assert "route" not in result.body
    assert "metadata" not in result.body


def test_execution_failure_does_not_project_b14_or_run_metadata() -> None:
    private_metadata = RunMetadata(
        trace_id="private-trace",
        app_id="reference-product",
        agent_id="reference-research-agent",
        status=RunStatus.FAILED,
        provider="privateprovider",
        model="private-model",
    )

    class FailingExecutionRuntime:
        async def run(self, request: ExecutionRequest) -> ExecutionResult:
            raise ExecutionRuntimeError(
                "upstream_timeout",
                "Model execution timed out.",
                metadata=private_metadata,
                retryable=True,
            )

    svc = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: GroundedResearchRuntime(MockWebProvider()),
        execution_runtime_factory=lambda _app_id: FailingExecutionRuntime(),
        b14_service_bound=True,
    )
    result = run(svc.research_payload(request_payload("search")))

    assert result.status_code == 504
    assert result.body["error"]["code"] == "upstream_timeout"
    assert result.body["error"]["metadata"] is None
    serialized = json.dumps(result.body, ensure_ascii=False)
    assert "privateprovider" not in serialized
    assert "private-model" not in serialized
    assert "private-trace" not in serialized


def test_missing_b14_binding_fails_before_web_or_execution_factory() -> None:
    called = False

    def unreachable(_app_id):
        nonlocal called
        called = True
        raise AssertionError("factory must not run")

    svc = WebResearchEngineService(
        research_runtime_factory=unreachable,
        execution_runtime_factory=unreachable,
        b14_service_bound=False,
    )
    result = run(svc.research_payload(request_payload("search")))
    assert result.status_code == 503
    assert result.body["error"]["code"] == "b14_service_unavailable"
    assert called is False


def test_invalid_runtime_factory_failure_is_safe() -> None:
    def broken(_app_id):
        raise RuntimeError("PRIVATE WEB CONFIG DETAIL")

    svc = WebResearchEngineService(
        research_runtime_factory=broken,
        execution_runtime_factory=broken,
        b14_service_bound=True,
    )
    result = run(svc.research_payload(request_payload("search")))
    serialized = json.dumps(result.body)
    assert result.status_code == 503
    assert result.body["error"]["code"] == "web_runtime_unavailable"
    assert "PRIVATE WEB CONFIG DETAIL" not in serialized


def test_http_contract_is_json_post_only_and_bounded() -> None:
    svc, _ = service()
    assert run(svc.handle(method="GET", path=RESEARCH_PATH)).status_code == 405
    assert run(
        svc.handle(
            method="POST",
            path=RESEARCH_PATH,
            content_type="text/plain",
            body=b"{}",
        )
    ).status_code == 415
    oversized = b"{" + b"x" * MAX_RESEARCH_REQUEST_BODY_BYTES + b"}"
    assert run(
        svc.handle(
            method="POST",
            path=RESEARCH_PATH,
            content_type="application/json",
            body=oversized,
        )
    ).status_code == 413


def test_source_is_product_neutral_and_has_no_request_web_secret_authority() -> None:
    source = (APP_ROOT / "app" / "web_research_service.py").read_text(encoding="utf-8")
    worker_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    for forbidden in (
        "storymemory-b61",
        "lovebud-scout",
        "400-ai-finder",
        "padiem-sidecar",
    ):
        assert forbidden not in source
        assert forbidden not in worker_source

    assert '"provider"' not in source
    assert '"firecrawl_api_key"' not in source
    assert '"daum_rest_api_key"' not in source
    assert "PADIEM_ENGINE_WEB_PROVIDER" in worker_source
    assert "PADIEM_ENGINE_FIRECRAWL_API_KEY" in worker_source
    assert "PADIEM_ENGINE_DAUM_REST_API_KEY" in worker_source
