"""Cross-runtime projection of Core Web / Grounded Research through Engine.

The Engine owns only the trusted internal wire and runtime composition. Web
provider selection, URL safety, source quality, grounding, evidence and
research budgets remain Padiem AI Core authority. B14 remains the only model
execution/routing authority used for planning and synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping, Protocol

from padiem_ai_core import (
    AgentProfile,
    ExecutionRequest,
    ExecutionResult,
    ExecutionRuntimeError,
    GroundedResearchResult,
    GroundedResearchRuntime,
    GroundedSynthesisResult,
    GroundingRuntimeError,
    MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
    MAX_QUERY_CHARS,
)

from app.service import (
    ServiceContractError,
    ServiceResponse,
    _service_error,
    _status_for_runtime_error,
    build_execution_request,
)

RESEARCH_PATH = "/internal/v1/research"
MAX_RESEARCH_REQUEST_BODY_BYTES = 128 * 1024

_OPERATIONS = frozenset({"search", "fetch", "deep_research"})
_TOP_LEVEL_REQUIRED = frozenset({"app_id", "operation", "query", "agent"})
_TOP_LEVEL_ALLOWED = frozenset(
    {
        "app_id",
        "operation",
        "query",
        "url",
        "agent",
        "additional_system_context",
        "trace_id",
    }
)


class ExecutionRunner(Protocol):
    async def run(self, request: ExecutionRequest) -> ExecutionResult: ...


ResearchRuntimeFactory = Callable[[str], GroundedResearchRuntime]
ExecutionRuntimeFactory = Callable[[str], ExecutionRunner]


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    app_id: str
    operation: str
    query: str
    url: str | None
    agent: AgentProfile
    additional_system_context: str | None
    trace_id: str | None


class ResearchContractError(ValueError):
    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _exact_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchContractError(
            "invalid_research_request",
            "Research request must be an object.",
        )
    data = dict(value)
    if set(data) - _TOP_LEVEL_ALLOWED:
        raise ResearchContractError(
            "invalid_research_request",
            "Research request contains unsupported fields.",
        )
    if _TOP_LEVEL_REQUIRED - set(data):
        raise ResearchContractError(
            "invalid_research_request",
            "Research request is missing required fields.",
        )
    return data


def _query(value: Any) -> str:
    if not isinstance(value, str):
        raise ResearchContractError(
            "invalid_research_request",
            "query must be a non-empty string.",
        )
    text = value.strip()
    if not text or len(text) > MAX_QUERY_CHARS:
        raise ResearchContractError(
            "invalid_research_request",
            "query exceeds the bounded research limit.",
        )
    return text


def _additional_system_context(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchContractError(
            "invalid_research_request",
            "additional_system_context must be text.",
        )
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS:
        raise ResearchContractError(
            "invalid_research_request",
            "additional_system_context exceeds the bounded context limit.",
        )
    return text


def build_research_request(payload: Any) -> ResearchRequest:
    data = _exact_object(payload)
    operation = data.get("operation")
    if operation not in _OPERATIONS:
        raise ResearchContractError(
            "invalid_research_operation",
            "Research operation must be search, fetch, or deep_research.",
        )

    query = _query(data.get("query"))
    url = data.get("url")
    if operation == "fetch":
        if not isinstance(url, str) or not url.strip():
            raise ResearchContractError(
                "invalid_research_request",
                "fetch research requires a URL.",
            )
        url = url.strip()
    elif url is not None:
        raise ResearchContractError(
            "invalid_research_request",
            "url is supported only for fetch research.",
        )

    # Reuse the accepted /execute interpretation of app/agent fields instead
    # of creating a second Engine model-routing contract.
    execute_shape: dict[str, Any] = {
        "app_id": data["app_id"],
        "agent": data["agent"],
        "messages": [{"role": "user", "content": query}],
    }
    if data.get("trace_id") is not None:
        execute_shape["trace_id"] = data["trace_id"]
    try:
        app_id, execution_request, _context = build_execution_request(execute_shape)
    except ServiceContractError as exc:
        raise ResearchContractError(
            exc.code,
            exc.safe_message,
            status_code=exc.status_code,
        ) from None

    return ResearchRequest(
        app_id=app_id,
        operation=operation,
        query=query,
        url=url,
        agent=execution_request.agent,
        additional_system_context=_additional_system_context(
            data.get("additional_system_context")
        ),
        trace_id=execution_request.trace_id,
    )


def _research_runtime_error(exc: GroundingRuntimeError) -> ServiceResponse:
    return _service_error(
        exc.code,
        exc.message,
        status_code=exc.status_code,
        retryable=exc.status_code in {502, 503, 504},
    )


def _public_result(
    *,
    request: ResearchRequest,
    result: GroundedSynthesisResult | GroundedResearchResult,
) -> ServiceResponse:
    synthesis = result.synthesis
    if not isinstance(synthesis, ExecutionResult):
        return _service_error(
            "invalid_research_result",
            "Padiem AI Engine returned an invalid research synthesis result.",
            status_code=500,
        )

    body: dict[str, Any] = {
        "ok": True,
        "operation": request.operation,
        "answer": synthesis.answer,
        "route": synthesis.route.to_public_dict(),
        "metadata": synthesis.metadata.to_public_dict(),
        "sources": [item.to_public_dict() for item in result.prepared.evidence],
        "research": None,
    }
    if isinstance(result, GroundedResearchResult):
        body["research"] = {
            **result.progress.to_public_dict(),
            "planner_fallback": bool(result.planner_fallback),
        }
    return ServiceResponse(status_code=200, body=body)


class WebResearchEngineService:
    """Bounded internal Engine projection over Core GroundedResearchRuntime."""

    def __init__(
        self,
        *,
        research_runtime_factory: ResearchRuntimeFactory,
        execution_runtime_factory: ExecutionRuntimeFactory,
        b14_service_bound: bool,
    ) -> None:
        if not callable(research_runtime_factory) or not callable(
            execution_runtime_factory
        ):
            raise ValueError("research and execution runtime factories must be callable")
        self._research_runtime_factory = research_runtime_factory
        self._execution_runtime_factory = execution_runtime_factory
        self._b14_service_bound = bool(b14_service_bound)

    async def research_payload(self, payload: Any) -> ServiceResponse:
        if not self._b14_service_bound:
            return _service_error(
                "b14_service_unavailable",
                "Business 14 service binding is unavailable.",
                status_code=503,
                retryable=True,
            )
        try:
            request = build_research_request(payload)
        except ResearchContractError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
            )

        try:
            research_runtime = self._research_runtime_factory(request.app_id)
            execution_runtime = self._execution_runtime_factory(request.app_id)
        except Exception:
            return _service_error(
                "web_runtime_unavailable",
                "Padiem AI Engine web runtime is unavailable.",
                status_code=503,
                retryable=True,
            )

        async def synthesize(grounded_context: str) -> ExecutionResult:
            execution_request = ExecutionRequest(
                agent=request.agent,
                messages=({"role": "user", "content": request.query},),
                additional_system_context=grounded_context,
                trace_id=request.trace_id,
            )
            return await execution_runtime.run(execution_request)

        async def plan(query: str) -> str:
            # Planner identity/instruction are Engine-owned and product-neutral.
            # Callers cannot submit a compiled planner or widen capabilities.
            planner_agent = AgentProfile(
                id="engine-research-planner",
                title="Research query planner",
                description="Produces bounded public-web queries for Core research.",
                system_instruction=(
                    "Return exactly one JSON object with key queries and 1 to 3 "
                    "concise search query strings. Do not include prose, markdown, "
                    "tools, URLs, credentials, or private reasoning."
                ),
                task_type="general",
                optimize_for="balanced",
                max_tokens=240,
                allowed_tools=(),
                required_capabilities=(),
                model_policy={},
                max_steps=1,
            )
            planner_result = await execution_runtime.run(
                ExecutionRequest(
                    agent=planner_agent,
                    messages=({"role": "user", "content": query},),
                    trace_id=request.trace_id,
                )
            )
            return planner_result.answer

        try:
            if request.operation == "search":
                result = await research_runtime.run_search(
                    request.query,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            elif request.operation == "fetch":
                assert request.url is not None
                result = await research_runtime.run_fetch(
                    request.url,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
            else:
                result = await research_runtime.run_deep_research(
                    request.query,
                    planner=plan,
                    synthesizer=synthesize,
                    additional_system_context=request.additional_system_context,
                    max_total_context_chars=MAX_ADDITIONAL_SYSTEM_CONTEXT_CHARS,
                )
        except GroundingRuntimeError as exc:
            return _research_runtime_error(exc)
        except ExecutionRuntimeError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=_status_for_runtime_error(exc),
                retryable=exc.retryable,
                metadata=exc.metadata.to_public_dict(),
            )
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_research_request",
                "Research request fields are invalid.",
                status_code=400,
            )
        except Exception:
            return _service_error(
                "engine_internal_error",
                "Padiem AI Engine research failed.",
                status_code=500,
            )

        return _public_result(request=request, result=result)

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != RESEARCH_PATH:
            return _service_error(
                "not_found",
                "Internal Engine route not found.",
                status_code=404,
            )
        if normalized_method != "POST":
            return _service_error(
                "method_not_allowed",
                "Method not allowed.",
                status_code=405,
            )
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request",
                "Request body is invalid.",
                status_code=400,
            )
        raw = bytes(body)
        if len(raw) > MAX_RESEARCH_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )
        return await self.research_payload(payload)
